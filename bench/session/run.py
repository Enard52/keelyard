"""Real OpenCode sessions, with and without keelyard, on many task types. $0: free OpenCode Zen model by default.

For every (task, setup, rep): build a fresh repo, run `opencode run` once, export the session, count tokens from
OpenCode's own accounting (input + cache read + cache write + output + reasoning: everything the model processed,
keelyard's brief and hints included), and run the task's hidden check. Results are appended to a JSONL file as
each run finishes, so an interrupted batch keeps what it did and a rerun skips finished runs.

    python bench/session/run.py --setups baseline,balanced,lean --reps 2 --jobs 3 --out bench/session/runs.jsonl
    python bench/session/report.py bench/session/runs.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tasks import TASKS  # noqa: E402

KEELYARD = shutil.which("keelyard") or str(Path(sys.executable).with_name("keelyard"))
LOCK = threading.Lock()


def tokens(info: dict) -> dict:
    t = info.get("tokens", {})
    c = t.get("cache", {})
    d = {"input": t.get("input", 0), "cache_read": c.get("read", 0), "cache_write": c.get("write", 0),
         "output": t.get("output", 0), "reasoning": t.get("reasoning", 0)}
    d["total"] = sum(d.values())
    return d


def answer_text(export: dict) -> str:
    out = []
    for m in export.get("messages", []):
        if m.get("info", {}).get("role") == "assistant":
            out += [p.get("text", "") for p in m.get("parts", []) if p.get("type") == "text"]
    return "\n".join(out)


def one(task: str, setup: str, rep: int, model: str, timeout: int) -> dict:
    spec = TASKS[task]
    root = Path(tempfile.mkdtemp(prefix=f"ks-{task}-{setup}-"))
    env = {**os.environ, "GIT_AUTHOR_NAME": "b", "GIT_AUTHOR_EMAIL": "b@b", "GIT_COMMITTER_NAME": "b",
           "GIT_COMMITTER_EMAIL": "b@b", "PWD": str(root), "PATH": f"{Path(KEELYARD).parent}{os.pathsep}{os.environ['PATH']}"}
    spec["setup"](root)
    subprocess.run(["git", "init", "-q"], cwd=root, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, env=env)
    subprocess.run(["git", "commit", "-qm", "start"], cwd=root, env=env)
    if setup != "baseline":
        subprocess.run([KEELYARD, "init", "--agent", "opencode", "--preset", setup], cwd=root, env=env,
                       capture_output=True, timeout=300)
    t0 = time.time()
    rec = {"task": task, "setup": setup, "rep": rep, "model": model}
    try:
        p = subprocess.run(["opencode", "run", "--dir", str(root), "--format", "json", "-m", model, spec["prompt"]], cwd=root, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        sid = next((json.loads(line).get("sessionID") for line in p.stdout.splitlines()
                    if line.startswith("{") and '"sessionID"' in line), None)
    except subprocess.TimeoutExpired:
        sid, rec["error"] = None, "timeout"
    rec["seconds"] = round(time.time() - t0)
    if not sid:
        rec.setdefault("error", "no session")
        return rec
    export = None
    for _ in range(3):  # a piped export can be cut off at 64 KB; a file is not
        dump = root / ".export.json"
        with dump.open("w", encoding="utf-8") as fh:
            subprocess.run(["opencode", "export", sid], cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=fh,
                           stderr=subprocess.DEVNULL, timeout=120)
        raw = dump.read_text(encoding="utf-8")
        dump.unlink()
        try:
            export = json.loads(raw[raw.index("{"):])
            break
        except ValueError:
            time.sleep(3)
    if export is None:
        rec["error"] = "export unreadable"
        return rec
    msgs = [m for m in export["messages"] if m.get("info", {}).get("role") == "assistant"]
    ans = answer_text(export)
    tools = [f"{p.get('tool')}: {json.dumps(p.get('state', {}).get('input', {}))[:120]}"
             for m in msgs for p in m.get("parts", []) if p.get("type") == "tool"]
    rec.update(tokens(export["info"]), calls=len(msgs), session=sid, tools=tools, answer=ans[-600:])
    try:
        rec["correct"] = bool(spec["check"](root, ans))
    except Exception as e:  # a crashing check is a failed run, not a crashed batch
        rec["correct"], rec["check_error"] = False, repr(e)[:200]
    shutil.rmtree(root, ignore_errors=True)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--setups", default="baseline,balanced,lean")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--model", default="opencode/big-pickle")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default=str(Path(__file__).with_name("runs.jsonl")))
    a = ap.parse_args()
    out = Path(a.out)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if "total" in r:
                done.add((r["task"], r["setup"], r["rep"], r["model"]))
    jobs = [(t, s, k) for k in range(1, a.reps + 1) for t in a.tasks.split(",") for s in a.setups.split(",")
            if (t, s, k, a.model) not in done]
    print(f"{len(jobs)} runs to do ({len(done)} already done)", flush=True)

    def go(j):
        try:
            r = one(*j, a.model, a.timeout)
        except Exception as e:  # one broken run must not end the batch
            r = {"task": j[0], "setup": j[1], "rep": j[2], "model": a.model, "error": repr(e)[:200]}
        with LOCK, out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r) + "\n")
        print(f"{r['task']:17} {r['setup']:9} rep {r['rep']}  total {r.get('total', '-'):>7}  calls {r.get('calls', '-')}"
              f"  correct {r.get('correct', '-')}  {r.get('error', '')}", flush=True)

    with ThreadPoolExecutor(a.jobs) as ex:
        list(ex.map(go, jobs))


if __name__ == "__main__":
    main()
