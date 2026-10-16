"""Inspired by failed-attempt memory tools: warn only when the same failure comes back after a code change."""
import sys

from keelyard import hooks
from keelyard.proof import Proof, failure_signature

FAIL = "def test_add():\n    from app import add\n    assert add(2, 2) == 4\n"


def test_signature_ignores_volatile_numbers():
    a = "FAILED tests/test_app.py::test_add - assert 5 == 4\n1 failed in 0.12s"
    b = "FAILED tests/test_app.py::test_add - assert 7 == 4\n1 failed in 0.31s"
    assert failure_signature(a) == failure_signature(b) != ""
    assert failure_signature("3 passed") == ""


def test_hint_only_when_same_failure_after_a_change(cfg, project):
    (project / "tests" / "test_app.py").write_text(FAIL)
    cmd = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'
    pf = Proof(cfg, "s1")
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    first = pf.run_tests("after", cmd)
    assert first["exit"] != 0 and pf.repeat_hint(first) is None  # first failure: nothing to say
    again = pf.run_tests("after", cmd)
    assert pf.repeat_hint(again) is None  # same code re-run: not an attempt
    (project / "app.py").write_text("def add(a, b):\n    return a * b + 1\n")
    third = pf.run_tests("after", cmd)
    hint = pf.repeat_hint(third)
    runs = pf.load().test_runs
    assert hint, [(r.get("tree"), r["exit"], failure_signature(r["tail"])) for r in runs]
    assert "same failure" in hint and len(hint) // 4 < 50
    (project / "app.py").write_text("def add(a, b):\n    return a + b\n")
    assert pf.repeat_hint(pf.run_tests("after", cmd)) is None  # passing


def test_shell_hook_surfaces_the_hint(cfg, project):
    pf = Proof(cfg, "s2")
    out1 = "FAILED tests/test_app.py::test_add - assert 0 == 4\n1 failed in 0.1s"
    ev = {"hook_event_name": "PostToolUse", "session_id": "s2", "tool_name": "Bash", "cwd": str(project),
          "tool_input": {"command": "pytest -q"}, "tool_response": {"stdout": out1, "stderr": "", "exit_code": 1}}
    hooks.handle("PostToolUse", ev, cfg)
    (project / "app.py").write_text("def add(a, b):\n    return 0\n")
    ev["tool_response"] = {"stdout": out1.replace("0 == 4", "1 == 4"), "stderr": "", "exit_code": 1}
    res = hooks.handle("PostToolUse", ev, cfg) or {}
    assert "same failure" in str(res)
    assert len(pf.load().test_runs) == 2
