"""Head-to-head: raw output vs keelyard filters vs rtk, on the same real commands.

Two numbers per command:
  tokens    = approx tokens (chars/4) the agent would read
  retention = share of "facts" from the raw output still present after filtering
              (changed paths, failing test ids, assertion lines, grep hits, lint codes...)
A filter that saves tokens by dropping facts the agent needs is not a win.

Usage: python bench/vs_rtk.py --rtk /path/to/rtk --django /path/to/django-clone
The script prepares its own scratch repos under a temp dir and never touches yours.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from keelyard.filters import filter_output
from keelyard.saver import ANSI, approx_tokens

ENV = {k: v for k, v in os.environ.items() if k not in ("FORCE_COLOR", "CLICOLOR_FORCE")} | {"NO_COLOR": "1"}


def sh(cmd: str, cwd: Path) -> str:
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, env=ENV)
    return p.stdout + p.stderr


# ----------------------------------------------------------------- facts
def facts_status(raw_cwd: Path) -> list[tuple[str, ...]]:
    return [(ln[3:].strip().split(" -> ")[-1].rstrip("/").split("/")[-1],)
            for ln in sh("git status --porcelain", raw_cwd).splitlines() if ln.strip()]


def facts_log(raw: str) -> list[tuple[str, ...]]:
    """Commit subject lines (first message line after the Date header)."""
    out, want = [], False
    for ln in raw.splitlines():
        if ln.startswith("Date:"):
            want = True
        elif want and ln.startswith("    ") and ln.strip():
            out.append((ln.strip()[:40],))
            want = False
    return out


def facts_diff(raw: str) -> list[tuple[str, ...]]:
    out = []
    for ln in raw.splitlines():
        if ln.startswith("diff --git"):
            out.append((ln.split(" b/")[-1].split("/")[-1],))
        elif ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")) and len(ln.strip()) > 3:
            out.append((ln[1:].strip()[:50],))
    return out


def facts_grep(raw: str) -> list[tuple[str, ...]]:
    out = []
    for ln in raw.splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", ln)
        if m:
            out.append((m.group(1).split("/")[-1], m.group(3).strip()[:40]))
    return out


def facts_find(raw: str) -> list[tuple[str, ...]]:
    return [(ln.strip().split("/")[-1],) for ln in raw.splitlines() if ln.strip()]


def facts_ruff(raw: str) -> list[tuple[str, ...]]:
    """(file, line, rule) for every violation, from ruff's concise or full output format."""
    out = [(m.group(1).split("/")[-1], m.group(2), m.group(4))
           for m in re.finditer(r"^(.+?):(\d+):(\d+): ([A-Z]+\d+)", raw, re.M)]
    out += [(m.group(2).split("/")[-1], m.group(3), m.group(1))
            for m in re.finditer(r"^([A-Z]+\d+) .*\n\s*--> (.+?):(\d+):\d+", raw, re.M)]
    return out


def facts_pytest(raw: str) -> list[tuple[str, ...]]:
    out = [(m,) for m in sorted(set(re.findall(r"(test_\w+\[\d+\])", raw)))
           if re.search(rf"FAILED .*{re.escape(m)}", raw)]
    out += [(ln[1:].strip()[:60],) for ln in raw.splitlines() if ln.startswith("E ") and len(ln) > 4]
    return list(dict.fromkeys(out))


def facts_cargo(raw: str) -> list[tuple[str, ...]]:
    out = [(m,) for m in re.findall(r"^test (\S+) \.\.\. FAILED", raw, re.M)]
    out += [(m.strip()[:60],) for m in re.findall(r"panicked at .*?:\n(.*)", raw)]
    out += [(ln.strip(),) for ln in raw.splitlines() if re.match(r"^\s*(left|right): ", ln)]
    return list(dict.fromkeys(out))


def retention(facts, text: str) -> float | None:
    if not facts:
        return None
    return sum(all(part in text for part in f) for f in facts) / len(facts)


# ----------------------------------------------------------------- scenarios
def prepare(tmp: Path, django: Path, history: Path) -> dict[str, Path]:
    dj = tmp / "django"
    subprocess.run(["git", "clone", "-q", "--depth", "60", f"file://{django}", str(dj)], check=True)
    for i, f in enumerate(["django/utils/text.py", "django/utils/html.py", "django/db/models/query.py",
                           "django/http/response.py", "django/core/cache/backends/base.py"]):
        p = dj / f
        p.write_text(p.read_text().replace("\n\n\n", f"\n\n\n# edited {i}\n", 2))
    (dj / "django/utils/text.py").write_text((dj / "django/utils/text.py").read_text() + "\ndef new_helper(x):\n    return x * 2\n")
    for n in ("notes.md", "scratch.py", "tmp_data.json"):
        (dj / n).write_text("x\n")
    (dj / "django/utils/crypto.py").unlink()

    py = tmp / "pyproj"
    py.mkdir()
    (py / "test_parse.py").write_text(
        "import json, pytest\n"
        "def parse(s):\n    return json.loads(s)['items']\n"
        "@pytest.mark.parametrize('i', range(120))\ndef test_ok(i):\n    assert parse('{\"items\": [%d]}' % i) == [i]\n"
        "@pytest.mark.parametrize('i', range(4))\ndef test_bad(i):\n    assert parse('{\"item\": [%d]}' % i) == [i]\n"
        "def test_math():\n    assert 2 + 2 == 5, 'arithmetic is broken'\n")

    rs = tmp / "rsproj"
    subprocess.run(["cargo", "new", "-q", "--lib", str(rs)], check=True)
    (rs / "src/lib.rs").write_text(
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n#[cfg(test)]\nmod tests {\n    use super::*;\n"
        + "".join(f"    #[test] fn ok_{i}() {{ assert_eq!(add({i}, 1), {i + 1}); }}\n" for i in range(40))
        + "    #[test] fn bad_sum() { assert_eq!(add(2, 2), 5, \"sum mismatch\"); }\n"
        + "    #[test] fn bad_neg() { assert!(add(-1, 0) > 0, \"negative input\"); }\n}\n")
    subprocess.run(["cargo", "build", "-q", "--tests"], cwd=rs, capture_output=True)
    return {"django": dj, "py": py, "rs": rs, "hist": history}


def scenarios(dirs, ruff: str):
    dj, py, rs = dirs["django"], dirs["py"], dirs["rs"]
    return [
        ("git status", dj, "git status", "git status", lambda raw: facts_status(dj)),
        ("git log -n 40 (requests)", dirs["hist"], "git log -n 40", "git log -n 40", facts_log),
        ("git diff", dj, "git diff", "git diff", facts_diff),
        ("grep -rn (django)", dj, "grep -rn 'def get_queryset' django", "grep -rn 'def get_queryset' django", facts_grep),
        ("find *.py (admin)", dj, "find django/contrib/admin -name '*.py'", "find django/contrib/admin -name '*.py'", facts_find),
        ("ruff check (django/utils)", dj, f"{ruff} check --no-cache --select E,F,W,B,UP --line-length 79 django/utils",
         "ruff check --no-cache --select E,F,W,B,UP --line-length 79 django/utils", facts_ruff),
        ("pytest -v (4 failing of 125)", py, f"{sys.executable} -m pytest -v", "pytest -v", facts_pytest),
        ("cargo test (2 failing of 42)", rs, "cargo test", "cargo test", facts_cargo),
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtk", required=True)
    ap.add_argument("--django", required=True, type=Path)
    ap.add_argument("--history", required=True, type=Path, help="any clone with 40+ commits")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    ruff = shutil.which("ruff") or str(Path(sys.executable).parent / "ruff")
    rtk_env_path = f"{Path(ruff).parent}:{Path(sys.executable).parent}:{os.environ['PATH']}"
    rows = []
    with tempfile.TemporaryDirectory() as t:
        dirs = prepare(Path(t), a.django.resolve(), a.history.resolve())
        for name, cwd, cmd, kcmd, facts_fn in scenarios(dirs, ruff):
            raw = sh(cmd, cwd)
            ky = filter_output(kcmd, raw)
            rt = subprocess.run(f"{a.rtk} {kcmd}", shell=True, cwd=cwd,
                                capture_output=True, text=True, env={**ENV, "PATH": rtk_env_path})
            rtk_out = rt.stdout + rt.stderr
            facts = facts_fn(ANSI.sub('', raw))
            rtk_out = ANSI.sub('', rtk_out)
            rows.append({"command": name, "facts": len(facts), "raw_tokens": approx_tokens(raw),
                         "keelyard_tokens": approx_tokens(ky), "rtk_tokens": approx_tokens(rtk_out),
                         "keelyard_retention": retention(facts, ky), "rtk_retention": retention(facts, rtk_out)})
    fmt = lambda v: "n/a" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    print("| command | facts | raw tok | keelyard tok | keelyard kept | rtk tok | rtk kept |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['command']} | {r['facts']} | {r['raw_tokens']:,} | {r['keelyard_tokens']:,} | {fmt(r['keelyard_retention'])} "
              f"| {r['rtk_tokens']:,} | {fmt(r['rtk_retention'])} |")
    tot = {k: sum(r[k] for r in rows) for k in ("raw_tokens", "keelyard_tokens", "rtk_tokens")}
    print(f"| **total** | | {tot['raw_tokens']:,} | {tot['keelyard_tokens']:,} | | {tot['rtk_tokens']:,} | |")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
