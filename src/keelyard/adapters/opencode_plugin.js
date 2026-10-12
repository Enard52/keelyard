// keelyard adapter for OpenCode. Installed to .opencode/plugin/keelyard.js by `keelyard install opencode`.
// Translates OpenCode plugin events into keelyard's shared hook format.
const KEELYARD = "keelyard"; // replaced with the absolute path by `keelyard install opencode`

export const Keelyard = async ({ $, directory, client }) => {
  const pending = new Map();
  const hook = async (event, payload) => {
    const body = JSON.stringify({ ...payload, cwd: directory });
    try {
      const out = await $`${KEELYARD} hook opencode ${event} < ${new Response(body)}`.quiet().nothrow().text();
      return out.trim() ? JSON.parse(out) : null;
    } catch {
      return null; // never break the agent
    }
  };
  return {
    "tool.execute.before": async (input, output) => {
      pending.set(input.callID, output.args);
      await hook("PreToolUse", { session_id: input.sessionID, tool_name: input.tool, tool_input: output.args });
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
