"""Measure keelyard's six token-saving mechanisms on local fixture repos. $0: no model, no network, no keys.

Tokens are estimated as characters / 4 (the estimate keelyard uses everywhere). Each mechanism is compared
with the plain baseline an agent would use without keelyard, and a correctness check confirms the agent
still gets the information it needs. Writes bench/mechanisms.json and prints a table.

    python bench/mechanisms.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from keelyard import codemap, config, mcp_server  # noqa: E402
from keelyard.filters import filter_output  # noqa: E402
from keelyard.proof import Proof  # noqa: E402
from keelyard.saver import ReadCache  # noqa: E402
from keelyard.snapshot import Shadow  # noqa: E402
from keelyard.workstate import WorkState  # noqa: E402


def tok(text: str) -> int:
    return round(len(text) / 4)


def git_copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".git", ".venv", ".keelyard", "*.pyc", "site", "dist"))
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    return dst.resolve()  # macOS: /var is /private/var, and the project root is always resolved


def fixtures(tmp: Path) -> dict[str, tuple[Path, list[str]]]:
    import httpx

    return {
        "keelyard": (git_copy(ROOT, tmp / "keelyard"), ["approx_tokens", "Proof", "filter_output", "tree_hash"]),
        "httpx": (git_copy(Path(httpx.__file__).parent, tmp / "httpx"), ["Client", "Response", "build_request", "URL"]),
        "discount": (git_copy(ROOT / "examples/arena/discount/repo", tmp / "discount"), ["total"]),
    }


def def_range(path: Path, line: int) -> tuple[int, int]:
    """Lines of the definition starting at `line`: until the next line at the same or lower indentation."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    ind = len(lines[line - 1]) - len(lines[line - 1].lstrip())
    end = line
    for i in range(line, len(lines)):
        s = lines[i]
        if s.strip() and len(s) - len(s.lstrip()) <= ind:
            break
        end = i + 1
    return line, min(end, line + 80)


# 1 -------------------------------------------------------------- find relevant code
def m1_find(repo: Path, symbols: list[str], cfg) -> dict:
    before = after = 0
    ok = True
    for sym in symbols:
        grep = subprocess.run(["git", "grep", "-n", "-w", sym], cwd=repo, capture_output=True, text=True).stdout
        hits = codemap.find_symbol_ranked(repo, sym)
        best = hits[0].split(":")[0] if hits else None
        # baseline: grep the name, then read the whole file that defines it
        before += tok(grep) + (tok((repo / best).read_text(encoding="utf-8", errors="replace")) if best else 0)
        if not best:
            ok = False
            continue
        line = int(hits[0].split(":")[1])
        start, end = def_range(repo / best, line)
        page = codemap.page(hits, 0, 5)
        rc = ReadCache(cfg, f"m1-{sym}")
        body = rc.read(best, start, end)
        rel = codemap.related(repo, best)
        after += tok(json.dumps(page)) + tok(codemap.outline(repo / best)) + tok(body) + tok(json.dumps(rel))
        ok &= sym in body.splitlines()[0]  # the definition itself is in what the agent read
    return {"before": before, "after": after, "correct": bool(ok),
            "check": "the top-ranked definition's own lines are in the slice read"}


# 2 -------------------------------------------------------------- avoid re-reads
def apply_diff(old: str, diff: str) -> str:
    old_lines, out, i = old.splitlines(), [], 0
    for hunk in re.split(r"^@@", diff, flags=re.M)[1:]:
        start = int(re.match(r" -(\d+)", hunk).group(1)) - 1
        if start < i:  # a hunk header with -0,0
            start = i
        out += old_lines[i:start]
        i = start
        for ln in hunk.splitlines()[1:]:
            if ln.startswith("-"):
                i += 1
            elif ln.startswith(("+", " ")):
                out.append(ln[1:])
                i += ln.startswith(" ")
    return "\n".join(out + old_lines[i:])


def m2_reread(repo: Path, cfg) -> dict:
    files = [f for f in codemap.tracked_files(repo) if f.endswith(".py")]
    files = sorted(files, key=lambda f: -(repo / f).stat().st_size)[:5]
    before = after = 0
    ok = True
    for f in files:
        p = repo / f
        orig = p.read_text(encoding="utf-8")
        rc = ReadCache(cfg, f"m2-{f}")
        first = rc.read(f)
        unchanged = rc.read(f)
        lines = orig.splitlines(True)
        mid = len(lines) // 2
        lines[mid] = lines[mid].rstrip("\n") + "  # edited\n"
        p.write_text("".join(lines), encoding="utf-8")
        changed = rc.read(f)
        forced = rc.read(f, force=True)
        p.write_text(orig, encoding="utf-8")
        full = len(first)
        before += 3 * tok(first)  # read, read again, read after an edit
        after += tok(first) + tok(unchanged) + tok(changed)
        if "diff only" in changed:
            ok &= apply_diff(orig.replace("\r\n", "\n"), changed.split("diff only:\n", 1)[1]) == "".join(lines).rstrip("\n")
        ok &= "# edited" in forced and len(forced) >= full
    return {"before": before, "after": after, "correct": bool(ok),
            "check": "diff applied to the first read reproduces the edited file exactly; force=true returns it all"}


# 3 -------------------------------------------------------------- log compaction
CORPUS_CMDS = {"pytest_mixed": "python -m pytest -q", "pytest_verbose": "python -m pytest", "go_test": "go test -v ./...",
               "cargo_test": "cargo test", "node_test": "node --test", "npm_test": "npm test", "jest_fail": "npx jest",
               "ruff": "ruff check .", "eslint": "eslint .", "python_traceback": "python tb.py"}
KEEP = re.compile(r"(?i)\b(error|fail(ed|ure)?|panicked|traceback|warning)\b|\b\d+ (passed|failed|total)\b|^E\s{2,}|test result:")


PROGRESS = re.compile(r"^(\S+::\S+) (FAILED|ERROR|PASSED|SKIPPED)\s+\[\s*\d+%\]$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[=_]{2,}", "", s)).strip()


def kept_all(raw: str, small: str) -> bool:
    """Every signal line survives; a verbose per-test progress line only needs its test id somewhere."""
    for ln in raw.splitlines():
        m = PROGRESS.match(ln.strip())
        if m:
            if m[2] in ("FAILED", "ERROR") and m[1] not in small:  # pytest -q hides passed/skipped ids too
                return False
        elif KEEP.search(ln) and ln.strip() and _norm(ln[:120]) not in _norm(small):
            return False
    return True


def m3_logs(repo: Path) -> dict:
    """A real verbose test run of the fixture, plus the captured corpus with 300 passing lines in front."""
    runs = []
    if (repo / "tests").is_dir() or list(repo.glob("test_*.py")):
        target = "tests/test_filter_corpus.py" if (repo / "tests/test_filter_corpus.py").exists() else "."
        cmd = [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", target]
        p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env={**__import__("os").environ, "PYTHONPATH": str(repo / "src")})
        runs.append(("python -m pytest -v", p.stdout + p.stderr))
    before = after = 0
    ok = True
    for cmd, raw in runs:
        small = filter_output(cmd, raw)
        before, after = before + tok(raw), after + min(tok(raw), tok(small))
        ok &= kept_all(raw, small)
    return {"before": before, "after": after, "correct": bool(ok), "check": "every error/failure/count line is kept"}


def m3_corpus() -> dict:
    before = after = 0
    ok = True
    pad = "\n".join(f"tests/test_bulk.py::test_p{i} PASSED" for i in range(300))
    for f in sorted((ROOT / "tests/corpus").glob("*.log")):
        if f.stem not in CORPUS_CMDS:
            continue
        raw = (pad + "\n" if "pytest" in f.stem else "") + f.read_text(encoding="utf-8")
        small = filter_output(CORPUS_CMDS[f.stem], raw)
        before, after = before + tok(raw), after + min(tok(raw), tok(small))
        ok &= kept_all(raw, small)
    return {"before": before, "after": after, "correct": bool(ok), "check": "every error/failure/count line is kept"}


def m3_json() -> dict:
    """Pretty JSON from a CLI (`gh search repos --json ...`), compacted losslessly."""
    raw = (ROOT / "tests/corpus/gh_search.json").read_text(encoding="utf-8")
    small = filter_output("gh search repos", raw)
    data = json.loads(raw)
    body = json.loads(small.split("\n", 1)[1])
    rows = [dict(zip(body["columns"], r, strict=True)) for r in body["rows"]] if isinstance(body, dict) else body
    return {"before": tok(raw), "after": tok(small), "correct": rows == data, "check": "decoding the table gives back the exact JSON"}


# 4 -------------------------------------------------------------- paged search
def m4_paging(repo: Path) -> dict:
    names = {"keelyard": "test", "httpx": "request", "discount": "total"}
    name = names.get(repo.name, "test")
    hits = codemap.find_symbol_ranked(repo, name) + [f"use {r}" for r in codemap.references(repo, name)]
    first = codemap.page(hits, 0, 20)
    pages, off = [], 0
    while True:
        pg = codemap.page(hits, off, 20)
        pages += pg["items"]
        if "next_offset" not in pg:
            break
        off = pg["next_offset"]
    every = codemap.page(hits, 0, max(len(hits), 1))  # same response shape, no paging
    return {"before": tok(json.dumps(every)), "after": tok(json.dumps(first)), "correct": pages == hits,
            "check": f"'{name}': {len(hits)} results; walking every page returns all of them in order, none lost",
            "note": "saves only when the answer is on page 1; reading every page costs slightly more than one dump"}


# 5 -------------------------------------------------------------- compact work state
def m5_state(repo: Path, cfg) -> dict:
    sid = "m5"
    files = sorted((f for f in codemap.tracked_files(repo) if f.endswith(".py")), key=lambda f: -(repo / f).stat().st_size)[:3]
    Proof(cfg, sid).add_requirements(["the change keeps every existing test passing", "behaviour is documented"])
    sh = Shadow(cfg)
    sh.snapshot("base", session=sid)
    origs = {}
    for f in files:
        origs[f] = (repo / f).read_text(encoding="utf-8")
        (repo / f).write_text(origs[f] + "\n# touched\n", encoding="utf-8")
    sh.snapshot("Edit", session=sid)
    ws = WorkState(cfg, sid)
    for f in files:
        ws.add("decision", f"keep the public API of {Path(f).name} unchanged", f"{f}:1")
    ws.add("decision", "the suite is the oracle", "cmd: python -m pytest -q")
    ws.add("question", "should the change be configurable?", "")
    state = ws.render(400)
    # baseline after a compaction: re-read the changed files and restate requirements/decisions in prose
    baseline = "\n".join((repo / f).read_text(encoding="utf-8") for f in files) + "\n".join(
        i["text"] for i in ws.load()) + "\n".join(r["text"] for r in Proof(cfg, sid).load().requirements)
    refs_ok = all(ws.check_ref(i["ref"]) is None for i in ws.load() if i["ref"])
    for f, t in origs.items():
        (repo / f).write_text(t, encoding="utf-8")
    covered = all(f in state for f in files) and "#1" in state and "Open questions" in state
    return {"before": tok(baseline), "after": tok(state), "correct": bool(refs_ok and covered),
            "check": "every decision ref resolves to a real file line or command; all changed files and requirements present",
            "note": "baseline is modeled: re-reading the changed files after compaction"}


# 6 -------------------------------------------------------------- tools per task
def m6_tools() -> dict:
    def size(sel):
        names = mcp_server.configure_tools(sel)
        tools = mcp_server.mcp._tool_manager._tools.values()
        return names, mcp_server._schema_size(tools)
    core_names, core = size("core")
    lazy_names, lazy = size("lazy")
    _, every = size("all")
    pool = mcp_server._ALL
    search = mcp_server.tool_search("undo my last edit")
    per_use = tok(json.dumps(search)) + tok(json.dumps({"name": "rewind_to", "arguments": {"step": 3}})) + 20
    reachable = all(mcp_server.tool_search(n.replace("_", " "))["tools"] for n in core_names if n not in lazy_names)
    mcp_server.configure_tools("core")
    return {"before": core, "after": lazy, "all_tools": every, "correct": bool(reachable and pool),
            "check": "every core tool hidden by lazy mode is found by tool_search",
            "note": f"schemas stay in context for the whole session, and so does each search result: one on-demand use "
                    f"costs about {per_use} tokens (search + call), so lazy is smaller while a session uses fewer than "
                    f"{(core - lazy) // max(per_use, 1)} distinct hidden tools",
            "break_even_uses": (core - lazy) // max(per_use, 1)}


def main() -> None:
    import os

    saved_root = os.environ.get("KEELYARD_ROOT")
    try:
        _main()
    finally:
        if saved_root is None:
            os.environ.pop("KEELYARD_ROOT", None)
        else:
            os.environ["KEELYARD_ROOT"] = saved_root


def _main() -> None:
    results: dict = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, (repo, syms) in fixtures(tmp).items():
            import os

            os.environ["KEELYARD_ROOT"] = str(repo)
            cfg = config.load(repo)
            results[name] = {"1 find code": m1_find(repo, syms, cfg), "2 re-reads": m2_reread(repo, cfg),
                             "3 logs (real run)": m3_logs(repo), "4 paging": m4_paging(repo), "5 work state": m5_state(repo, cfg)}
    results["corpus"] = {"3 logs (corpus)": m3_corpus(), "3 JSON output": m3_json()}
    results["mcp"] = {"6 tools/list": m6_tools()}
    out = ROOT / "bench" / "mechanisms.json"
    out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(f"{'fixture':10} {'mechanism':20} {'before':>8} {'after':>8} {'saved':>7}  correct")
    for fx, ms in results.items():
        for m, r in ms.items():
            if not r["before"]:
                continue
            saved = 100 * (r["before"] - r["after"]) / r["before"]
            print(f"{fx:10} {m:20} {r['before']:>8} {r['after']:>8} {saved:>6.0f}%  {r['correct']}")


if __name__ == "__main__":
    main()
