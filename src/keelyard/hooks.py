"""Hook entry point shared by all agents.

Claude Code sends one JSON object on stdin per event; Codex and OpenCode
adapters translate their events into the same shape before calling us.
A hook must never break the agent, so every failure is logged and swallowed.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from . import config, session
from .proof import Proof
from .report import render
from .saver import ReadCache
from .snapshot import Shadow

EDIT_TOOLS_READ = {"Read", "read", "view"}


def _file_arg(tool_input: dict) -> str | None:
    return tool_input.get("file_path") or tool_input.get("filePath") or tool_input.get("path")


def handle(event: str, payload: dict, cfg: config.Config) -> dict | None:
    sid = session.set_current(cfg, payload.get("session_id") or payload.get("sessionID"))
    tool = payload.get("tool_name") or payload.get("tool") or ""
    tin = payload.get("tool_input") or payload.get("args") or {}
    rew = cfg.section("rewind")
    sav = cfg.section("saver")

    if event == "SessionStart":
        if payload.get("source") in ("compact", "clear"):
            ReadCache(cfg, sid).reset()
        if rew["enabled"]:
            Shadow(cfg).snapshot(tool="baseline", session=sid)
        return None

    if event == "UserPromptSubmit":
        Proof(cfg, sid).set_task(payload.get("prompt", ""))
        return None

    if event == "PreCompact":
        ReadCache(cfg, sid).reset()
        return None

    if event == "PreToolUse" and tool in EDIT_TOOLS_READ and sav.get("dedupe_reads", True):
        f = _file_arg(tin)
        if not f or tin.get("offset") or tin.get("limit"):
            return None
        rc = ReadCache(cfg, sid)
        try:
            p = rc.resolve(f)
        except (PermissionError, ValueError):
            return None
        prev = rc.seen(p)
        if prev and p.is_file():
            import hashlib

            if hashlib.sha256(p.read_bytes()).hexdigest()[:16] == prev["sha"]:
                return {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": (f"keelyard: {f} is unchanged since you read it this session; "
                                                 "use the content already in your context. If it was compacted away, "
                                                 "read with an offset/limit or call the keelyard read_file tool with force=true.")}}
        return None

    if event == "PostToolUse":
        if tool in EDIT_TOOLS_READ:
            f = _file_arg(tin)
            if f and not tin.get("offset") and not tin.get("limit"):
                rc = ReadCache(cfg, sid)
                try:
                    p = rc.resolve(f)
                    if p.is_file():
                        rc.remember(p, p.read_bytes())
                except (PermissionError, ValueError):
                    pass
        if rew["enabled"] and tool in rew["snapshot_tools"]:
            Shadow(cfg).snapshot(tool=tool, session=sid)
        return None

    if event == "Stop":
        if rew["enabled"]:
            Shadow(cfg).snapshot(tool="stop", session=sid)
        pf = Proof(cfg, sid)
        gaps = pf.missing()
        report = render(pf)
        opts = cfg.section("proof")
        if not gaps or not opts["gate"]:
            return None
        b = pf.load()
        if b.blocks >= int(opts["max_blocks"]):
            return {"systemMessage": f"keelyard: proof incomplete after {b.blocks} reminders; see {report}"}
        b.blocks += 1
        pf.save(b)
        reason = ("keelyard proof gate: you changed files but have not proven the work yet.\n- "
                  + "\n- ".join(gaps)
                  + "\nUse the keelyard MCP tools (proof_requirements, proof_check, proof_run_tests, proof_screenshot), "
                    "or the `keelyard proof` CLI, then finish.")
        return {"decision": "block", "reason": reason}
    return None


def main(agent: str, event: str) -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    cwd = payload.get("cwd") or payload.get("directory")
    cfg = config.load(config.find_root(Path(cwd)) if cwd else None)
    try:
        out = handle(event, payload, cfg)
    except Exception:  # noqa: BLE001
        with (cfg.state / "hook.log").open("a") as f:
            f.write(f"{time.ctime()} {agent} {event}\n{traceback.format_exc()}\n")
        return 0
    if out:
        print(json.dumps(out))
    return 0
