"""Arena: run the same task across agents and models, then measure what happened.

For each (agent, run) the task's template repo is copied fresh, the agent's CLI is
run headless with the prompt, and the task's check command decides pass/fail.
Tokens and cost come from the agent's own machine-readable output. Nothing is estimated:
if an agent does not report usage, the cell says "n/a".

Results go to results.json (shareable, re-renderable) and report.html (+ chart.png
when matplotlib is installed).
"""

from __future__ import annotations

import html
import json
import shutil
import statistics
import subprocess
import tempfile
import time
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Run:
    agent: str
    model: str
    run: int
    passed: bool
    seconds: float
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cost_usd: float | None
    files_changed: int
    exit_code: int
    note: str = ""


def parse_usage(stdout: str) -> dict:
    """Understands Claude Code `-p --output-format json`, Codex `exec --json` and OpenCode-style JSON lines."""
    found = {"input": None, "output": None, "cache_read": None, "cost": None}

    def add(k, v):
        if isinstance(v, (int, float)):
            found[k] = (found[k] or 0) + v

    docs = []
    try:
        docs.append(json.loads(stdout))
    except json.JSONDecodeError:
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    docs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    flat = [x for d in docs for x in (d if isinstance(d, list) else [d])]
    for d in flat:
        if not isinstance(d, dict):
            continue
        if d.get("type") == "result" or "total_cost_usd" in d:  # Claude Code
            u = d.get("usage") or {}
            add("input", u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0))
            add("output", u.get("output_tokens"))
            add("cache_read", u.get("cache_read_input_tokens"))
            add("cost", d.get("total_cost_usd"))
        elif d.get("type") == "turn.completed" and isinstance(d.get("usage"), dict):  # Codex exec --json
            u = d["usage"]
            add("input", u.get("input_tokens", 0) - u.get("cached_input_tokens", 0))
            add("output", u.get("output_tokens"))
            add("cache_read", u.get("cached_input_tokens"))
        elif isinstance(d.get("tokens"), dict):  # OpenCode message
            t = d["tokens"]
            add("input", t.get("input"))
            add("output", (t.get("output") or 0) + (t.get("reasoning") or 0))
            add("cache_read", (t.get("cache") or {}).get("read"))
            add("cost", d.get("cost"))
    return found


def _changed(repo: Path) -> int:
    p = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True)
    return len([ln for ln in p.stdout.splitlines() if ln.strip()])


def run_task(spec_path: Path, out_dir: Path, only: list[str] | None = None) -> list[Run]:
    spec = tomllib.loads(spec_path.read_text())
    task = spec["task"]
    template = (spec_path.parent / task["repo"]).resolve()
    runs = int(task.get("runs", 1))
    timeout = int(task.get("timeout", 900))
    results: list[Run] = []
    for agent in spec.get("agent", []):
        if only and agent["name"] not in only:
            continue
        exe = agent["cmd"][0]
        if not shutil.which(exe) and not (spec_path.parent / exe).exists():
            results.append(Run(agent["name"], agent.get("model", ""), 0, False, 0, None, None, None, None, 0, 127,
                               f"{exe} not installed"))
            continue
        for i in range(1, runs + 1):
            with tempfile.TemporaryDirectory(prefix="keelyard-arena-") as tmp:
                repo = Path(tmp) / "repo"
                shutil.copytree(template, repo)
                subprocess.run(["git", "init", "-q"], cwd=repo)
                subprocess.run(["git", "add", "-A"], cwd=repo)
                subprocess.run(["git", "-c", "user.name=arena", "-c", "user.email=a@a", "commit", "-qm", "base"], cwd=repo)
                fmt = {"prompt": task["prompt"], "model": agent.get("model", ""), "repo": str(repo),
                       "here": str(spec_path.parent.resolve())}
                cmd = [c.format(**fmt) for c in agent["cmd"]]
                t0 = time.time()
                try:
                    p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout)
                    code, out, note = p.returncode, p.stdout, ""
                except subprocess.TimeoutExpired:
                    code, out, note = 124, "", f"timeout {timeout}s"
                secs = time.time() - t0
                chk = subprocess.run(task["check"], shell=True, cwd=repo, capture_output=True, text=True, timeout=600)
                u = parse_usage(out)
                results.append(Run(agent["name"], agent.get("model", ""), i, chk.returncode == 0, round(secs, 1),
                                   u["input"], u["output"], u["cache_read"],
                                   round(u["cost"], 4) if u["cost"] is not None else None, _changed(repo), code, note))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(
        {"task": task, "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"), "runs": [asdict(r) for r in results]}, indent=2))
    render(out_dir)
    return results


def summarize(runs: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for r in runs:
        by.setdefault(f"{r['agent']}|{r['model']}", []).append(r)
    rows = []
    for key, rs in by.items():
        agent, model = key.split("|", 1)

        def med(k, rs=rs):
            v = [r[k] for r in rs if r[k] is not None]
            return statistics.median(v) if v else None

        rows.append({"agent": agent, "model": model, "runs": len(rs), "pass_rate": sum(r["passed"] for r in rs) / len(rs),
                     "median_seconds": med("seconds"), "median_input": med("input_tokens"), "median_output": med("output_tokens"),
                     "median_cache_read": med("cache_read_tokens"), "median_cost": med("cost_usd"),
                     "note": "; ".join(sorted({r["note"] for r in rs if r["note"]}))})
    return rows


def _fmt(v, kind="int"):
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{v * 100:.0f}%"
    if kind == "usd":
        return f"${v:.4f}"
    if kind == "s":
        return f"{v:.1f}s"
    return f"{int(v):,}"


def render(out_dir: Path) -> Path:
    data = json.loads((out_dir / "results.json").read_text())
    rows = summarize(data["runs"])
    e = html.escape
    maxtok = max([(r["median_input"] or 0) + (r["median_output"] or 0) for r in rows] + [1])
    bars = []
    for i, r in enumerate(rows):
        tok = (r["median_input"] or 0) + (r["median_output"] or 0)
        w = 520 * tok / maxtok
        y = 20 + i * 34
        bars.append(f"<text x='0' y='{y + 16}' font-size='12'>{e(r['agent'])}</text>"
                    f"<rect x='160' y='{y}' width='{w:.0f}' height='22' rx='4' fill='{'#2f6f4f' if r['pass_rate'] >= .5 else '#a3402f'}'/>"
                    f"<text x='{166 + w:.0f}' y='{y + 16}' font-size='12'>{_fmt(tok) if tok else 'n/a'} tok · {_fmt(r['pass_rate'], 'pct')} pass</text>")
    svg = f"<svg width='860' height='{40 + 34 * len(rows)}' font-family='system-ui'>{''.join(bars)}</svg>"
    trs = "".join(
        f"<tr><td>{e(r['agent'])}</td><td>{e(r['model'])}</td><td>{r['runs']}</td><td>{_fmt(r['pass_rate'], 'pct')}</td>"
        f"<td>{_fmt(r['median_seconds'], 's')}</td><td>{_fmt(r['median_input'])}</td><td>{_fmt(r['median_output'])}</td>"
        f"<td>{_fmt(r['median_cache_read'])}</td><td>{_fmt(r['median_cost'], 'usd')}</td><td>{e(r['note'])}</td></tr>" for r in rows)
    page = f"""<!doctype html><meta charset=utf-8><title>keelyard arena: {e(data['task']['name'])}</title>
<style>body{{font:14px/1.5 system-ui;margin:40px auto;max-width:980px;color:#1d1d1b;background:#f6f5f2}}
table{{border-collapse:collapse;width:100%;background:#fff}}td,th{{padding:6px 8px;border-bottom:1px solid #e4e2dc;text-align:left}}
.muted{{color:#6b6a65}}</style>
<h1>{e(data['task']['name'])}</h1><p class=muted>{e(data['task']['prompt'])}<br>check: <code>{e(data['task']['check'])}</code> · {e(data['generated'])}</p>
<h2>Median tokens per run</h2>{svg}
<h2>Results</h2><table><tr><th>agent</th><th>model</th><th>runs</th><th>pass</th><th>time</th><th>input</th><th>output</th><th>cache read</th><th>cost</th><th>note</th></tr>{trs}</table>
<p class=muted>Tokens and cost are what each agent reported about itself; "n/a" means it reported nothing. Raw data: results.json.</p>"""
    (out_dir / "report.html").write_text(page)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 0.6 + 0.5 * len(rows)))
        labels = [f"{r['agent']} ({_fmt(r['pass_rate'], 'pct')} pass)" for r in rows]
        ax.barh(labels, [(r["median_input"] or 0) + (r["median_output"] or 0) for r in rows],
                color=["#2f6f4f" if r["pass_rate"] >= .5 else "#a3402f" for r in rows])
        ax.set_xlabel("median tokens per run (input + output)")
        ax.set_title(data["task"]["name"])
        fig.tight_layout()
        fig.savefig(out_dir / "chart.png", dpi=150)
        plt.close(fig)
    except ImportError:
        pass
    return out_dir / "report.html"
