"""Lean mode: proof from ordinary shell test runs, no MCP for OpenCode by default, a small brief."""

import json

from keelyard import hooks
from keelyard.adapters.install import install
from keelyard.brain import brief
from keelyard.proof import Proof, parse_test_exit

PY_PASS = "tests/test_app.py::test_add PASSED\n" * 40 + "============ 66 passed in 0.20s ============\n"
PY_FAIL = "tests/test_app.py::test_add FAILED\n" + "x PASSED\n" * 40 + "===== 1 failed, 65 passed in 0.3s =====\n"


def ev(event, **kw):
    return {"session_id": "s1", "cwd": ".", **kw}


def test_exit_parsing():
    assert parse_test_exit(PY_PASS) == 0
    assert parse_test_exit(PY_FAIL) == 1
    assert parse_test_exit("ok  \tpkg\t0.1s\n") == 0
    assert parse_test_exit("Tests:       2 failed, 3 passed, 5 total") == 1
    assert parse_test_exit("hello") is None


def test_shell_test_run_is_proof(cfg, project):
    hooks.handle("UserPromptSubmit", ev("UserPromptSubmit", prompt="make add() take 3 args"), cfg)
    (project / "app.py").write_text("def add(a, b, c=0):\n    return a + b + c\n")
    hooks.handle("PostToolUse", ev("PostToolUse", tool_name="edit", tool_input={"filePath": "app.py"}), cfg)
    assert hooks.handle("Stop", ev("Stop"), cfg)["decision"] == "block"
    hooks.handle("PostToolUse", ev("PostToolUse", tool_name="bash", tool_input={"command": "python -m pytest -v"},
                                   tool_response={"stdout": PY_FAIL, "stderr": ""}), cfg)
    out = hooks.handle("Stop", ev("Stop"), cfg)
    assert out["decision"] == "block" and "failed" in out["reason"]
    res = hooks.handle("PostToolUse", ev("PostToolUse", tool_name="bash", tool_input={"command": "python -m pytest -v"},
                                         tool_response={"stdout": PY_PASS, "stderr": ""}), cfg)
    assert len(res["hookSpecificOutput"]["updatedToolOutput"]["stdout"]) < len(PY_PASS) / 3  # filtered too
    assert hooks.handle("Stop", ev("Stop"), cfg) is None
    b = Proof(cfg, "s1").load()
    assert b.requirements and b.requirements[0]["done"] and "66 passed" in b.requirements[0]["evidence"]


def test_non_test_shell_is_not_proof(cfg, project):
    (project / "app.py").write_text("x = 1\n")
    hooks.handle("PostToolUse", ev("PostToolUse", tool_name="edit", tool_input={"filePath": "app.py"}), cfg)
    hooks.handle("PostToolUse", ev("PostToolUse", tool_name="bash", tool_input={"command": "cat log.txt"},
                                   tool_response={"stdout": PY_PASS, "stderr": ""}), cfg)
    assert hooks.handle("Stop", ev("Stop"), cfg)["decision"] == "block"


def test_opencode_install_has_no_mcp_by_default(project):
    install("opencode", project)
    oc = project / "opencode.json"
    assert not oc.exists() or "keelyard" not in json.loads(oc.read_text()).get("mcp", {})
    js = (project / ".opencode" / "plugins" / "keelyard.js").read_text()
    assert "const MCP = false;" in js
    agents = (project / "AGENTS.md").read_text()
    assert "proof_requirements" not in agents and len(agents) < 400


def test_opencode_mcp_opt_in(project, monkeypatch):
    monkeypatch.setenv("KEELYARD_OPENCODE_MCP", "1")
    install("opencode", project)
    assert json.loads((project / "opencode.json").read_text())["mcp"]["keelyard"]["type"] == "local"
    assert "const MCP = true;" in (project / ".opencode" / "plugins" / "keelyard.js").read_text()


def test_lean_brief_is_small_and_skips_agent_files(cfg, project):
    install("opencode", project)
    b = brief(cfg, "s1", lean=True)
    assert ".opencode" not in b and "AGENTS.md" not in b
    assert len(b) < 600
