"""Stronger helpers: focused context, schemas, retry with feedback, best-of-N, test-checked patches, escalation."""

import asyncio
import json
import sys
from pathlib import Path

import httpx

from keelyard import config
from keelyard.swarm import Swarm, Task, context_pack, parse_ask, plan, subagent_tasks

PY = Path(sys.executable).as_posix()
GOOD_PATCH = "```diff\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n```"
BAD_PATCH = "```diff\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b + 1\n```"


def setup(project, extra=""):
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text(
        '[models.cheap]\nprovider="openai"\nbase_url="http://fake/v1"\nmodel="cheap"\n'
        '[models.strong]\nprovider="openai"\nbase_url="http://fake/v1"\nmodel="big"\n' + extra)
    return config.load(project)


def transport(fn):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        text = fn(body["model"], body["messages"][-1]["content"], body["temperature"])
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    return httpx.MockTransport(handler), seen


def test_context_pack_keeps_only_named_definitions_with_real_line_numbers(project):
    (project / "big.py").write_text("import os\n\n" + "".join(f"def f{i}():\n    return {i}\n\n" for i in range(50)))
    pack = context_pack(project, ["big.py"], ["f30"])
    assert "1: import os" in pack and "93: def f30():" in pack and "94:     return 30" in pack
    assert "def f29" not in pack and "def f31" not in pack and "only f30" in pack
    assert "def f31" in context_pack(project, ["big.py"])  # no symbols: whole file


def test_parse_ask_accepts_schema_or_text():
    out = parse_ask('ok {"answer": "it adds", "citations": ["app.py:2"], "quotes": ["return a + b"]}')
    assert "it adds" in out and "app.py:2" in out and "`return a + b`" in out
    assert parse_ask("plain app.py:2") == "plain app.py:2"


def test_retry_feeds_verifier_notes_back(project):
    cfg = setup(project, "[swarm]\nbest_of = 1\nretries = 1\nescalate_model = \"\"\n")
    t, seen = transport(lambda m, p, temp: '{"answer": "adds", "citations": ["app.py:2"]}' if "rejected" in p
                        else '{"answer": "adds", "citations": ["app.py:99"]}')
    r = asyncio.run(Swarm(cfg, transport=t).run([Task("ask", "what does add do", ["app.py"])]))[0]
    assert r.verified and r.attempts == 2 and "app.py:99" in seen[1]["messages"][-1]["content"]


def test_best_of_n_picks_a_verified_sample(project):
    cfg = setup(project, "[swarm]\nbest_of = 3\nretries = 0\nescalate_model = \"\"\n")
    t, seen = transport(lambda m, p, temp: '{"answer": "adds", "citations": ["app.py:2"]}' if temp > 0.5
                        else '{"answer": "adds", "citations": ["nope.py:1"]}')
    r = asyncio.run(Swarm(cfg, transport=t).run([Task("ask", "what does add do", ["app.py"])]))[0]
    assert r.verified and r.attempts == 1 and r.candidates == 3 and len(seen) == 3


def test_draft_patches_are_tested_in_a_copy_and_the_passing_one_wins(project):
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    cfg = setup(project, f"[swarm]\nbest_of = 2\nretries = 0\nescalate_model = \"\"\n[proof]\ntest_cmd = \"{PY} -m pytest -q\"\n")
    t, _ = transport(lambda m, p, temp: GOOD_PATCH if temp > 0.5 else BAD_PATCH)
    r = asyncio.run(Swarm(cfg, transport=t).run([Task("draft_edit", "fix add", ["app.py"])]))[0]
    assert r.verified and r.tests_passed is True and "a + b" in r.output
    assert (project / "app.py").read_text().endswith("a - b\n")  # never applied to the project


def test_failing_patch_is_rejected_and_escalates_to_strong(project):
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    cfg = setup(project, f"[swarm]\nbest_of = 1\nretries = 1\n[proof]\ntest_cmd = \"{PY} -m pytest -q\"\n")
    t, seen = transport(lambda m, p, temp: GOOD_PATCH if m == "big" else BAD_PATCH)
    r = asyncio.run(Swarm(cfg, transport=t).run([Task("draft_edit", "fix add", ["app.py"])]))[0]
    assert r.verified and r.escalated and r.attempts == 3
    assert "assert 5 == 4" in seen[1]["messages"][-1]["content"]  # retry saw the failing test output
    assert [b["model"] for b in seen] == ["cheap", "cheap", "big"]


def test_no_escalation_when_strong_is_unset(project):
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text('[models.cheap]\nprovider="openai"\nbase_url="http://f/v1"\nmodel="c"\n')
    assert Swarm(config.load(project)).escalate is None  # default strong model is "set-me"


def test_planner_splits_by_defining_file_and_emits_subagent_prompts(project):
    (project / "cart.py").write_text("def total(prices):\n    return sum(prices)\n\n\ndef other():\n    pass\n")
    cfg = config.load(project)
    tasks = plan(cfg, "Fix total so that it applies the add discount")
    files = {t.files[0]: t for t in tasks}
    assert set(files) == {"cart.py", "app.py"} and files["cart.py"].symbols == ["total"]
    assert all(t.kind == "draft_edit" for t in tasks)
    sub = subagent_tasks(cfg, tasks)
    cart = next(s for s in sub if s["files"] == ["cart.py"])
    assert "1: def total(prices):" in cart["subagent_prompt"] and "def other" not in cart["subagent_prompt"]
    assert "unified diff" in cart["subagent_prompt"]
    assert plan(cfg, "where is total computed?")[0].kind == "ask"


def test_single_definition_drafts_are_spliced_into_a_diff(project):
    from keelyard.swarm import splice_definition

    (project / "m.py").write_text("import os\n\n\ndef keep():\n    return 1\n\n\ndef fix(x):\n    return x - 1\n\n\ndef tail():\n    pass\n")
    diff = splice_definition(project, "m.py", "fix", "Sure:\n```python\ndef fix(x):\n    return x + 1\n```")
    assert "-    return x - 1" in diff and "+    return x + 1" in diff
    changed = [ln for ln in diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    assert changed == ["-    return x - 1", "+    return x + 1"]
    assert splice_definition(project, "m.py", "fix", "```python\nprint('no def')\n```") is None


def test_pipeline_uses_replace_format_for_one_symbol(project):
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    cfg = setup(project, f"[swarm]\nbest_of = 1\nretries = 0\nescalate_model = \"\"\n[proof]\ntest_cmd = \"{PY} -m pytest -q\"\n")
    t, seen = transport(lambda m, p, temp: "```python\ndef add(a, b):\n    return a + b\n```")
    r = asyncio.run(Swarm(cfg, transport=t).run([Task("draft_edit", "fix add", ["app.py"], symbols=["add"])]))[0]
    assert r.verified and r.tests_passed and "+    return a + b" in r.output
    assert "complete new version" in seen[0]["messages"][0]["content"]


def test_patch_tests_compare_against_already_failing_suite(project):
    """A suite with unrelated failures must not reject a correct fix (found by the quality benchmark)."""
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    (project / "tests" / "test_other.py").write_text("def test_unrelated():\n    assert 1 == 2\n")
    cfg = setup(project, f"[swarm]\nbest_of = 1\nretries = 0\nescalate_model = \"\"\n[proof]\ntest_cmd = \"{PY} -m pytest -q\"\n")
    t, _ = transport(lambda m, p, temp: GOOD_PATCH)
    r = asyncio.run(Swarm(cfg, transport=t).run([Task("draft_edit", "fix add", ["app.py"])]))[0]
    assert r.verified and any("breaks none" in n for n in r.notes)
    t, _ = transport(lambda m, p, temp: BAD_PATCH)
    r = asyncio.run(Swarm(cfg, transport=t).run([Task("draft_edit", "fix add", ["app.py"])]))[0]
    assert not r.verified and any("fixes no failing test" in n for n in r.notes)


def test_failing_tests_parser():
    from keelyard.swarm import failing_tests

    out = "FAILED t.py::test_a - x\nERROR t.py::test_b\n--- FAIL: TestGo (0.0s)\ntest mod::rs ... FAILED\n  ✕ jest thing (3 ms)\n"
    assert failing_tests(out) == {"t.py::test_a", "t.py::test_b", "TestGo", "mod::rs", "jest thing (3 ms)"}
