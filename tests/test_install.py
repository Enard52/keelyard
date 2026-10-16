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


def test_install_codex_and_opencode(project, monkeypatch):
    monkeypatch.setenv("KEELYARD_OPENCODE_MCP", "1")
    install("codex", project)
    h = json.loads((project / ".codex" / "hooks.json").read_text())
    assert "Stop" in h["hooks"] and "PostToolUse" in h["hooks"]
    install("opencode", project)
    assert "session.idle" in (project / ".opencode" / "plugins" / "keelyard.js").read_text()
    assert json.loads((project / "opencode.json").read_text())["mcp"]["keelyard"]["type"] == "local"


def _tree(root):
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*")) if ".git" not in p.parts and ".keelyard" not in p.parts}


def test_uninstall_restores_project_byte_for_byte(project):
    from keelyard.adapters.install import uninstall

    (project / "CLAUDE.md").write_text("# mine\n")
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text('{"permissions":{"allow":["Bash(ls)"]},"env":{"X":"1"}}\n')
    (project / "opencode.json").write_text('{"model":"m"}\n')
    before = _tree(project)
    for a in ("claude", "codex", "opencode"):
        install(a, project, preset="lean")
    assert _tree(project) != before
    for a in ("claude", "codex", "opencode"):
        uninstall(a, project)
    assert _tree(project) == before  # no leftover {} files, empty folders, or reformatted JSON


def test_uninstall_keeps_user_edits_made_after_install(project):
    from keelyard.adapters.install import uninstall

    install("claude", project)
    s = json.loads((project / ".claude" / "settings.json").read_text())
    s["env"] = {"MINE": "1"}
    (project / ".claude" / "settings.json").write_text(json.dumps(s))
    uninstall("claude", project)
    assert json.loads((project / ".claude" / "settings.json").read_text()).get("env", {}).get("MINE") == "1"
