// keelyard adapter for OpenCode. Installed to .opencode/plugin/keelyard.js by `keelyard install opencode`.
// Translates OpenCode plugin events into keelyard's shared hook format.
const KEELYARD = "keelyard"; // replaced with the absolute path by `keelyard install opencode`

export const Keelyard = async ({ $, directory, client }) => {
  const pending = new Map();
  const notes = []; // keelyard hints waiting for the model's next turn
  const briefs = new Map(); // per session: the brief sent in the system prompt and kept through compaction
  const hook = async (event, payload) => {
    const body = JSON.stringify({ ...payload, cwd: directory });
    try {
      const out = await $`${KEELYARD} hook opencode ${event} < ${new Response(body)}`.quiet().nothrow().text();
      return out.trim() ? JSON.parse(out) : null;
    } catch {
      return null; // never break the agent
    }
  };
  const context = (res) => res?.hookSpecificOutput?.additionalContext;
  const ensureBrief = async (sid) => {
    if (!briefs.has(sid)) briefs.set(sid, context(await hook("SessionStart", { session_id: sid, source: "startup" })) || "");
    return briefs.get(sid);
  };
  return {
    // OpenCode >= 1.0: add the brief and any queued hints to the system prompt of each model call.
    "experimental.chat.system.transform": async (input, output) => {
      const b = await ensureBrief(input?.sessionID);
      if (b) output.system.push(b);
      while (notes.length) output.system.push(notes.shift());
    },
    // Keep the brief in the summary OpenCode writes when it compacts the session.
    "experimental.session.compacting": async (input, output) => {
      const res = await hook("SessionStart", { session_id: input?.sessionID, source: "compact" });
      if (context(res)) output.context.push(context(res));
    },
    "chat.message": async (input, output) => {
      const text = (output?.parts || []).filter((p) => p.type === "text").map((p) => p.text).join("\n");
      if (!text) return;
      const res = await hook("UserPromptSubmit", { session_id: input.sessionID, prompt: text });
      if (context(res)) notes.push(context(res));
    },
    "tool.execute.before": async (input, output) => {
      pending.set(input.callID, output.args);
      const res = await hook("PreToolUse", { session_id: input.sessionID, tool_name: input.tool, tool_input: output.args });
      const h = res?.hookSpecificOutput;
      if (h?.permissionDecision === "deny") throw new Error(h.permissionDecisionReason); // the model reads this
      if (h?.additionalContext) notes.push(h.additionalContext);
    },
    "tool.execute.after": async (input) => {
      const args = pending.get(input.callID) || {};
      pending.delete(input.callID);
      await hook("PostToolUse", { session_id: input.sessionID, tool_name: input.tool, tool_input: args });
    },
    event: async ({ event }) => {
      if (event.type !== "session.idle") return;
      const sid = event.properties?.sessionID;
      const res = await hook("Stop", { session_id: sid });
      if (res?.decision === "block" && sid) {
        // OpenCode cannot veto "idle", so the gate replies with the missing proof as a new prompt.
        await client.session.prompt({ path: { id: sid }, body: { parts: [{ type: "text", text: res.reason }] } });
      }
    },
  };
};
