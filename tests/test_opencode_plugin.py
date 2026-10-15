"""The OpenCode plugin runs under both plugin APIs (2.x setup(ctx), 1.x server()) with a fake keelyard."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from keelyard.hooks import handle

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "src" / "keelyard" / "adapters" / "opencode_plugin.js"
pytestmark = pytest.mark.skipif(not shutil.which("node") or os.name == "nt", reason="needs node and a POSIX fake executable")

FAKE = r'''#!/usr/bin/env python3
import json, sys
ev = sys.argv[3]; p = json.load(sys.stdin)
open(sys.argv[0] + ".log", "a").write(json.dumps([ev, p]) + "\n")
ctx = lambda t: {"hookSpecificOutput": {"additionalContext": t}}
if ev == "SessionStart": print(json.dumps(ctx("BRIEF " + p.get("source", ""))))
elif ev == "UserPromptSubmit": print(json.dumps(ctx("RECALL")))
elif ev == "PreToolUse" and "rm -rf" in json.dumps(p.get("tool_input")):
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "NO"}}))
elif ev == "PostToolUse" and (p.get("tool_response") or {}).get("stdout"):
    print(json.dumps({"hookSpecificOutput": {"updatedToolOutput": {"stdout": "SMALL"}}}))
elif ev == "Stop": print(json.dumps({"decision": "block", "reason": "PROVE"}))
'''

DRIVER = r'''
import plugin from "./keelyard.mjs";
const out = {};
// ---- OpenCode 2.x
const hooks = {}; const prompts = []; let mcp = null;
let push; const events = { [Symbol.asyncIterator]() { return { next: () => new Promise((r) => (push = r)) }; } };
const ctx = {
  location: { directory: "/proj" },
  mcp: { transform: async (cb) => { const m = new Map(); cb({ get: (k) => m.get(k), set: (k, v) => m.set(k, v) }); mcp = m.get("keelyard"); } },
  session: { hook: async (n, cb) => { hooks["s." + n] = cb; }, prompt: async (x) => prompts.push(x) },
  tool: { hook: async (n, cb) => { hooks["t." + n] = cb; } },
  event: { subscribe: () => events },
};
await plugin.setup(ctx);
const c = { sessionID: "s1", system: [] };
await hooks["s.prompt"]({ sessionID: "s1", prompt: { text: "fix it" } });
await hooks["s.context"](c);
let denied = null;
const rm = { sessionID: "s1", id: "c1", tool: "bash", input: { command: "rm -rf /" } };
try { await hooks["t.execute.before"](rm); } catch (e) { denied = e.message; }
await hooks["t.execute.before"]({ sessionID: "s1", id: "c2", tool: "bash", input: { command: "pytest" } });
const after = { sessionID: "s1", id: "c2", tool: "bash", status: "completed", result: { content: "x".repeat(5000) } };
await hooks["t.execute.after"](after);
push({ done: false, value: { type: "session.idle", data: { sessionID: "s1" } } });
await new Promise((r) => setTimeout(r, 1500));
out.v2 = { mcp, system: c.system.map((s) => s.text), denied, content: after.result.content, prompts };
// ---- OpenCode 1.x
const sent = [];
const h = await plugin.server({ directory: "/proj", client: { session: { prompt: async (x) => sent.push(x) } } });
const sys = { system: [] };
await h["experimental.chat.system.transform"]({ sessionID: "s2" }, sys);
const o = { output: "y".repeat(5000) };
await h["tool.execute.before"]({ sessionID: "s2", callID: "k", tool: "bash" }, { args: { command: "pytest" } });
await h["tool.execute.after"]({ sessionID: "s2", callID: "k", tool: "bash" }, o);
await h.event({ event: { type: "session.idle", properties: { sessionID: "s2" } } });
out.v1 = { system: sys.system, output: o.output, sent };
console.log(JSON.stringify(out));
process.exit(0);
'''


def test_plugin_works_under_opencode_2_and_1(tmp_path):
    fake = tmp_path / "keelyard"
    fake.write_text(FAKE.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
    fake.chmod(0o755)
    js = PLUGIN.read_text().replace('const KEELYARD = "keelyard";', f"const KEELYARD = {json.dumps(str(fake))};", 1)
    (tmp_path / "keelyard.mjs").write_text(js)
    (tmp_path / "driver.mjs").write_text(DRIVER)
    r = subprocess.run(["node", "driver.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    v2, v1 = out["v2"], out["v1"]
    assert v2["mcp"]["command"][1] == "mcp" and v2["mcp"]["type"] == "local"
    assert v2["system"] == ["BRIEF startup", "RECALL"]
    assert v2["denied"] == "NO" and v2["content"] == "SMALL"
    assert v2["prompts"] == [{"sessionID": "s1", "text": "PROVE"}]
    assert v1["system"] == ["BRIEF startup"] and v1["output"] == "SMALL"
    assert v1["sent"][0]["body"]["parts"][0]["text"] == "PROVE"
    log = [json.loads(x) for x in (tmp_path / "keelyard.log").read_text().splitlines()]
    post = [p for e, p in log if e == "PostToolUse"][0]
    assert post["tool_input"] == {"command": "pytest"} and post["cwd"] == "/proj"


def test_lowercase_bash_output_is_filtered(cfg):
    """OpenCode and Codex name the shell tool `bash`/`shell`; filtering used to match only Claude's `Bash`."""
    long = "\n".join(f"tests/test_x.py::test_{i} PASSED" for i in range(400)) + "\n1 failed, 399 passed"
    for tool in ("bash", "shell"):
        out = handle("PostToolUse", {"session_id": "s", "tool_name": tool, "tool_input": {"command": "pytest -v"},
                                     "tool_response": {"stdout": long, "stderr": ""}}, cfg)
        assert out and len(out["hookSpecificOutput"]["updatedToolOutput"]["stdout"]) < len(long) / 2, tool
