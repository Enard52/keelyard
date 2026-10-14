"""Measure helper quality on a small fixed task set: single-shot, the verified pipeline, the best local
configuration we can afford (more samples and retries), and the cooperative swarm (blackboard, critic, voting).

Usage: python bench/swarm_quality.py [--base-url http://localhost:11434/v1] [--model qwen-coder-1.5b] [--runs 2]
Ground truth for drafts = the full test suite passes after applying the patch in a throwaway copy.
Ground truth for questions = the answer cites the expected file:line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from keelyard import config  # noqa: E402
from keelyard.coop import Coop  # noqa: E402
from keelyard.swarm import CITE, Swarm, Task, plan, test_patch  # noqa: E402

FILLER = "".join(f"\n\ndef helper_{i}(x):\n    \"\"\"Unrelated helper {i}.\"\"\"\n    return x * {i} + {i}\n" for i in range(25))

MODULES = {
    "cart.py": ("def total(prices, coupon=None):\n    subtotal = sum(prices)\n    if coupon == \"SAVE10\":\n"
                "        subtotal = subtotal * 0.10\n    return round(subtotal, 2)\n",
                "from cart import total\n\ndef test_total():\n    assert total([100]) == 100\n    assert total([100], \"SAVE10\") == 90\n"),
    "text.py": ("def slugify(title):\n    words = title.strip().split()\n    return \"-\".join(words)\n",
                "from text import slugify\n\ndef test_slug():\n    assert slugify(\" Hello World \") == \"hello-world\"\n"),
    "dates.py": ("def is_weekend(weekday):\n    \"\"\"weekday: 0=Mon .. 6=Sun\"\"\"\n    return weekday > 5\n",
                 "from dates import is_weekend\n\ndef test_weekend():\n    assert is_weekend(5) and is_weekend(6) and not is_weekend(4)\n"),
    "stats.py": ("def mean(xs):\n    if not xs:\n        return 0.0\n    return sum(xs) / (len(xs) - 1)\n",
                 "from stats import mean\n\ndef test_mean():\n    assert mean([2, 4]) == 3\n    assert mean([]) == 0.0\n"),
    "stock.py": ("def remove(stock, n):\n    \"\"\"Remove n items; never below zero.\"\"\"\n    return stock - n\n",
                 "from stock import remove\n\ndef test_remove():\n    assert remove(5, 2) == 3\n    assert remove(1, 3) == 0\n"),
}
DRAFTS = [
    ("Fix total so SAVE10 takes 10% off instead of charging 10%.", "cart.py", ["total"]),
    ("Fix slugify so it lowercases the words.", "text.py", ["slugify"]),
    ("Fix is_weekend so Saturday (5) counts as weekend.", "dates.py", ["is_weekend"]),
    ("Fix mean so it divides by the number of items.", "stats.py", ["mean"]),
    ("Fix remove so stock never goes below zero.", "stock.py", ["remove"]),
]
ASKS = [
    ("Which line applies the coupon to the subtotal in total?", "cart.py", ["total"], 4),
    ("Which line joins the words in slugify?", "text.py", ["slugify"], 3),
    ("Which line decides whether the day is a weekend?", "dates.py", ["is_weekend"], 3),
    ("Which line divides in mean?", "stats.py", ["mean"], 4),
    ("Which line returns the new stock count in remove?", "stock.py", ["remove"], 3),
]


def make_repo(d: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    for name, (src, test) in MODULES.items():
        (d / name).write_text(src + FILLER)
        (d / f"test_{name}").write_text(test)


def write_cfg(d: Path, base_url: str, model: str) -> None:
    (d / ".keelyard").mkdir(exist_ok=True)
    py = Path(sys.executable).as_posix()
    (d / ".keelyard" / "config.toml").write_text(
        f'[proof]\ntest_cmd = "{py} -m pytest -q -p no:cacheprovider"\n'
        f'[swarm]\nconcurrency = 2\nworkers = 2\nescalate_model = ""\n'
        f'[models.cheap]\nprovider = "openai"\nbase_url = "{base_url}"\nmodel = "{model}"\nmax_tokens = 600\n')


async def run_mode(cfg, mode: str) -> dict:
    if mode == "single":
        sw = Swarm(cfg, best_of=1, retries=0, test_patches=False)
        drafts = [Task("draft_edit", g, [f]) for g, f, _ in DRAFTS]
        asks = [Task("ask", q, [f]) for q, f, _, _ in ASKS]
    else:
        if mode == "pipeline":
            sw = Swarm(cfg, best_of=3, retries=1, test_patches=True)
        elif mode == "best-local":  # stand-in for "one strong agent": the most compute we give one model
            sw = Swarm(cfg, best_of=5, retries=2, test_patches=True)
        else:
            sw = Coop(cfg, best_of=3, retries=1, test_patches=True)
            sw.critic = mode == "coop"  # "coop-nocritic": blackboard, voting, routing and budget only
        drafts = [plan(cfg, g, [f])[0] for g, f, _ in DRAFTS]
        for t, (_, _, syms) in zip(drafts, DRAFTS, strict=True):
            t.symbols = syms  # what plan() finds by symbol name; set explicitly since files= skips the lookup
        asks = [Task("ask", q, [f], symbols=s) for q, f, s, _ in ASKS]
    t0 = time.time()
    res = await sw.run(drafts + asks)
    secs = time.time() - t0
    d_res, a_res = res[:len(drafts)], res[len(drafts):]
    py = Path(sys.executable).as_posix()

    def truly_fixed(r, f):  # ground truth: that module's own tests pass with the patch, in a throwaway copy
        return bool(r.output and "@@" in r.output and test_patch(cfg, r.output, f"{py} -m pytest -q -p no:cacheprovider test_{f}")[0])
    truth = [truly_fixed(r, f) for r, (_, f, _) in zip(d_res, DRAFTS, strict=True)]
    correct_d = sum(truth)
    claimed_d = sum(r.verified for r in d_res)
    false_ok = sum(1 for r, ok in zip(d_res, truth, strict=True) if r.verified and not ok)

    def cites_line(text, f, line):
        return any(Path(p).name == f and int(a) <= line <= int(b or a) for p, a, b in CITE.findall(text))
    correct_a = sum(1 for r, (_, f, _, ln) in zip(a_res, ASKS, strict=True) if cites_line(r.output, f, ln))
    tokens = sum(r.tokens_in + r.tokens_out for r in res)
    calls = sw.ledger.calls if isinstance(sw, Coop) else sum(r.candidates for r in res)
    return {"mode": mode, "correct": correct_d + correct_a, "tokens": tokens,
            "tokens_per_correct": round(tokens / (correct_d + correct_a)) if correct_d + correct_a else None,
            "drafts_correct": correct_d, "drafts_verified": claimed_d, "drafts_verified_but_wrong": false_ok,
            "asks_correct": correct_a, "asks_verified": sum(r.verified for r in a_res),
            "tokens_in": sum(r.tokens_in for r in res), "tokens_out": sum(r.tokens_out for r in res),
            "model_calls": calls, "seconds": round(secs, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--model", default="qwen-coder-1.5b")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--modes", default="single,pipeline,best-local,coop,coop-nocritic")
    ap.add_argument("--out", type=Path, default=ROOT / "bench" / "swarm_quality.json")
    a = ap.parse_args()
    rows = []
    for run in range(a.runs):
        for mode in a.modes.split(","):
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                make_repo(d)
                write_cfg(d, a.base_url, a.model)
                row = asyncio.run(run_mode(config.load(d), mode))
                row["run"] = run + 1
                rows.append(row)
                print(json.dumps(row))
    a.out.write_text(json.dumps({"model": a.model, "drafts": len(DRAFTS), "asks": len(ASKS), "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
