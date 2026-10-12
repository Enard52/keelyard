"""`keelyard install <agent>`: wire hooks + MCP into a project for one agent."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

CLAUDE_EVENTS = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreCompact": None,
    "PreToolUse": "Read",
    "PostToolUse": "Write|Edit|MultiEdit|NotebookEdit|Bash|Read",  # Bash: snapshot + output filter
    "Stop": None,
}
CODEX_EVENTS = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PostToolUse": "Bash|apply_patch|Edit|Write",
    "Stop": None,
}


def _exe() -> str:
    return shutil.which("keelyard") or "keelyard"


def _merge_hooks(path: Path, agent: str, events: dict[str, str | None]) -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    hooks = data.setdefault("hooks", {})
    for event, matcher in events.items():
        cmd = f"{_exe()} hook {agent} {event}"
        groups = hooks.setdefault(event, [])
        # idempotent: drop any previous keelyard entry for this event
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if " hook " not in h.get("command", "") or "keelyard" not in h.get("command", "")]
        groups[:] = [g for g in groups if g.get("hooks")]
        entry: dict = {"hooks": [{"type": "command", "command": cmd, "timeout": 900 if event == "Stop" else 30}]}
        if matcher:
            entry["matcher"] = matcher
        groups.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _merge_json(path: Path, key: str, name: str, value: dict) -> None:
    data = json.loads(path.read_text()) if path.exists() else {}
    data.setdefault(key, {})[name] = value
    path.write_text(json.dumps(data, indent=2) + "\n")


def install(agent: str, root: Path) -> list[str]:
    done = []
    if agent == "claude":
        _merge_hooks(root / ".claude" / "settings.json", "claude", CLAUDE_EVENTS)
        _merge_json(root / ".mcp.json", "mcpServers", "keelyard", {"command": _exe(), "args": ["mcp"]})
        done += [".claude/settings.json (hooks)", ".mcp.json (MCP server)"]
    elif agent == "codex":
        _merge_hooks(root / ".codex" / "hooks.json", "codex", CODEX_EVENTS)
        done.append(".codex/hooks.json (hooks; approve them in Codex with /hooks)")
        done.append(f'add to ~/.codex/config.toml:\n[mcp_servers.keelyard]\ncommand = "{_exe()}"\nargs = ["mcp"]')
    elif agent == "opencode":
        dest = root / ".opencode" / "plugin" / "keelyard.js"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(resources.files("keelyard.adapters").joinpath("opencode_plugin.js").read_text())
        _merge_json(root / "opencode.json", "mcp", "keelyard", {"type": "local", "command": [_exe(), "mcp"], "enabled": True})
        done += [".opencode/plugin/keelyard.js (events)", "opencode.json (MCP server)"]
    else:
        raise ValueError("agent must be claude, codex or opencode")
    return done
