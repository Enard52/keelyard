"""Compact work state: requirements, decisions, changes and open questions, each tied to evidence.

After a compaction the agent gets this instead of re-reading the whole conversation. Every key conclusion
must point at something checkable: a file and line (``src/cart.py:42``), a command (``cmd: pytest -q``) or a
proof item (``#3``). References are validated when added and re-checked on every render, so a stale
reference shows up as stale instead of silently misleading the agent.
"""
from __future__ import annotations

import json
import re
import time

from .config import Config
from .saver import approx_tokens

KINDS = ("decision", "question", "note")
FILE_REF = re.compile(r"^(?P<path>[^:\s]+?)(?::(?P<line>\d+)(?:-(?P<end>\d+))?)?$")


class WorkState:
    def __init__(self, cfg: Config, session: str):
        self.cfg, self.session = cfg, session
        self.path = cfg.state / "work" / f"{session}.json"

    def load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def check_ref(self, ref: str) -> str | None:
        """None when the reference is valid now, else why not."""
        ref = ref.strip()
        if ref.startswith("cmd:"):
            return None if ref[4:].strip() else "empty command"
        if re.fullmatch(r"#\d+", ref):
            from .proof import Proof

            ids = {r["id"] for r in Proof(self.cfg, self.session).load().requirements}
            return None if int(ref[1:]) in ids else f"no proof item {ref}"
        m = FILE_REF.match(ref.replace("\\", "/"))
        if not m:
            return "use path:line, cmd: <command> or #<proof item>"
        p = (self.cfg.root / m["path"]).resolve()
        try:
            p.relative_to(self.cfg.root.resolve())
        except ValueError:
            return "outside the project"
        if not p.is_file():
            return f"{m['path']} does not exist"
        if m["line"]:
            n = len(p.read_bytes().splitlines())
            if int(m["end"] or m["line"]) > n or int(m["line"]) < 1:
                return f"{m['path']} has {n} lines"
        return None

    def add(self, kind: str, text: str, ref: str) -> dict:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        if not text.strip():
            raise ValueError("empty text")
        if kind != "question":  # an open question may not have evidence yet; a conclusion must
            why = self.check_ref(ref or "")
            if why:
                raise ValueError(f"reference {ref!r}: {why}")
        items = self.load()
        item = {"id": max((i["id"] for i in items), default=0) + 1, "kind": kind, "text": text.strip()[:300],
                "ref": (ref or "").strip(), "ts": time.time(), "done": False}
        items.append(item)
        self._save(items)
        return item

    def resolve(self, item_id: int) -> dict:
        items = self.load()
        for i in items:
            if i["id"] == item_id:
                i["done"] = True
                self._save(items)
                return i
        raise KeyError(f"no work-state item {item_id}")

    def changes(self, limit: int = 12) -> list[str]:
        """Files this session changed, newest first, with the rewind step that holds each version."""
        try:
            from .snapshot import Shadow

            steps = [s for s in Shadow(self.cfg).steps() if s.session == self.session]
        except Exception:  # noqa: BLE001 - no timeline must not hide the rest of the state
            return []
        seen: dict[str, int] = {}
        for s in reversed(steps):
            for f in s.files:
                seen.setdefault(f, s.step)
        return [f"{f} (step {n})" for f, n in list(seen.items())[:limit]]

    def render(self, budget_tokens: int = 400) -> str:
        """The compact state. Empty string when there is nothing to say (costs zero tokens)."""
        from .proof import Proof

        sections: list[tuple[str, list[str]]] = []
        try:
            reqs = Proof(self.cfg, self.session).load().requirements
        except Exception:  # noqa: BLE001
            reqs = []
        if reqs:
            sections.append(("Requirements", [f"#{r['id']} [{'x' if r['done'] else ' '}] {r['text']}" for r in reqs]))
        items = self.load()

        def line(i: dict) -> str:
            ref = i["ref"]
            if not ref:
                return f"{i['text']} (id {i['id']})"
            why = self.check_ref(ref)
            return f"{i['text']} → {ref}" + (f" [STALE: {why}]" if why else "")

        dec = [line(i) for i in items if i["kind"] in ("decision", "note")]
        if dec:
            sections.append(("Decisions", dec))
        ch = self.changes()
        if ch:
            sections.append(("Changed", ch))
        qs = [line(i) for i in items if i["kind"] == "question" and not i["done"]]
        if qs:
            sections.append(("Open questions", qs))
        if not sections:
            return ""
        out, used = ["Work state (verify refs before relying on them):"], 10
        for title, rows in sections:
            out.append(f"{title}:")
            used += 3
            for k, r in enumerate(rows):
                t = approx_tokens(r) + 1
                if used + t > budget_tokens:
                    out.append(f"- … {len(rows) - k} more: keelyard state")
                    used += 8
                    break
                out.append(f"- {r}")
                used += t
        return "\n".join(out)
