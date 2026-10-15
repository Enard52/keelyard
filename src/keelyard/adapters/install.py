"""`keelyard install <agent>`: wire hooks + MCP into a project for one agent."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from importlib import resources
from pathlib import Path

CLAUDE_EVENTS = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreCompact": None,
    "PreToolUse": "Read|Bash|Edit|Write|MultiEdit",  # dedupe reads, snapshot before destructive commands, nudges
    "PostToolUse": "Write|Edit|MultiEdit|NotebookEdit|Bash|Read",  # Bash: snapshot + output filter
    "Stop": None,
}
CODEX_EVENTS = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreToolUse": "Bash|shell|apply_patch|Edit|Write",
    "PostToolUse": "Bash|apply_patch|Edit|Write",
    "Stop": None,
}


def _exe_path() -> str:
    """The keelyard executable, unquoted: for configs that exec a program directly (MCP)."""
    return shutil.which("keelyard") or "keelyard"


def _exe() -> str:
    """The keelyard command as a shell-safe string, for hook commands run by a shell (paths may contain spaces)."""
    exe = _exe_path()
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


WORKFLOWS = {"plan": "plan, implement, verify (any multi-step change)",
             "debug": "reproduce, hypothesise, test, fix the cause",
             "review": "check a diff: correct, safe, tested, small, clear"}


def workflow_text(name: str) -> str:
    if name not in WORKFLOWS:
        raise ValueError(f"unknown workflow {name!r}. Hint: one of {', '.join(WORKFLOWS)}.")
    return _guide(f"workflows/{name}.md")


def _command(name: str) -> str:
    """A slash command file: only the one-line description is in context until the command is used."""
    return f"---\ndescription: keelyard workflow: {WORKFLOWS[name]}\n---\n{workflow_text(name)}"


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
        for name in WORKFLOWS:
            (cmds / f"{name}.md").write_text(_command(name), encoding="utf-8")
        done += [".claude/skills/keelyard/SKILL.md (skill)",
                 "/keelyard:status, :prove, :undo, :plan, :debug, :review (slash commands)"]
    if agent == "opencode":
        cmds = root / ".opencode" / "command"
        cmds.mkdir(parents=True, exist_ok=True)
        for name in WORKFLOWS:
            (cmds / f"keelyard-{name}.md").write_text(_command(name), encoding="utf-8")
        done.append("/keelyard-plan, /keelyard-debug, /keelyard-review (commands)")
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
    if agent == "opencode":
        for name in WORKFLOWS:
            f = root / ".opencode" / "command" / f"keelyard-{name}.md"
            if f.exists():
                f.unlink()
                done.append(str(f.relative_to(root)))
    return done


def install(agent: str, root: Path) -> list[str]:
    if agent not in AGENTS:
        raise InstallError(f"unknown agent {agent!r}. Hint: choose one of {', '.join(AGENTS)}.")
    for rel, _ in FILES[agent]:  # validate everything first, so a bad file never leaves a half install
        _read_json(root / rel)
    done = []
    if agent == "claude":
        _merge_hooks(root / ".claude" / "settings.json", "claude", CLAUDE_EVENTS)
        _merge_json(root / ".mcp.json", "mcpServers", "keelyard", {"command": _exe_path(), "args": ["mcp"]})
        done += [".claude/settings.json (hooks)", ".mcp.json (MCP server)"]
    elif agent == "codex":
        _merge_hooks(root / ".codex" / "hooks.json", "codex", CODEX_EVENTS)
        done.append(".codex/hooks.json (hooks; approve them in Codex with /hooks)")
        done.append(f'add to ~/.codex/config.toml:\n[mcp_servers.keelyard]\ncommand = {json.dumps(_exe_path())}\nargs = ["mcp"]')
    elif agent == "opencode":
        dest = root / ".opencode" / "plugin" / "keelyard.js"
        dest.parent.mkdir(parents=True, exist_ok=True)
        js = resources.files("keelyard.adapters").joinpath("opencode_plugin.js").read_text()
        dest.write_text(js.replace('const KEELYARD = "keelyard";', f"const KEELYARD = {json.dumps(_exe_path())};", 1))
        _merge_json(root / "opencode.json", "mcp", "keelyard", {"type": "local", "command": [_exe_path(), "mcp"], "enabled": True})
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


# --------------------------------------------------------------------------- global (user-level) install
TOML_START, TOML_END = "# keelyard:start", "# keelyard:end"


def global_paths(home: Path | None = None) -> dict[str, Path]:
    h = home or Path.home()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    oc = Path(xdg) / "opencode" if xdg else h / ".config" / "opencode"
    return {"claude_settings": h / ".claude" / "settings.json", "claude_json": h / ".claude.json",
            "claude_md": h / ".claude" / "CLAUDE.md", "claude_dir": h / ".claude",
            "codex_toml": h / ".codex" / "config.toml", "codex_hooks": h / ".codex" / "hooks.json",
            "codex_md": h / ".codex" / "AGENTS.md",
            "opencode_json": oc / "opencode.json", "opencode_plugin": oc / "plugin" / "keelyard.js",
            "opencode_md": oc / "AGENTS.md", "opencode_dir": oc}


def _backup(path: Path) -> None:
    """Keep the user's original once: <file>.keelyard-backup (never overwritten)."""
    bak = path.with_name(path.name + ".keelyard-backup")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)


def _toml_block(path: Path, body: str | None) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    text = re.sub(rf"\n?{re.escape(TOML_START)}\n.*?{re.escape(TOML_END)}\n?", "\n", text, flags=re.S).rstrip("\n")
    if body:
        text = (text + "\n\n" if text else "") + f"{TOML_START}\n{body.strip()}\n{TOML_END}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n" if text else "", encoding="utf-8")


def _strip_hooks(path: Path) -> bool:
    if not path.exists():
        return False
    data = _read_json(path)
    for event, groups in list(data.get("hooks", {}).items()):
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h.get("command", ""))]
        groups[:] = [g for g in groups if g.get("hooks")]
        if not groups:
            del data["hooks"][event]
    if not data.get("hooks"):
        data.pop("hooks", None)
    _write_json(path, data)
    return True


def _drop_key(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    data = _read_json(path)
    if data.get(key, {}).pop("keelyard", None) is None:
        return False
    if not data[key]:
        data.pop(key)
    _write_json(path, data)
    return True


def install_global(agent: str, home: Path | None = None) -> list[str]:
    """Wire one agent for every project of this user. Existing files are backed up once and merged, never replaced."""
    if agent not in AGENTS:
        raise InstallError(f"unknown agent {agent!r}. Hint: choose one of {', '.join(AGENTS)}.")
    p = global_paths(home)
    for k in ("claude_settings", "claude_json", "codex_hooks", "opencode_json"):
        _read_json(p[k])  # validate first: a broken file must never leave a half install
    rules = _guide("agents_block.md")
    done = []
    if agent == "claude":
        for k in ("claude_settings", "claude_json", "claude_md"):
            _backup(p[k])
        _merge_hooks(p["claude_settings"], "claude", CLAUDE_EVENTS)
        _merge_json(p["claude_json"], "mcpServers", "keelyard", {"type": "stdio", "command": _exe_path(), "args": ["mcp"]})
        _set_block(p["claude_md"], rules)
        skill = p["claude_dir"] / "skills" / "keelyard" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(_guide("SKILL.md"), encoding="utf-8")
        cmds = p["claude_dir"] / "commands" / "keelyard"
        cmds.mkdir(parents=True, exist_ok=True)
        for name, src in CLAUDE_COMMANDS.items():
            (cmds / f"{name}.md").write_text(_guide(src), encoding="utf-8")
        for name in WORKFLOWS:
            (cmds / f"{name}.md").write_text(_command(name), encoding="utf-8")
        done += [str(p["claude_settings"]), str(p["claude_json"]), str(p["claude_md"])]
    elif agent == "codex":
        for k in ("codex_toml", "codex_hooks", "codex_md"):
            _backup(p[k])
        _merge_hooks(p["codex_hooks"], "codex", CODEX_EVENTS)
        _toml_block(p["codex_toml"], f"[mcp_servers.keelyard]\ncommand = {json.dumps(_exe_path())}\nargs = [\"mcp\"]")
        _set_block(p["codex_md"], rules)
        done += [str(p["codex_toml"]), str(p["codex_hooks"]), str(p["codex_md"])]
    else:
        for k in ("opencode_json", "opencode_md"):
            _backup(p[k])
        js = resources.files("keelyard.adapters").joinpath("opencode_plugin.js").read_text()
        p["opencode_plugin"].parent.mkdir(parents=True, exist_ok=True)
        p["opencode_plugin"].write_text(js.replace('const KEELYARD = "keelyard";', f"const KEELYARD = {json.dumps(_exe_path())};", 1))
        _merge_json(p["opencode_json"], "mcp", "keelyard", {"type": "local", "command": [_exe_path(), "mcp"], "enabled": True})
        _set_block(p["opencode_md"], rules)
        cmds = p["opencode_dir"] / "command"
        cmds.mkdir(parents=True, exist_ok=True)
        for name in WORKFLOWS:
            (cmds / f"keelyard-{name}.md").write_text(_command(name), encoding="utf-8")
        done += [str(p["opencode_json"]), str(p["opencode_plugin"]), str(p["opencode_md"])]
    _set_global_marker(agent, True)
    return done


def uninstall_global(agent: str, home: Path | None = None) -> list[str]:
    p = global_paths(home)
    done = []
    if agent == "claude":
        if _strip_hooks(p["claude_settings"]):
            done.append(str(p["claude_settings"]))
        if _drop_key(p["claude_json"], "mcpServers"):
            done.append(str(p["claude_json"]))
        if _set_block(p["claude_md"], None):
            done.append(str(p["claude_md"]))
        for d in (p["claude_dir"] / "skills" / "keelyard", p["claude_dir"] / "commands" / "keelyard"):
            if d.is_dir():
                shutil.rmtree(d)
                done.append(str(d))
    elif agent == "codex":
        if _strip_hooks(p["codex_hooks"]):
            done.append(str(p["codex_hooks"]))
        if p["codex_toml"].exists():
            _toml_block(p["codex_toml"], None)
            done.append(str(p["codex_toml"]))
        if _set_block(p["codex_md"], None):
            done.append(str(p["codex_md"]))
    else:
        if _drop_key(p["opencode_json"], "mcp"):
            done.append(str(p["opencode_json"]))
        if p["opencode_plugin"].exists():
            p["opencode_plugin"].unlink()
            done.append(str(p["opencode_plugin"]))
        if _set_block(p["opencode_md"], None):
            done.append(str(p["opencode_md"]))
        for name in WORKFLOWS:
            f = p["opencode_dir"] / "command" / f"keelyard-{name}.md"
            if f.exists():
                f.unlink()
    _set_global_marker(agent, False)
    return done


def _marker() -> Path:
    from ..config import data_home

    return data_home() / "global.json"


def _set_global_marker(agent: str, on: bool) -> None:
    m = _marker()
    agents = set(json.loads(m.read_text()).get("agents", [])) if m.exists() else set()
    (agents.add if on else agents.discard)(agent)
    m.write_text(json.dumps({"agents": sorted(agents)}))


def global_agents() -> list[str]:
    try:
        return list(json.loads(_marker().read_text()).get("agents", []))
    except (OSError, ValueError):
        return []


def installed_global(agent: str, home: Path | None = None) -> bool:
    p = global_paths(home)
    if agent == "opencode":
        return p["opencode_plugin"].exists()
    f = p["claude_settings"] if agent == "claude" else p["codex_hooks"]
    try:
        t = f.read_text()
    except OSError:
        return False
    return "keelyard" in t and " hook " in t
