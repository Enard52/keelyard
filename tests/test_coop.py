"""Cooperative swarm: blackboard, critic, voting, cheapest-capable routing, strict token budgets, 200+ workers."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

from keelyard import config
from keelyard.coop import Blackboard, BudgetExceeded, Coop, Ledger, Router, solve
from keelyard.swarm import Task

PY = Path(sys.executable).as_posix()
BAD = "```diff\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b + 1\n```"
GOOD = "```diff\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n```"
GOOD2 = "```diff\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return b + a\n```"


def setup(project, extra=""):
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text(
        '[models.cheap]\nprovider="openai"\nbase_url="http://fake/v1"\nmodel="cheap"\nmax_tokens=100\n'
        '[models.strong]\nprovider="openai"\nbase_url="http://fake/v1"\nmodel="big"\nmax_tokens=100\n' + extra)
    return config.load(project)


def transport(fn, delay=0.0):
    seen, state = [], {"now": 0, "peak": 0}

    async def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        if delay:
            await asyncio.sleep(delay)
        state["now"] -= 1
        text = fn(body["model"], body["messages"][0]["content"], body["messages"][-1]["content"], body["temperature"])
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    return httpx.MockTransport(handler), seen, state


CITED = '{"answer": "adds", "citations": ["app.py:2"]}'
UNCITED = '{"answer": "adds", "citations": ["app.py:99"]}'


def test_ledger_reserves_before_spending_and_never_overshoots():
    led = Ledger(total=100, per_task=60)
    led.reserve(1, 50)
    with pytest.raises(BudgetExceeded):
        led.reserve(1, 20)  # per-task cap counts the open reservation
    led.reserve(2, 45)
    with pytest.raises(BudgetExceeded):
        led.reserve(3, 10)  # total cap
    led.settle(1, 50, "cheap", 20, 5)  # actual was cheaper: the rest is released
    led.reserve(3, 10)
    assert led.used == 25 and led.by_model["cheap"] == 25 and led.refused == 2


def test_blackboard_shares_only_verified_facts_and_known_dead_ends():
    bb = Blackboard()
    bb.post(1, ["app.py"], "add is on app.py:2", verified=True)
    bb.post(2, ["app.py"], "tried a + b + 1: tests fail", verified=False)
    bb.post(3, ["other.py"], "unrelated", verified=True)
    text = bb.for_files(["app.py"], exclude=99)
    assert "add is on app.py:2" in text and "tests fail" in text and "unrelated" not in text
    assert "app.py:2" not in bb.for_files(["app.py"], exclude=1)  # a worker never sees its own notes
    assert bb.for_files(["nothing.py"]) == ""


def test_router_learns_the_cheapest_capable_tier():
    r = Router(["cheap", "strong"])
    assert r.start("ask") == 0
    for _ in range(3):
        r.record("ask", 0, False)
        r.record("ask", 1, True)
    assert r.start("ask") == 1  # cheap keeps failing asks: start at strong
    assert r.start("draft_edit") == 0


def test_cheap_tier_first_and_strong_only_when_needed(project):
    cfg = setup(project, "[swarm]\nbest_of = 1\nretries = 0\nladder = [\"cheap\", \"strong\"]\ncritic = false\n")
    t, seen, _ = transport(lambda m, s, u, temp: CITED if m == "big" or "add2" not in u else UNCITED)
    res = asyncio.run(Coop(cfg, transport=t).run([Task("ask", "what does add do", ["app.py"]),
                                                  Task("ask", "add2 question", ["app.py"])]))
    assert res[0].verified and res[0].model == "cheap"
    assert res[1].verified and res[1].model == "big" and res[1].escalated
    assert [b["model"] for b in seen].count("big") == 1


def test_blackboard_reaches_later_workers(project):
    cfg = setup(project, "[swarm]\nbest_of = 1\nretries = 0\nworkers = 1\ncritic = false\n")
    t, seen, _ = transport(lambda m, s, u, temp: CITED)
    asyncio.run(Coop(cfg, transport=t).run([Task("ask", "first", ["app.py"]), Task("ask", "second", ["app.py"])]))
    assert "Verified by other workers" in seen[1]["messages"][-1]["content"]
    assert "app.py:2" in seen[1]["messages"][-1]["content"]


def test_critic_rejects_a_verified_but_wrong_candidate(project):
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    cfg = setup(project, "[swarm]\nbest_of = 2\nretries = 0\ntest_patches = false\ncritic = true\nladder = [\"cheap\"]\n")

    def fn(m, system, user, temp):
        if "reviewer" in system:
            return "REJECT: adds one" if "a + b + 1" in user else "APPROVE"
        return BAD if temp < 0.5 else GOOD
    t, seen, _ = transport(fn)
    r = asyncio.run(Coop(cfg, transport=t).run([Task("draft_edit", "fix add", ["app.py"])]))[0]
    assert r.verified and "+    return a + b\n" in r.output and r.critic == "APPROVE"
    assert r.tokens_in == 40 and r.tokens_out == 20  # 2 workers + 2 critic calls, all counted


def test_vote_prefers_consensus(project):
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    cfg = setup(project, "[swarm]\nbest_of = 3\nretries = 0\ntest_patches = false\ncritic = false\nladder = [\"cheap\"]\n")
    calls = iter([GOOD2, GOOD, GOOD])
    t, _, _ = transport(lambda m, s, u, temp: next(calls))
    r = asyncio.run(Coop(cfg, transport=t).run([Task("draft_edit", "fix add", ["app.py"])]))[0]
    assert "+    return a + b\n" in r.output and r.consensus == 2


def test_two_hundred_fifty_concurrent_workers_with_exact_accounting(project):
    cfg = setup(project, "[swarm]\nbest_of = 1\nretries = 0\nworkers = 256\ncritic = false\nladder = [\"cheap\"]\n")
    t, seen, state = transport(lambda m, s, u, temp: CITED, delay=0.2)
    coop = Coop(cfg, transport=t)
    res = asyncio.run(coop.run([Task("ask", f"q{i}", ["app.py"]) for i in range(250)]))
    assert len(res) == 250 and all(r.verified for r in res)
    assert state["peak"] >= 200
    assert coop.ledger.used == 250 * 15 == sum(r.tokens_in + r.tokens_out for r in res)


def test_total_budget_is_a_hard_cap(project):
    cfg = setup(project, "[swarm]\nbest_of = 1\nretries = 0\nworkers = 64\ncritic = false\nladder = [\"cheap\"]\n"
                         "budget_tokens = 1500\n")
    t, seen, _ = transport(lambda m, s, u, temp: CITED, delay=0.01)
    coop = Coop(cfg, transport=t)
    res = asyncio.run(coop.run([Task("ask", f"q{i}", ["app.py"]) for i in range(100)]))
    done = [r for r in res if r.verified]
    refused = [r for r in res if any("budget" in n for n in r.notes)]
    assert done and refused and len(done) + len(refused) == 100
    assert coop.ledger.used + coop.ledger.reserved <= 1500 and coop.ledger.reserved == 0
    assert len(seen) == len(done)


def test_solve_runs_planner_workers_verifier(project):
    (project / "app.py").write_text("def add(a, b):\n    return a - b\n")
    cfg = setup(project, f"[swarm]\nbest_of = 1\nretries = 0\ncritic = true\nladder = [\"cheap\"]\n"
                         f"[proof]\ntest_cmd = \"{PY} -m pytest -q\"\n")

    def fn(m, system, user, temp):
        return "APPROVE" if "reviewer" in system else "```python\ndef add(a, b):\n    return a + b\n```"
    t, _, _ = transport(fn)
    out = asyncio.run(solve(cfg, "Fix add so it adds", transport=t))
    assert out["tasks"] == 1 and out["verified"] == 1 and out["results"][0].tests_passed
    assert out["tokens"] == 30 and out["tokens_per_verified"] == 30
