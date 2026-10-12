import asyncio
import json

import httpx

from keelyard import config
from keelyard.swarm import Swarm, Task, format_results, verify_citations, verify_patch


def fake_openai(answer_for):
    calls = {"n": 0, "max_inflight": 0, "inflight": 0}

    async def handler(request: httpx.Request):
        calls["n"] += 1
        calls["inflight"] += 1
        calls["max_inflight"] = max(calls["max_inflight"], calls["inflight"])
        await asyncio.sleep(0.01)
        calls["inflight"] -= 1
        body = json.loads(request.content)
        text = answer_for(body["messages"][-1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

    return httpx.MockTransport(handler), calls


def test_swarm_200_workers_with_verification(cfg, project):
    (cfg.state / "config.toml").write_text(
        '[swarm]\nconcurrency = 50\n[models.cheap]\nprovider="openai"\nbase_url="http://fake/v1"\nmodel="m"\n')
    cfg = config.load(project)

    def answer(prompt):
        if "lie" in prompt:
            return "It multiplies, see app.py:40 and `return a * b`"
        return "add returns the sum, see app.py:2 `return a + b`"

    transport, calls = fake_openai(answer)
    tasks = [Task("ask", "what does add do" if i % 10 else "lie please", ["app.py"]) for i in range(200)]
    tasks.append(Task("grep", "def add"))
    res = asyncio.run(Swarm(cfg, transport=transport).run(tasks))
    assert calls["n"] == 200 and calls["max_inflight"] <= 50
    assert sum(r.verified for r in res) == 181  # 180 honest + 1 local grep; 20 liars caught
    liar = next(r for r in res if not r.verified)
    assert any("app.py:40" in n for n in liar.notes)
    assert "181/201 verified" in format_results(res)


def test_anthropic_provider_and_retry(cfg, project):
    (cfg.state / "config.toml").write_text(
        '[models.cheap]\nprovider="anthropic"\nbase_url="http://fake"\nmodel="m"\n')
    cfg = config.load(project)
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, json={})
        assert request.url.path == "/v1/messages"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "app.py:1 `def add(a, b):`"}],
                                         "usage": {"input_tokens": 5, "output_tokens": 3}})

    res = asyncio.run(Swarm(cfg, transport=httpx.MockTransport(handler)).run([Task("ask", "q", ["app.py"])]))
    assert res[0].verified and state["n"] == 2


def test_verify_patch(project):
    good = ("```diff\ndiff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n-    return a + b\n+    return b + a\n```")
    ok, _, notes = verify_patch(project, good)
    assert ok, notes
    assert (project / "app.py").read_text().endswith("a + b\n")  # never applied
    bad = good.replace("return a + b", "return nonsense")
    assert not verify_patch(project, bad)[0]


def test_verify_citations_rejects_missing_file(project):
    ok, notes = verify_citations(project, "see ghost.py:3", ["app.py"])
    assert not ok and "missing file" in notes[0]
