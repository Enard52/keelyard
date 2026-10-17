"""Per-task-type table from bench/session/run.py results, and the 70% gate.

    python bench/session/report.py bench/session/runs.jsonl [--setup lean] [--gate 0.70]

Saving = 1 - mean(total tokens with keelyard) / mean(total tokens without keelyard), per task. Every attempt
counts (failed runs too). Quality: correct runs / runs, which must not be lower than the baseline's.
Exits 1 (the gate, default --gate 0.70) if any task saves less than the gate or loses quality.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from statistics import mean


def load(path: str) -> dict:
    g = defaultdict(list)
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if "total" in r:
            g[(r["task"], r["setup"])].append(r)
    return g


def table(g: dict, setup: str, gate: float | None) -> tuple[list[str], bool]:
    rows = [f"| task | runs (base/{setup}) | baseline tokens (mean) | {setup} tokens (mean) | saving | correct base | correct {setup} | gate |",
            "|---|---|---:|---:|---:|---:|---:|---|"]
    ok = True
    allb, allk = [], []
    for task in sorted({t for t, _ in g}):
        b, k = g.get((task, "baseline"), []), g.get((task, setup), [])
        if not b or not k:
            continue
        mb, mk = mean(r["total"] for r in b), mean(r["total"] for r in k)
        allb.append(mb)
        allk.append(mk)
        save = 1 - mk / mb
        qb, qk = sum(r["correct"] for r in b) / len(b), sum(r["correct"] for r in k) / len(k)
        passed = (gate is None or save >= gate) and qk >= qb
        ok &= passed
        rows.append(f"| {task} | {len(b)}/{len(k)} | {mb:,.0f} | {mk:,.0f} | {save:.0%} | {qb:.0%} | {qk:.0%} | "
                    f"{'pass' if passed else 'FAIL'} |")
    if allb:
        rows.append(f"| **all (sum of means)** | | {sum(allb):,.0f} | {sum(allk):,.0f} | {1 - sum(allk) / sum(allb):.0%} | | | |")
    return rows, ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--setup", default="lean")
    ap.add_argument("--gate", type=float, default=0.70, help="minimum saving per task (0 = report only)")
    a = ap.parse_args()
    rows, ok = table(load(a.path), a.setup, a.gate or None)
    print("\n".join(rows))
    if not ok:
        print(f"GATE FAIL: a task saves under {a.gate:.0%} or loses quality", file=sys.stderr)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
