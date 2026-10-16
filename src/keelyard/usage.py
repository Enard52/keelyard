"""Token usage from the agents' own local logs (the ccusage idea, for three agents).

Reads Claude Code, Codex and OpenCode session files, de-duplicates streamed
messages, and aggregates tokens per day, agent and model. Cost is computed only
from prices you put in .keelyard/config.toml ([prices."model"]), or taken from
OpenCode's own recorded cost. keelyard ships no price table, so it cannot go stale.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .memory import default_sources


@dataclass
class Row:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0
    messages: int = 0
    priced: bool = True
    models: set = field(default_factory=set)

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write


def _claude(base: Path):
    for f in base.glob("*/*.jsonl"):
        seen = set()
        for line in f.read_text(errors="replace", encoding="utf-8").splitlines():
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = j.get("message") if isinstance(j.get("message"), dict) else {}
            u = m.get("usage")
            if j.get("type") != "assistant" or not u:
                continue
            key = (m.get("id"), j.get("requestId"))
            if key[0] and key in seen:
                continue
            seen.add(key)
            yield ("claude-code", j.get("timestamp", "")[:10], m.get("model", "?"), u.get("input_tokens", 0),
                   u.get("output_tokens", 0), u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0), None)


def _codex(base: Path):
    for f in base.rglob("*.jsonl"):
        model = "?"
        for line in f.read_text(errors="replace", encoding="utf-8").splitlines():
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = j.get("payload") or {}
            if j.get("type") == "turn_context":
                model = p.get("model", model)
            elif j.get("type") == "event_msg" and p.get("type") == "token_count":
                u = (p.get("info") or {}).get("last_token_usage")
                if u:
                    cached = u.get("cached_input_tokens", 0)
                    yield ("codex", j.get("timestamp", "")[:10], model, u.get("input_tokens", 0) - cached,
                           u.get("output_tokens", 0), cached, 0, None)


def _opencode(storage: Path):
    import datetime as dt

    for f in (storage / "message").glob("*/*.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        t = m.get("tokens")
        if m.get("role") != "assistant" or not t:
            continue
        created = (m.get("time") or {}).get("created") or 0
        day = dt.datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d") if created else ""
        c = t.get("cache") or {}
        yield ("opencode", day, m.get("modelID", "?"), t.get("input", 0), t.get("output", 0) + t.get("reasoning", 0),
               c.get("read", 0), c.get("write", 0), m.get("cost"))


def collect(prices: dict | None = None, sources=None, by: str = "day") -> dict[str, Row]:
    prices = prices or {}
    readers = {"claude-code": _claude, "codex": _codex, "opencode": _opencode}
    rows: dict[str, Row] = defaultdict(Row)
    for agent, base in sources or default_sources():
        if not base.exists():
            continue
        for ag, day, model, i, o, cr, cw, cost in readers[agent](base):
            key = {"day": f"{day} {ag}", "model": f"{ag} {model}", "agent": ag}[by]
            r = rows[key]
            r.input, r.output, r.cache_read, r.cache_write = r.input + i, r.output + o, r.cache_read + cr, r.cache_write + cw
            r.messages += 1
            r.models.add(model)
            if cost is not None:
                r.cost += float(cost)
            elif model in prices:
                pr = prices[model]
                r.cost += (i * pr.get("input", 0) + o * pr.get("output", 0) + cr * pr.get("cache_read", 0)
                           + cw * pr.get("cache_write", 0)) / 1e6
            else:
                r.priced = False
    return dict(sorted(rows.items()))


def table(rows: dict[str, Row]) -> str:
    if not rows:
        return "no agent usage logs found"
    out = [f"{'key':<34}{'input':>12}{'output':>10}{'cache rd':>12}{'cache wr':>11}{'cost $':>10}"]
    for k, r in rows.items():
        cost = f"{r.cost:.2f}" + ("" if r.priced else "*")
        out.append(f"{k[:33]:<34}{r.input:>12,}{r.output:>10,}{r.cache_read:>12,}{r.cache_write:>11,}{cost:>10}")
    if any(not r.priced for r in rows.values()):
        out.append("* some models have no [prices] entry in .keelyard/config.toml; their cost is not included")
    return "\n".join(out)
