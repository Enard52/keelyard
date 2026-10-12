"""Minimal curses timeline: browse snapshots, view diffs, rewind."""

from __future__ import annotations

import curses
import datetime as dt

from .snapshot import Shadow


def run(shadow: Shadow) -> str | None:
    return curses.wrapper(_loop, shadow)


def _loop(scr, shadow: Shadow) -> str | None:
    curses.curs_set(0)
    steps = list(reversed(shadow.steps()))
    if not steps:
        return "no snapshots yet"
    sel, msg = 0, "↑/↓ move · enter diff · r rewind · q quit"
    while True:
        scr.erase()
        h, w = scr.getmaxyx()
        scr.addnstr(0, 0, f"keelyard timeline · {len(steps)} steps · {msg}", w - 1, curses.A_BOLD)
        top = max(0, sel - (h - 3))
        for i, s in enumerate(steps[top:top + h - 2]):
            idx = top + i
            t = dt.datetime.fromtimestamp(s.ts).strftime("%H:%M:%S")
            line = f"#{s.step:<4} {t}  {s.tool:<12} {', '.join(s.files[:4])}"
            scr.addnstr(i + 1, 0, line, w - 1, curses.A_REVERSE if idx == sel else 0)
        scr.refresh()
        k = scr.getch()
        if k in (ord("q"), 27):
            return None
        if k in (curses.KEY_DOWN, ord("j")):
            sel = min(sel + 1, len(steps) - 1)
        elif k in (curses.KEY_UP, ord("k")):
            sel = max(sel - 1, 0)
        elif k in (10, 13, curses.KEY_ENTER):
            _pager(scr, shadow.diff(steps[sel].step))
        elif k == ord("r"):
            scr.addnstr(h - 1, 0, f"rewind workspace to #{steps[sel].step}? y/n", w - 1, curses.A_BOLD)
            if scr.getch() == ord("y"):
                res = shadow.rewind(steps[sel].step)
                return f"restored step {res['restored']} (undo: keelyard rewind {res['safety_step']})"


def _pager(scr, text: str) -> None:
    lines, off = text.splitlines() or ["(empty)"], 0
    while True:
        scr.erase()
        h, w = scr.getmaxyx()
        for i, ln in enumerate(lines[off:off + h - 1]):
            attr = curses.A_BOLD if ln.startswith(("+", "-", "@@")) else 0
            scr.addnstr(i, 0, ln, w - 1, attr)
        scr.addnstr(h - 1, 0, "space/b page · q back", w - 1, curses.A_DIM)
        k = scr.getch()
        if k in (ord("q"), 27):
            return
        if k in (ord(" "), curses.KEY_NPAGE):
            off = min(off + h - 1, max(0, len(lines) - 1))
        elif k in (ord("b"), curses.KEY_PPAGE):
            off = max(0, off - h + 1)
