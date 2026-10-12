"""`keelyard install <agent>`: wire hooks + MCP into a project for one agent."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
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
    """The keelyard command as a shell-safe string (install paths may contain spaces)."""
    exe = shutil.which("keelyard") or "keelyard"
    if os.name == "nt":  # pragma: no cover
        return subprocess.list2cmdline([exe])
    return shlex.quote(exe)


def _is_ours(cmd: str) -> bool:
    return "keelyard" in cmd and " hook " in cmd


class InstallError(RuntimeError):
    pass


def _read_json(path: Path) -> dict:
    if not path.exists() or not path.read_text().strip():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise InstallError(f"{path} is not valid JSON ({e.msg}, line {e.lineno}). "
                           "Hint: fix or remove that file, then run `keelyard init` again. Nothing was changed.") from None
    if not isinstance(data, dict):
        raise InstallError(f"{path} must contain a JSON object. Hint: fix it, then run `keelyard init` again.")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".keelyard-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def _merge_hooks(path: Path, agent: str, events: dict[str, str | None]) -> None:
    data = _read_json(path)
    hooks = data.setdefault("hooks", {})
    for event, matcher in events.items():
        cmd = f"{_exe()} hook {agent} {event}"
        groups = hooks.setdefault(event, [])
        # idempotent: drop any previous keelyard entry for this event
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h.get("command", ""))]
        groups[:] = [g for g in groups if g.get("hooks")]
        entry: dict = {"hooks": [{"type": "command", "command": cmd, "timeout": 900 if event == "Stop" else 30}]}
        if matcher:
            entry["matcher"] = matcher
        groups.append(entry)
    _write_json(path, data)


def _merge_json(path: Path, key: str, name: str, value: dict) -> None:
    data = _read_json(path)
    data.setdefault(key, {})[name] = value
    _write_json(path, data)


AGENTS = ("claude", "codex", "opencode")
FILES = {
    "claude": [(".claude/settings.json", "hooks"), (".mcp.json", "mcpServers")],
    "codex": [(".codex/hooks.json", "hooks")],
    "opencode": [("opencode.json", "mcp")],
}
BINARIES = {"claude": "claude", "codex": "codex", "opencode": "opencode"}
HOMES = {"claude": "~/.claude", "codex": "~/.codex", "opencode": "~/.local/share/opencode"}


def detect() -> dict[str, str]:
    """Agents found on this machine: name -> how we know (binary path or config dir)."""
    found = {}
    for agent in AGENTS:
        exe = shutil.which(BINARIES[agent])
        home = Path(os.path.expanduser(HOMES[agent]))
        if exe:
            found[agent] = exe
        elif home.is_dir():
            found[agent] = str(home)
    return found


def installed(agent: str, root: Path) -> bool:
    if agent == "opencode":
        return (root / ".opencode" / "plugin" / "keelyard.js").exists()
    path = root / FILES[agent][0][0]
    try:
        text = path.read_text()
    except OSError:
        return False
    return "keelyard" in text and " hook " in text


START, END = "<!-- keelyard:start -->", "<!-- keelyard:end -->"
GUIDE_FILE = {"claude": "CLAUDE.md", "codex": "AGENTS.md", "opencode": "AGENTS.md"}
CLAUDE_COMMANDS = {"status": "cmd_status.md", "prove": "cmd_prove.md", "undo": "cmd_undo.md"}


def _guide(name: str) -> str:
    return resources.files("keelyard.adapters").joinpath("guides", name).read_text(encoding="utf-8")


def _set_block(path: Path, body: str | None) -> bool:
    """Insert, replace or (body=None) remove the keelyard block; the rest of the file is untouched."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    start, end = text.find(START), text.find(END)
    if start != -1 and end > start:
        before, after = text[:start].rstrip("\n"), text[end + len(END):].lstrip("\n")
    else:
        if body is None:
            return False
        before, after = text.rstrip("\n"), ""
    parts = [x for x in (before, f"{START}\n{body.strip()}\n{END}" if body is not None else "", after) if x]
    new = "\n\n".join(parts) + "\n" if parts else ""
    if body is None and not new.strip():
        path.unlink()
        return True
    path.write_text(new, encoding="utf-8")
    return True


def install_guides(agent: str, root: Path) -> list[str]:
    """Teach the agent the workflow: an instructions block, plus a skill and slash commands for Claude Code."""
    done = []
    _set_block(root / GUIDE_FILE[agent], _guide("agents_block.md"))
    done.append(f"{GUIDE_FILE[agent]} (keelyard section)")
    if agent == "claude":
        skill = root / ".claude" / "skills" / "keelyard" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(_guide("SKILL.md"), encoding="utf-8")
        cmds = root / ".claude" / "commands" / "keelyard"
        cmds.mkdir(parents=True, exist_ok=True)
        for name, src in CLAUDE_COMMANDS.items():
            (cmds / f"{name}.md").write_text(_guide(src), encoding="utf-8")
        done += [".claude/skills/keelyard/SKILL.md (skill)", "/keelyard:status, /keelyard:prove, /keelyard:undo (slash commands)"]
    return done


def uninstall_guides(agent: str, root: Path) -> list[str]:
    done = []
    others = [a for a in AGENTS if a != agent and GUIDE_FILE[a] == GUIDE_FILE[agent] and installed(a, root)]
    if not others and _set_block(root / GUIDE_FILE[agent], None):
        done.append(f"{GUIDE_FILE[agent]} (keelyard section)")
    if agent == "claude":
        skill = root / ".claude" / "skills" / "keelyard"
        cmds = root / ".claude" / "commands" / "keelyard"
        for d in (skill, cmds):
            if d.is_dir():
                shutil.rmtree(d)
                done.append(str(d.relative_to(root)))
    return done


def install(agent: str, root: Path) -> list[str]:
    if agent not in AGENTS:
        raise InstallError(f"unknown agent {agent!r}. Hint: choose one of {', '.join(AGENTS)}.")
    for rel, _ in FILES[agent]:  # validate everything first, so a bad file never leaves a half install
        _read_json(root / rel)
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
    return done + install_guides(agent, root)


def uninstall(agent: str, root: Path) -> list[str]:
    """Remove only keelyard's entries; everything else in those files is left as it was."""
    if agent not in AGENTS:
        raise InstallError(f"unknown agent {agent!r}. Hint: choose one of {', '.join(AGENTS)}.")
    done = []
    for rel, key in FILES[agent]:
        path = root / rel
        if not path.exists():
            continue
        data = _read_json(path)
        if key == "hooks":
            for event, groups in list(data.get("hooks", {}).items()):
                for g in groups:
                    g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h.get("command", ""))]
                groups[:] = [g for g in groups if g.get("hooks")]
                if not groups:
                    del data["hooks"][event]
            if not data.get("hooks"):
                data.pop("hooks", None)
        elif data.get(key, {}).pop("keelyard", None) is not None and not data[key]:
            data.pop(key)
        _write_json(path, data)
        done.append(rel)
    plugin = root / ".opencode" / "plugin" / "keelyard.js"
    if agent == "opencode" and plugin.exists():
        plugin.unlink()
        done.append(".opencode/plugin/keelyard.js")
    return done + uninstall_guides(agent, root)
