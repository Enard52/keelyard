"""Terminal output. One restrained palette; colour only where it carries meaning."""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.markup import escape
from rich.theme import Theme

THEME = Theme({
    "ok": "#3f9d6a",
    "bad": "#d1453b",
    "warn": "#c28a1e",
    "muted": "#8a8a85",
    "key": "bold",
    "accent": "#3f9d6a",
    "path": "#6c8fb3",
})

_no_color = bool(os.environ.get("NO_COLOR"))
# rich treats any FORCE_COLOR value as "force", but FORCE_COLOR=0 means the opposite in most tools
_force = False if os.environ.get("FORCE_COLOR") in ("0", "false") else None
out = Console(theme=THEME, highlight=False, no_color=_no_color, soft_wrap=True, force_terminal=_force)
err = Console(theme=THEME, highlight=False, no_color=_no_color, stderr=True, force_terminal=_force)

OK, BAD, WARN, DOT = "✓", "✗", "!", "·"
if not (sys.stdout.encoding or "").lower().startswith("utf"):
    OK, BAD, WARN, DOT = "ok", "x", "!", "-"


def heading(text: str, sub: str = "") -> None:
    out.print(f"[key]{text}[/]" + (f"  [muted]{sub}[/]" if sub else ""))


def line(state: str, label: str, detail: str = "", width: int = 18) -> None:
    mark = {"ok": f"[ok]{OK}[/]", "bad": f"[bad]{BAD}[/]", "warn": f"[warn]{WARN}[/]", "skip": f"[muted]{DOT}[/]"}[state]
    out.print(f"  {mark} {escape(label):<{width}} [muted]{escape(detail)}[/]")


def error(message: str) -> None:
    """Print `error: ...` and, if the message carries one, a separate hint line."""
    msg, _, hint = message.partition("Hint:")
    err.print(f"[bad]error:[/] {escape(msg.strip())}")
    if hint.strip():
        err.print(f"[muted]hint:[/]  {escape(hint.strip())}")


def plain(text: str) -> None:
    out.print(text, markup=False, highlight=False)


def tilde(path) -> str:
    """A path for people to read: ~/... under the home folder (JSON output keeps full paths)."""
    import os
    from pathlib import Path

    p, home = str(path), str(Path.home())
    if home and home not in (os.sep, "") and (p == home or p.startswith(home + os.sep)):
        return "~" + p[len(home):]
    return p
