"""swarm round-2 audit: the documented plan -> run pipe, clear model errors, exit codes, --model in coop mode."""

import asyncio
import http.server
import json
import subprocess
import sys
import threading

import httpx
import pytest
from test_swarm2 import setup, transport

from keelyard.coop import Coop
from keelyard.swarm import Task, explain, preflight


def ky(*args, cwd, env=None):
    import os
    e = {k: v for k, v in os.environ.items() if k != "KEELYARD_ROOT"} | (env or {})
    return subprocess.run([sys.executable, "-m", "keelyard.cli", *args], cwd=cwd, capture_output=True, text=True,
                          env=e, timeout=120)


@pytest.fixture
def notfound_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            body = b'{"error": "model not found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_plan_json_pipes_into_run_and_explains_a_404(project, notfound_server):
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text(
        f'[models.cheap]\nprovider="openai"\nbase_url="{notfound_server}"\nmodel="m"\napi_key_env=""\n', encoding="utf-8")
    plan = ky("swarm", "plan", "fix add", "--json", cwd=project)
    assert plan.returncode == 0
    (project / "tasks.json").write_text(plan.stdout, encoding="utf-8")  # exactly what `> tasks.json` writes
    r = ky("swarm", "run", "tasks.json", "--json", cwd=project, env={"KEELYARD_RETRIES": "1"})
    assert r.returncode == 3, r.stderr  # nothing worked: not a success
    d = json.loads(r.stdout)
    assert d["total"] == 1 and "not found (HTTP 404)" in d["results"][0]["notes"][0]


def test_run_refuses_an_error_file_with_a_hint(project):
    (project / "bad.json").write_text('{"ok": false, "error": "found no file for that goal.", "hint": "pass --files"}',
                                      encoding="utf-8")
    r = ky("swarm", "run", "bad.json", cwd=project)
    assert r.returncode == 1 and "error from `swarm plan`" in r.stderr and "pass --files" in r.stderr


def test_missing_key_is_caught_before_any_call(project):
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text(
        '[models.cheap]\nprovider="openai"\nbase_url="https://openrouter.ai/api/v1"\nmodel="x:free"\n'
        'api_key_env="KEELYARD_TEST_NO_SUCH_KEY"\n', encoding="utf-8")
    (project / "t.json").write_text('[{"kind": "ask", "prompt": "q", "files": ["app.py"]}]', encoding="utf-8")
    r = ky("swarm", "run", "t.json", cwd=project)
    assert r.returncode == 1 and "$KEELYARD_TEST_NO_SUCH_KEY is not set" in r.stderr


def test_preflight_and_explain_never_leak_keys(monkeypatch):
    monkeypatch.setenv("K", "sk-or-v1-supersecret")
    assert preflight({"model": "x:free", "api_key_env": "K"}) is None
    req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": "Bearer sk-or-v1-supersecret"})
    msg = explain(httpx.HTTPStatusError("x", request=req, response=httpx.Response(401, request=req)))
    assert "rejected the API key" in msg and "supersecret" not in msg


def test_coop_model_flag_pins_the_model(project):
    cfg = setup(project)
    t, seen = transport(lambda model, prompt, temp: '{"answer": "add", "citations": ["app.py:1"], "quotes": ["def add"]}')
    sw = Coop(cfg, model_key="strong", transport=t, best_of=1, retries=0)
    asyncio.run(sw.run([Task("ask", "where is add", ["app.py"])]))
    assert seen and {b["model"] for b in seen} == {"big"}
