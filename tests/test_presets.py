"""keelyard init --preset lean|balanced|max-quality: lowest-token agent settings, fully reversible."""

import json

import pytest

from keelyard.adapters.install import PRESETS, InstallError, install, uninstall


def test_presets_known():
    assert set(PRESETS) == {"lean", "balanced", "max-quality"}


def test_lean_opencode_trims_agent_and_uninstall_restores(project):
    (project / "opencode.json").write_text(json.dumps({"theme": "dark"}))
    install("opencode", project, preset="lean")
    oc = json.loads((project / "opencode.json").read_text())
    build = oc["agents"]["build"]
    assert len(build["system"]) < 600
    denied = {r["action"] for r in build["permissions"] if r["effect"] == "deny"}
    assert {"webfetch", "websearch", "subagent", "todowrite"} <= denied
    assert {"glob", "grep"} <= denied
    assert "shell" not in denied and "edit" not in denied and "read" not in denied
    assert "keelyard" not in oc.get("mcp", {})
    uninstall("opencode", project)
    assert json.loads((project / "opencode.json").read_text()) == {"theme": "dark"}


def test_lean_keeps_user_agent_settings(project):
    (project / "opencode.json").write_text(json.dumps({"agents": {"build": {"system": "mine"}}}))
    install("opencode", project, preset="lean")
    assert json.loads((project / "opencode.json").read_text())["agents"]["build"] == {"system": "mine"}


def test_lean_claude_env_and_restore(project):
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps({"env": {"BASH_MAX_OUTPUT_LENGTH": "99"}}))
    install("claude", project, preset="lean")
    env = json.loads((project / ".claude" / "settings.json").read_text())["env"]
    assert env["BASH_MAX_OUTPUT_LENGTH"] == "99"  # the user's value wins
    assert env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] == "1"
    uninstall("claude", project)
    data = json.loads((project / ".claude" / "settings.json").read_text())
    assert data == {"env": {"BASH_MAX_OUTPUT_LENGTH": "99"}}


def test_max_quality_opencode_adds_mcp(project):
    install("opencode", project, preset="max-quality")
    assert json.loads((project / "opencode.json").read_text())["mcp"]["keelyard"]["type"] == "local"
    assert "const MCP = true;" in (project / ".opencode" / "plugins" / "keelyard.js").read_text()


def test_unknown_preset(project):
    with pytest.raises(InstallError):
        install("opencode", project, preset="turbo")
