import json

from keelyard.adapters.install import install


def test_install_claude_idempotent(project):
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps(
        {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}))
    install("claude", project)
    install("claude", project)
    s = json.loads((project / ".claude" / "settings.json").read_text())
    assert s["permissions"]["allow"] == ["Bash(ls)"]
    stop_cmds = [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]]
    assert stop_cmds.count("say done") == 1 and sum("keelyard" in c for c in stop_cmds) == 1
    assert s["hooks"]["PreToolUse"][0]["matcher"] .startswith("Read|")
    assert json.loads((project / ".mcp.json").read_text())["mcpServers"]["keelyard"]["args"] == ["mcp"]


def test_install_codex_and_opencode(project):
    install("codex", project)
    h = json.loads((project / ".codex" / "hooks.json").read_text())
    assert "Stop" in h["hooks"] and "PostToolUse" in h["hooks"]
    install("opencode", project)
    assert "session.idle" in (project / ".opencode" / "plugins" / "keelyard.js").read_text()
    assert json.loads((project / "opencode.json").read_text())["mcp"]["keelyard"]["type"] == "local"
