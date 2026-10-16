"""CLI rough edges found in the 0.1 audit: bare group commands, usage lines, codex MCP check."""

import json
import subprocess

from test_global import home, ky  # noqa: F401  (fixture re-export)


def _proj(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    return p


def test_bare_proof_shows_status_and_supports_json(home, tmp_path):  # noqa: F811
    p = _proj(tmp_path)
    assert ky("init", "--no-agents", cwd=p).returncode == 0
    r = ky("proof", cwd=p)
    assert r.returncode == 0 and "no work yet" in r.stdout
    r = ky("proof", "--json", cwd=p)
    assert r.returncode == 0 and json.loads(r.stdout)["state"] == "no_work"


def test_usage_errors_name_the_real_command(home, tmp_path):  # noqa: F811
    r = ky("code", cwd=_proj(tmp_path))
    assert r.returncode == 2
    assert "usage: keelyard code" in r.stderr and "<command> [options] code" not in r.stderr


def test_doctor_warns_when_codex_mcp_is_not_registered(home, tmp_path):  # noqa: F811
    p = _proj(tmp_path)
    assert ky("install", "codex", cwd=p).returncode == 0
    checks = json.loads(ky("doctor", "--json", cwd=p).stdout)["checks"]
    assert any(c["check"] == "codex mcp" and c["state"] == "warn" for c in checks)
    assert ky("install", "codex", "--global", cwd=p).returncode == 0
    checks = json.loads(ky("doctor", "--json", cwd=p).stdout)["checks"]
    assert not any(c["check"] == "codex mcp" for c in checks)


def test_every_text_file_access_is_utf8():
    """Windows defaults to cp1252: an Uzbek/Cyrillic comment or an emoji in an agent log would crash keelyard."""
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "keelyard"
    bad = []
    for f in src.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"\.(read_text|write_text)\(", text):
            depth, j = 1, m.end()
            while depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            if "encoding" not in text[m.end():j]:
                bad.append(f"{f.name}:{text.count(chr(10), 0, m.start()) + 1}")
    assert not bad, bad


def test_hook_reads_non_ascii_payload(home, tmp_path):  # noqa: F811
    p = _proj(tmp_path)
    (p / "app.py").write_text("# Qarshi shahri — привет ✓\n", encoding="utf-8")
    assert ky("init", "--agent", "claude", "--json", cwd=p).returncode == 0
    payload = json.dumps({"session_id": "s", "cwd": str(p), "hook_event_name": "UserPromptSubmit",
                          "prompt": "funksiyani tuzat — исправь ✓"}, ensure_ascii=False)
    import os
    import sys
    env = {k: v for k, v in os.environ.items() if k != "KEELYARD_ROOT"}
    r = subprocess.run([sys.executable, "-m", "keelyard.cli", "hook", "claude", "UserPromptSubmit"], cwd=p, env=env,
                       input=payload.encode("utf-8"), capture_output=True, timeout=120)  # agents send UTF-8 bytes
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    out = r.stdout.decode("utf-8")  # keelyard must answer in UTF-8 too, whatever the console code page
    json.loads(out) if out.strip() else None
