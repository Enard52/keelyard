"""Hook entry point shared by all agents.

Claude Code sends one JSON object on stdin per event; Codex and OpenCode
adapters translate their events into the same shape before calling us.
A hook must never break the agent, so every failure is logged and swallowed.
"""

from __future__ import annotations

import hashlib
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


def _filter_bash(cfg: config.Config, tin: dict, resp) -> dict | None:
    """Shrink a finished Bash result in place (Claude Code PostToolUse updatedToolOutput).

    The command already ran unchanged; only what the model reads is filtered, and the raw
    output stays recoverable with `keelyard recall <id>`. No permission decision is touched.
    """
    if not isinstance(resp, dict) or resp.get("isImage") or not isinstance(resp.get("stdout"), str):
        return None
    from .filters import filter_output
    from .saver import approx_tokens

    raw_out, raw_err = resp.get("stdout", ""), resp.get("stderr", "") or ""
    raw = raw_out + ("\n" + raw_err if raw_err else "")
    if len(raw) < int(cfg.section("saver").get("filter_min_chars", 1200)):
        return None
    small = filter_output(tin.get("command", ""), raw)
    if len(small) > 0.8 * len(raw):
        return None
    h = hashlib.sha256(raw.encode()).hexdigest()[:12]
    raw_dir = cfg.state / "raw"
    raw_dir.mkdir(exist_ok=True)
    (raw_dir / h).write_text(raw)
    note = f"\n[keelyard filtered {approx_tokens(raw)}→{approx_tokens(small)} tokens; full output: keelyard recall {h}]"
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": {
        "stdout": small + note, "stderr": "", "interrupted": bool(resp.get("interrupted")), "isImage": False}}}


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
            if hashlib.sha256(p.read_bytes()).hexdigest()[:16] == prev["sha"]:
                return {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": (f"keelyard: {f} is unchanged since you read it this session; "
                                                 "use the content already in your context. If it was compacted away, "
                                                 "read with an offset/limit or call the keelyard read_file tool with force=true.")}}
        return None

    if event == "PostToolUse":
        out = None
        if tool == "Bash" and sav.get("filter_bash", True):
            out = _filter_bash(cfg, tin, payload.get("tool_response"))
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
        return out

    if event == "Stop":
        if rew["enabled"]:
            Shadow(cfg).snapshot(tool="stop", session=sid)
        pf = Proof(cfg, sid)
        gaps = pf.missing()
        report = render(pf)
        opts = cfg.section("proof")
        b = pf.load()
        if pf.last_edit_ts() is not None or b.requirements:
            b.gate.append({"ts": time.time(), "blocked": bool(gaps and opts["gate"] and b.blocks < int(opts["max_blocks"])),
                           "open": len(gaps)})
            b.gate = b.gate[-50:]
            pf.save(b)
        if not gaps or not opts["gate"]:
            return None
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
    try:
        start = Path(cwd) if cwd and Path(cwd).is_dir() else None
        cfg = config.load(config.find_root(start))
        cfg.require_project()
    except Exception:  # noqa: BLE001 - not a project, or a broken config: stay out of the agent's way
        return 0
    try:
        out = handle(event, payload, cfg)
    except Exception:  # noqa: BLE001
        log = cfg.state / "hook.log"
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{time.ctime()} {agent} {event}\n{traceback.format_exc()}\n")
        if log.stat().st_size > 1_000_000:  # keep the log bounded
            log.write_text(log.read_text(errors="replace")[-200_000:])
        return 0
    if out:
        print(json.dumps(out))
    return 0
