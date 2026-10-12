"""Structure-first reading: outlines, a project map and symbol lookup.

Same goal as repomix --compress (MIT) and the "signatures only" modes in rtk and
claude-context-optimizer: let the agent see the shape of code before paying for
the bodies. Independent implementation: Python uses the stdlib ast module, other
languages use line-anchored definition patterns. Every entry carries path:line so
the agent can read exactly the range it needs.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from collections import OrderedDict
from pathlib import Path

from .config import VENDOR_DIRS
from .saver import approx_tokens

DEF_PATTERNS = {
    ".js": r"^\s*(export\s+)?(default\s+)?(async\s+)?(function\*?\s+\w+|class\s+\w+|(const|let)\s+\w+\s*=\s*(async\s*)?(\(|function))",
    ".ts": r"^\s*(export\s+)?(default\s+)?(abstract\s+)?(async\s+)?(function\*?\s+\w+|class\s+\w+|interface\s+\w+|type\s+\w+\s*=|enum\s+\w+|"
           r"(const|let)\s+\w+\s*(:\s*[^=]+)?=\s*(async\s*)?(\(|function))",
    ".go": r"^(func|type)\s",
    ".rs": r"^\s*(pub(\([^)]*\))?\s+)?(async\s+)?(fn|struct|enum|trait|impl|mod|type)\b",
    ".java": r"^\s*(public|private|protected|static|final|abstract|\s)*(class|interface|enum|record|[\w<>\[\], ]+\s+\w+\s*\()",
    ".rb": r"^\s*(def|class|module)\s",
    ".php": r"^\s*(abstract\s+|final\s+)?(public\s+|private\s+|protected\s+)?(static\s+)?(function|class|interface|trait)\s",
    ".c": r"^[A-Za-z_][\w \*]*\s+\**\w+\s*\([^;]*$",
    ".swift": r"^\s*(public\s+|private\s+|internal\s+)?(func|class|struct|enum|protocol|extension)\s",
    ".kt": r"^\s*(fun|class|interface|object|data class|enum class)\s",
}
ALIASES = {".jsx": ".js", ".mjs": ".js", ".tsx": ".ts", ".h": ".c", ".cc": ".c", ".cpp": ".c", ".hpp": ".c"}


def _py_outline(src: str) -> list[str]:
    tree = ast.parse(src)
    out: list[str] = []

    def sig(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
        pre = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
        return f"{pre} {fn.name}({ast.unparse(fn.args)}){ret}"

    def doc(node) -> str:
        d = ast.get_docstring(node)
        return f"  # {d.strip().splitlines()[0][:90]}" if d else ""

    def walk(body, indent: str) -> None:
        for n in body:
            if isinstance(n, ast.ClassDef):
                bases = ", ".join(ast.unparse(b) for b in n.bases)
                out.append(f"{n.lineno:>5} {indent}class {n.name}" + (f"({bases})" if bases else "") + doc(n))
                walk(n.body, indent + "    ")
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                deco = "".join(f"@{ast.unparse(d)} " for d in n.decorator_list)
                out.append(f"{n.lineno:>5} {indent}{deco}{sig(n)}{doc(n)}")
            elif not indent and isinstance(n, (ast.Assign, ast.AnnAssign)) and len(ast.unparse(n)) < 100:
                tgt = ast.unparse(n.targets[0] if isinstance(n, ast.Assign) else n.target)
                if tgt.isupper():
                    out.append(f"{n.lineno:>5} {ast.unparse(n)}")

    walk(tree.body, "")
    return out


MAX_OUTLINE = 400


def outline(path: Path) -> str:
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return f"{path.name}: binary file ({len(data):,} bytes), no outline"
    src = data.decode(errors="replace")
    ext = ALIASES.get(path.suffix, path.suffix)
    lines: list[str]
    if ext == ".py":
        try:
            lines = _py_outline(src)
        except (SyntaxError, ValueError, RecursionError):  # py2 code, null bytes, absurd nesting
            rx = re.compile(r"^\s*(async\s+def|def|class)\s+\w+")
            lines = [f"{i:>5} {ln.rstrip()[:160]}" for i, ln in enumerate(src.splitlines(), 1) if rx.search(ln)]
    else:
        pat = DEF_PATTERNS.get(ext)
        if not pat:
            return f"(no outline rules for {path.suffix}; {len(src.splitlines())} lines)"
        rx = re.compile(pat)
        lines = [f"{i:>5} {ln.rstrip()[:160]}" for i, ln in enumerate(src.splitlines(), 1) if rx.search(ln)]
    if len(lines) > MAX_OUTLINE:
        lines = lines[:MAX_OUTLINE] + [f"  ... {len(lines) - MAX_OUTLINE} more definitions (use find_symbol)"]
    head = f"{path.name}: {len(src.splitlines())} lines, ~{approx_tokens(src)} tokens; outline ~{approx_tokens(chr(10).join(lines))}"
    return head + "\n" + "\n".join(lines)


def tracked_files(root: Path) -> list[str]:
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "-co", "--exclude-standard", "-z"],
                           cwd=root, capture_output=True)
        ok = p.returncode == 0
    except FileNotFoundError:  # git not installed
        ok = False
    if ok:
        files = [f for f in p.stdout.decode("utf-8", "surrogateescape").split("\0") if f]
    else:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in VENDOR_DIRS and not d.startswith("."))
            rel = Path(dirpath).relative_to(root)
            files += [(rel / n).as_posix() for n in sorted(filenames)]
    return [f for f in files if not f.startswith(".keelyard/") and not f.endswith("/")]


def project_map(root: Path, max_dirs: int = 60) -> str:
    dirs: dict[str, list[tuple[str, int]]] = OrderedDict()
    total = 0
    for rel in sorted(tracked_files(root)):
        p = root / rel
        try:
            size = p.stat().st_size
        except OSError:
            continue
        total += size
        d, _, name = rel.rpartition("/")
        dirs.setdefault(d or ".", []).append((name, size))
    out = [f"{sum(len(v) for v in dirs.values())} files, ~{total // 4} tokens if read in full"]
    for d, files in list(dirs.items())[:max_dirs]:
        files.sort(key=lambda x: -x[1])
        big = ", ".join(f"{n} ~{s // 4}t" for n, s in files[:6])
        out.append(f"{d}/ ({len(files)}): {big}" + (" …" if len(files) > 6 else ""))
    if len(dirs) > max_dirs:
        out.append(f"… {len(dirs) - max_dirs} more dirs")
    return "\n".join(out)


def find_symbol(root: Path, name: str, limit: int = 20) -> str:
    if not re.fullmatch(r"[A-Za-z_][\w.]*", name):
        return "symbol must be an identifier"
    short = name.split(".")[-1]
    defs = re.compile(rf"^\s*(export\s+)?(default\s+)?(pub(\([^)]*\))?\s+)?(async\s+)?"
                      rf"(def|class|function\*?|fn|func|struct|enum|trait|interface|type|const|let|var|module)\s+(\([^)]*\)\s*)?{re.escape(short)}\b")
    hits = []
    for rel in tracked_files(root):
        p = root / rel
        if p.suffix not in (".py", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".java", ".c", ".h", ".cpp") and \
                ALIASES.get(p.suffix, p.suffix) not in (".js", ".ts"):
            continue
        try:
            for i, ln in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if short in ln and defs.search(ln):
                    hits.append(f"{rel}:{i}: {ln.strip()[:160]}")
                    if len(hits) >= limit:
                        return "\n".join(hits)
        except OSError:
            continue
    return "\n".join(hits) or f"no definition of {name} found"
