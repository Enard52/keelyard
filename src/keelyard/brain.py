"""keelyard in the agent's working memory: a brief at session start, recall per prompt, short nudges.

Everything here is advisory text for the model, with a hard token budget. Nothing blocks except the
existing repeat-read deny, which now hands back the outline or diff instead of a bare "no".
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .config import Config
from .saver import approx_tokens

RULES = (
    "keelyard is active. Edits are snapshotted (rewind_list, rewind_to). Before done: proof_run_tests(phase=\"after\") "
    "and proof_check each item. Find code with find_symbol + read_file ranges. Guides: workflow(\"plan\"|\"debug\"|\"review\")."
)


def _cap(text: str, tokens: int) -> str:
    """Trim text to about `tokens` tokens on a line boundary."""
    limit = max(0, tokens) * 4
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit("\n", 1)[0]
    return cut + "\n…"


# --------------------------------------------------------------------------- brief
def brief(cfg: Config, session: str, budget_tokens: int | None = None, query: str = "", lean: bool = False) -> str:
    """Rules, open proof items, a project map digest and recent memory, in that priority, within budget."""
    from .codemap import project_map
    from .proof import Proof

    budget = int(budget_tokens if budget_tokens is not None else cfg.section("brain")["brief_tokens"])
    parts: list[str] = [] if lean else [RULES]  # lean: the AGENTS.md block already carries the rules
    from .workstate import WorkState

    try:
        ws = WorkState(cfg, session)
        state = ws.render(max(80, budget // 3)) if (ws.load() or ws.changes(1)) else ""
    except Exception:  # noqa: BLE001
        state = ""
    if state:
        parts.append(state)  # includes the requirements, so the proof items below would repeat them
    try:
        b = Proof(cfg, session).load()
        if state:
            raise LookupError
        open_items = [f"#{r['id']} {r['text']}" for r in b.requirements if not r["done"]]
        if open_items:
            parts.append("Open proof items:\n- " + "\n- ".join(open_items[:8]))
        elif b.task and not lean:
            parts.append(f"Current task: {b.task[:200]}")
    except Exception:  # noqa: BLE001 - a broken bundle must not hide the brief (LookupError: already in the state)
        pass
    hits = recall(cfg, query or "", budget_tokens=max(60, budget // 5), exclude_session=session) if query else ""
    if hits:
        parts.append(hits)
    try:
        parts.append("Project map:\n" + project_map(cfg.root, max_dirs=12))
    except Exception:  # noqa: BLE001
        pass
    out, used = [], 0
    for p in parts:  # highest priority first; the last part is trimmed to fit, nothing after it
        t = approx_tokens(p)
        if used + t <= budget:
            out.append(p)
            used += t
        else:
            rest = budget - used
            if rest > 40:
                out.append(_cap(p, rest))
            break
    inline = inline_files(cfg, int(cfg.section("brain").get("inline_files_tokens", 0) or 0))
    return "\n\n".join(out + ([inline] if inline else []))


SOURCE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java", ".kt", ".cs", ".php", ".c", ".h",
              ".cpp", ".hpp", ".swift", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml", ".md", ".txt", ".sh"}


def inline_files(cfg: Config, budget: int) -> str:
    """Full text of the smallest project files, smallest first, within budget: the agent can skip read calls."""
    if budget <= 0:
        return ""
    from .codemap import AGENT_FILES, tracked_files

    files = []
    for rel in tracked_files(cfg.root):
        p = cfg.root / rel
        if rel.split("/")[0] in AGENT_FILES or p.suffix not in SOURCE_EXT or rel.startswith(".git"):
            continue
        try:
            files.append((p.stat().st_size, rel))
        except OSError:
            continue
    out, used = [], 0
    for _, rel in sorted(files):
        try:
            text = (cfg.root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        t = approx_tokens(text) + 8
        if used + t > budget:
            break
        out.append(f"--- {rel}\n{text.rstrip()}")
        used += t
    if not out:
        return ""
    return "Project files (current text; no need to read them again):\n" + "\n".join(out)


# --------------------------------------------------------------------------- recall
STOP = set("the a an and or to of in on for with is are be this that it as at by from fix add make please can you "
           "i we me my our should would could will just now then also use using do does".split())


def keywords(text: str, n: int = 10) -> str:
    words = [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower()) if w not in STOP]
    seen: dict[str, None] = {}
    for w in words:
        seen.setdefault(w)
    return " ".join(list(seen)[:n])


def recall(cfg: Config, prompt: str, budget_tokens: int | None = None, exclude_session: str = "",
           db: Path | None = None) -> str:
    """Top past-session snippets for this project that match the prompt; '' when nothing is relevant."""
    from .config import data_home
    from .memory import Memory

    budget = int(budget_tokens if budget_tokens is not None else cfg.section("brain")["recall_tokens"])
    q = keywords(prompt)
    path = Path(db or os.environ.get("KEELYARD_MEMORY_DB") or data_home() / "memory.db")
    if not q or budget <= 0 or not path.exists():
        return ""
    try:
        m = Memory(path)
        hits = [h for h in m.search(q, project=str(cfg.root), budget_chars=budget * 4, limit=4)
                if h["session"] != exclude_session]
    except Exception:  # noqa: BLE001 - memory is a bonus, never an error
        return ""
    if not hits:
        return ""
    lines = [f"- {h['ts'][:10]} {h['agent']}: {h['snippet'].strip()}" for h in hits]
    return _cap("From earlier sessions in this project (keelyard memory):\n" + "\n".join(lines), budget)


# --------------------------------------------------------------------------- nudges
DESTRUCTIVE = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*[rR]|--recursive\s+--force|-r\s+-f|-f\s+-r)\b"), "rm -rf"),
    (re.compile(r"\bRemove-Item\b.*-Recurse", re.I), "Remove-Item -Recurse"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"), "git clean -f"),
    (re.compile(r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)"), "git checkout ."),
    (re.compile(r"\bgit\s+push\b.*(--force|-f\b)"), "git push --force"),
    (re.compile(r"\b(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE?)\b", re.I), "DROP/TRUNCATE"),
    (re.compile(r"\bDELETE\s+FROM\s+\w+\s*(;|$|\")", re.I), "DELETE without WHERE"),
    (re.compile(r"\b(alembic\s+downgrade|manage\.py\s+(migrate|flush)|prisma\s+migrate\s+(reset|dev)|"
                r"rails\s+db:(drop|reset|migrate)|rake\s+db:(drop|reset|migrate)|knex\s+migrate|sequelize\s+db:migrate)"),
     "database migration"),
]


QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
RUNS_ITS_ARGS = re.compile(r"\b(bash|sh|zsh|pwsh|powershell|cmd)(\.exe)?\s+(-c|/c|-Command)\b|\beval\b|\bssh\b|\bxargs\b", re.I)
SQL_CLIENT = re.compile(r"\b(psql|mysql|mariadb|sqlite3|sqlcmd|duckdb|clickhouse-client|cockroach\s+sql|dbshell)\b|\.sql\b", re.I)


def destructive(cmd: str) -> str | None:
    """Name of the destructive operation in a shell command, or None.

    Text inside quotes is data (`git commit -m "drop table"`, `echo 'rm -rf /'`) unless the command runs its
    arguments (`bash -c`, `eval`, `ssh`). SQL is only flagged when a SQL client or a .sql file is involved."""
    cmd = cmd or ""
    bare = cmd if RUNS_ITS_ARGS.search(cmd) else QUOTED.sub("''", cmd)
    for rx, name in DESTRUCTIVE:
        if name in ("DROP/TRUNCATE", "DELETE without WHERE"):
            if SQL_CLIENT.search(cmd) and rx.search(cmd):
                return name
        elif rx.search(bare):
            return name
    return None


CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".rb", ".java", ".kt", ".php", ".cs", ".swift", ".c", ".cpp"}


def has_tests_nearby(root: Path, rel: str) -> bool:
    """True if `rel` is a test, or a test file for it exists by common naming conventions."""
    p = Path(rel)
    stem, ext = p.stem, p.suffix
    if ext not in CODE_EXT:
        return True  # docs, config, data: no nudge
    low = rel.lower().replace("\\", "/")
    if re.search(r"(^|/)(tests?|spec|__tests__)/", low) or re.search(r"(^test_|_test$|\.test$|\.spec$|tests?$)", stem.lower()):
        return True
    names = {f"test_{stem}{ext}", f"{stem}_test{ext}", f"{stem}.test{ext}", f"{stem}.spec{ext}", f"{stem}Test{ext}",
             f"{stem}_spec{ext}"}
    if ext in (".ts", ".tsx", ".js", ".jsx"):
        names |= {f"{stem}.test{e}" for e in (".ts", ".tsx", ".js", ".jsx")}
    if ext == ".go":
        return (root / p.parent / f"{stem}_test.go").exists()
    if ext == ".rs":
        try:
            if "#[cfg(test)]" in (root / p).read_text(errors="replace", encoding="utf-8"):
                return True
        except OSError:
            pass
    from .codemap import tracked_files

    try:
        files = tracked_files(root)
    except Exception:  # noqa: BLE001
        files = []
    return any(Path(f).name in names for f in files)


class Nudger:
    """Rate limit per kind (cooldown) and per session (cap). State lives in .keelyard/nudges.json."""

    def __init__(self, cfg: Config, session: str):
        self.cfg, self.session = cfg, session
        self.opts = cfg.section("brain")
        self.path = cfg.state / "nudges.json"

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if d.get("session") == self.session else {"session": self.session, "count": 0, "last": {}}
        except (OSError, ValueError):
            return {"session": self.session, "count": 0, "last": {}}

    def allow(self, kind: str, key: str = "") -> bool:
        if not self.opts.get("nudges", True):
            return False
        d = self._load()
        k = f"{kind}:{key}"
        now = time.time()
        if d["count"] >= int(self.opts["max_nudges_per_session"]):
            return False
        if now - d["last"].get(k, 0) < float(self.opts["nudge_cooldown_s"]):
            return False
        d["count"] += 1
        d["last"][k] = now
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, self.path)
        return True


def session_tokens(payload: dict) -> int:
    """Rough session size: the transcript file Claude Code / Codex pass, at ~4 chars per token."""
    t = payload.get("transcript_path")
    if not t:
        return 0
    try:
        return Path(t).stat().st_size // 4 // 3  # JSONL carries ~3x overhead (metadata, escaping)
    except OSError:
        return 0


def budget_nudge(cfg: Config, payload: dict) -> str | None:
    o = cfg.section("brain")
    plan = int(o.get("plan_tokens") or 0)
    if plan <= 0:
        return None
    used = session_tokens(payload)
    if used < plan * float(o["budget_warn_at"]):
        return None
    return (f"keelyard: this session is at ~{used:,} of {plan:,} tokens. Hand bulk reading, summarising and "
            "drafting to helpers (swarm tool, or your own subagents) and keep this context for decisions.")
