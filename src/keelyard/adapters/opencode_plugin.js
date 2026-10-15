// keelyard adapter for OpenCode, installed to .opencode/plugins/keelyard.js by `keelyard install opencode`.
// One file for both plugin APIs: OpenCode 2.x calls setup(ctx); OpenCode 1.x (>= 1.18.29) calls server().
// Both translate OpenCode events into keelyard's shared hook format (`keelyard hook opencode <event>`).
import { spawn } from "node:child_process";

const KEELYARD = "keelyard"; // replaced with the absolute path by `keelyard install opencode`

function run(event, payload) {
  return new Promise((resolve) => {
    let out = "";
    let child;
    try {
      child = spawn(KEELYARD, ["hook", "opencode", event], { stdio: ["pipe", "pipe", "ignore"], windowsHide: true });
    } catch {
      return resolve(null);
    }
    const timer = setTimeout(() => child.kill(), event === "Stop" ? 900000 : 60000);
    child.stdout.on("data", (d) => (out += d));
    child.on("error", () => { clearTimeout(timer); resolve(null); });
    child.on("close", () => {
      clearTimeout(timer);
      try { resolve(out.trim() ? JSON.parse(out) : null); } catch { resolve(null); } // never break the agent
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

// Shared state and translation, independent of the plugin API version.
function core(directory) {
  const notes = []; // hints waiting for the model's next request
  const briefs = new Map(); // per session: the brief, kept through compaction
  const pending = new Map(); // call id -> tool input
  const hook = (event, payload) => run(event, { ...payload, cwd: directory });
  const context = (res) => res?.hookSpecificOutput?.additionalContext;
  return {
    async system(sid) {
      if (!briefs.has(sid)) briefs.set(sid, context(await hook("SessionStart", { session_id: sid, source: "startup" })) || "");
      const parts = briefs.get(sid) ? [briefs.get(sid)] : [];
      while (notes.length) parts.push(notes.shift());
      return parts;
    },
    async compact(sid) {
      return context(await hook("SessionStart", { session_id: sid, source: "compact" }));
    },
    async prompt(sid, text) {
      if (!text) return;
      const c = context(await hook("UserPromptSubmit", { session_id: sid, prompt: text }));
      if (c) notes.push(c);
    },
    // Throws to deny: OpenCode shows the reason to the model.
    async before(sid, id, tool, input) {
      pending.set(id, input || {});
      const h = (await hook("PreToolUse", { session_id: sid, tool_name: tool, tool_input: input || {} }))?.hookSpecificOutput;
      if (h?.permissionDecision === "deny") throw new Error(h.permissionDecisionReason);
      if (h?.additionalContext) notes.push(h.additionalContext);
    },
    // Returns a smaller text to show the model instead of `output`, or null.
    async after(sid, id, tool, output) {
      const input = pending.get(id) || {};
      pending.delete(id);
      const res = await hook("PostToolUse", {
        session_id: sid, tool_name: tool, tool_input: input,
        tool_response: typeof output === "string" ? { stdout: output, stderr: "" } : undefined,
      });
      const h = res?.hookSpecificOutput;
      if (h?.additionalContext) notes.push(h.additionalContext);
      return h?.updatedToolOutput?.stdout ?? null;
    },
    async stop(sid) {
      const res = await hook("Stop", { session_id: sid });
      return res?.decision === "block" ? res.reason : null;
    },
  };
}

const textOf = (content) =>
  typeof content === "string" ? content
    : Array.isArray(content) ? content.filter((c) => c?.type === "text").map((c) => c.text).join("\n") : null;

export default {
  id: "keelyard",

  // OpenCode 2.x
  async setup(ctx) {
    const k = core(ctx.location?.directory || process.cwd());
    await ctx.mcp.transform((editor) => {
      if (!editor.get("keelyard")) editor.set("keelyard", { type: "local", command: [KEELYARD, "mcp"] });
    });
    await ctx.session.hook("context", async (event) => {
      for (const text of await k.system(event.sessionID)) event.system.push({ type: "text", text });
    });
    await ctx.session.hook("compaction", async (event) => {
      const c = await k.compact(event.sessionID);
      if (c) event.system.push({ type: "text", text: c });
    });
    await ctx.session.hook("prompt", async (event) => {
      await k.prompt(event.sessionID, event.prompt?.text);
    });
    await ctx.tool.hook("execute.before", (event) => k.before(event.sessionID, event.id, event.tool, event.input));
    await ctx.tool.hook("execute.after", async (event) => {
      const raw = event.status === "completed" ? textOf(event.result?.content) : null;
      const small = await k.after(event.sessionID, event.id, event.tool, raw);
      if (small && event.status === "completed") event.result = { ...event.result, content: small };
    });
    const controller = new AbortController();
    void (async () => {
      try {
        for await (const ev of ctx.event.subscribe({ signal: controller.signal })) {
          if (ev?.type !== "session.idle") continue;
          const sid = ev.data?.sessionID;
          const reason = sid && (await k.stop(sid));
          // OpenCode cannot veto "idle", so the gate replies with the missing proof as a new prompt.
          if (reason) await ctx.session.prompt({ sessionID: sid, text: reason });
        }
      } catch { /* subscription closed */ }
    })();
    return () => controller.abort();
  },

  // OpenCode 1.x
  async server({ directory, client }) {
    const k = core(directory);
    return {
      "experimental.chat.system.transform": async (input, output) => {
        for (const text of await k.system(input?.sessionID)) output.system.push(text);
      },
      "experimental.session.compacting": async (input, output) => {
        const c = await k.compact(input?.sessionID);
        if (c) output.context.push(c);
      },
      "chat.message": async (input, output) => {
        await k.prompt(input.sessionID, (output?.parts || []).filter((p) => p.type === "text").map((p) => p.text).join("\n"));
      },
      "tool.execute.before": (input, output) => k.before(input.sessionID, input.callID, input.tool, output.args),
      "tool.execute.after": async (input, output) => {
        const small = await k.after(input.sessionID, input.callID, input.tool, typeof output?.output === "string" ? output.output : null);
        if (small && typeof output?.output === "string") output.output = small;
      },
      event: async ({ event }) => {
        if (event.type !== "session.idle") return;
        const sid = event.properties?.sessionID;
        const reason = sid && (await k.stop(sid));
        if (reason) await client.session.prompt({ path: { id: sid }, body: { parts: [{ type: "text", text: reason }] } });
      },
    };
  },
};
