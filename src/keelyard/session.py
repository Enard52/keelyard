"""Tracks which agent session is current, so MCP tools and hooks agree."""

from __future__ import annotations

import re

from .config import Config

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def clean(session_id: str | None) -> str:
    sid = _SAFE.sub("_", session_id or "")[:80]
    return sid or "default"


def set_current(cfg: Config, session_id: str | None) -> str:
    sid = clean(session_id)
    (cfg.state / "current_session").write_text(sid)
    return sid


def current(cfg: Config) -> str:
    p = cfg.state / "current_session"
    return clean(p.read_text().strip()) if p.exists() else "default"
