"""Unified memory across Claude Code, Codex and OpenCode sessions.

Transcripts are read from the agents' own local stores, secrets are redacted,
and the text is indexed in a local SQLite FTS5 database. Retrieval returns
short snippets under a character budget, so recalling a past fix costs a few
hundred tokens instead of re-reading a whole transcript.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .config import data_home
from .redact import redact

CHUNK = 1200
TOOL_KEEP = 400


@dataclass
class Turn:
    agent: str
    session: str
    project: str
    ts: str
    role: str
    text: str


def _flatten(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        t = part.get("type")
        if t in ("text", "input_text", "output_text"):
            out.append(part.get("text", ""))
        elif t == "tool_use":
            out.append(f"[tool {part.get('name')}] {json.dumps(part.get('input'))[:TOOL_KEEP]}")
        elif t == "tool_result":
            out.append(f"[result] {_flatten(part.get('content'))[:TOOL_KEEP]}")
    return "\n".join(x for x in out if x)


# --------------------------------------------------------------------------- readers
def read_claude(path: Path) -> Iterator[Turn]:
    for line in path.read_text(errors="replace", encoding="utf-8").splitlines():
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        if j.get("type") not in ("user", "assistant") or not isinstance(j.get("message"), dict):
            continue
        text = _flatten(j["message"].get("content"))
        if text.strip():
            yield Turn("claude-code", j.get("sessionId", path.stem), j.get("cwd", ""), j.get("timestamp", ""),
                       j["message"].get("role", j["type"]), text)


def read_codex(path: Path) -> Iterator[Turn]:
    session, cwd = path.stem, ""
    for line in path.read_text(errors="replace", encoding="utf-8").splitlines():
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        p = j.get("payload") or {}
        if j.get("type") == "session_meta":
            session, cwd = p.get("id", session), p.get("cwd", cwd)
            continue
        if j.get("type") != "response_item":
            continue
        if p.get("type") == "message":
            text = _flatten(p.get("content"))
            if text.strip() and not text.lstrip().startswith("<environment_context>"):
                yield Turn("codex", session, cwd, j.get("timestamp", ""), p.get("role", ""), text)
        elif p.get("type") == "function_call":
            yield Turn("codex", session, cwd, j.get("timestamp", ""), "tool",
                       f"[tool {p.get('name')}] {str(p.get('arguments'))[:TOOL_KEEP]}")
        elif p.get("type") == "function_call_output":
            out = p.get("output")
            out = out if isinstance(out, str) else json.dumps(out)
            yield Turn("codex", session, cwd, j.get("timestamp", ""), "tool", f"[result] {out[:TOOL_KEEP]}")


def read_opencode(storage: Path) -> Iterator[Turn]:
    sessions = {}
    for f in (storage / "session").glob("*/*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            sessions[s["id"]] = s.get("directory", "")
        except (json.JSONDecodeError, KeyError):
            continue
    for mdir in (storage / "message").glob("*"):
        sid = mdir.name
        for mf in sorted(mdir.glob("*.json")):
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            texts = []
            for pf in sorted((storage / "part" / m.get("id", mf.stem)).glob("*.json")):
                try:
                    part = json.loads(pf.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                if part.get("type") == "text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "tool":
                    st = part.get("state") or {}
                    texts.append(f"[tool {part.get('tool')}] {json.dumps(st.get('input'))[:TOOL_KEEP]}")
                    if st.get("output"):
                        texts.append(f"[result] {str(st['output'])[:TOOL_KEEP]}")
            text = "\n".join(t for t in texts if t)
            if text.strip():
                ts = str((m.get("time") or {}).get("created", ""))
                yield Turn("opencode", sid, sessions.get(sid, ""), ts, m.get("role", ""), text)


def _norm_project(project: str) -> str:
    """Resolved, forward-slash form, so /var vs /private/var and C:\\x vs C:/x compare equal."""
    if project and (os.path.isabs(project) or project.startswith("/")):
        return os.path.realpath(project).replace("\\", "/")
    return project


def default_sources() -> list[tuple[str, Path]]:
    home = Path.home()
    xdg = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    return [("claude-code", claude_dir / "projects"), ("codex", codex_home / "sessions"),
            ("opencode", xdg / "opencode" / "storage")]


# --------------------------------------------------------------------------- store
class Memory:
    def __init__(self, db: Path | None = None):
        self.db_path = db or Path(os.environ.get("KEELYARD_MEMORY_DB") or data_home() / "memory.db")
        self.db = sqlite3.connect(self.db_path)
        os.chmod(self.db_path, 0o600)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, agent TEXT, session TEXT,
                project TEXT, ts TEXT, role TEXT, text TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(text, project, content='chunks', content_rowid='id',
                tokenize='porter unicode61');
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO fts(rowid, text, project) VALUES (new.id, new.text, new.project); END;
            CREATE TABLE IF NOT EXISTS sources(path TEXT PRIMARY KEY, sig TEXT);
            """
        )

    def _add(self, t: Turn) -> int:
        text = redact(t.text)
        project = _norm_project(t.project)
        n = 0
        for i in range(0, len(text), CHUNK):
            piece = text[i:i + CHUNK]
            h = hashlib.sha256(f"{t.agent}|{t.session}|{t.role}|{piece}".encode()).hexdigest()
            cur = self.db.execute(
                "INSERT OR IGNORE INTO chunks(hash,agent,session,project,ts,role,text) VALUES (?,?,?,?,?,?,?)",
                (h, t.agent, t.session, project, t.ts, t.role, piece))
            n += cur.rowcount
        return n

    def _changed(self, path: Path) -> bool:
        st = path.stat()
        sig = f"{st.st_size}:{st.st_mtime_ns}"
        row = self.db.execute("SELECT sig FROM sources WHERE path=?", (str(path),)).fetchone()
        if row and row[0] == sig:
            return False
        self.db.execute("INSERT OR REPLACE INTO sources VALUES (?,?)", (str(path), sig))
        return True

    def ingest(self, sources: list[tuple[str, Path]] | None = None) -> dict[str, int]:
        stats: dict[str, int] = {}
        for agent, base in sources or default_sources():
            if not base.exists():
                continue
            added = 0
            if agent == "claude-code":
                for f in base.glob("*/*.jsonl"):
                    if self._changed(f):
                        added += sum(self._add(t) for t in read_claude(f))
            elif agent == "codex":
                for f in base.rglob("*.jsonl"):
                    if self._changed(f):
                        added += sum(self._add(t) for t in read_codex(f))
            elif agent == "opencode":
                added += sum(self._add(t) for t in read_opencode(base))
            stats[agent] = added
        self.db.commit()
        return stats

    def search(self, query: str, project: str | None = None, budget_chars: int = 2400, limit: int = 8) -> list[dict]:
        words = re.findall(r"\w+", query.lower())
        if not words:
            return []
        fts_q = " OR ".join(f'"{w}"' for w in words[:16])
        sql = ("SELECT c.agent, c.session, c.project, c.ts, c.role, snippet(fts, 0, '', '', ' … ', 40) "
               "FROM fts JOIN chunks c ON c.id = fts.rowid WHERE fts MATCH ?")
        args: list = [fts_q]
        if project:
            # exact folder or a subfolder ('/shop' must not match '/shop2'); also the resolved
            # path, since macOS logs /private/var for /var
            clauses = []
            for cand in dict.fromkeys([project.replace("\\", "/").rstrip("/"), _norm_project(project).rstrip("/")]):
                esc = cand.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                clauses.append("c.project = ? OR c.project LIKE ? ESCAPE '\\'")
                args += [cand, esc + "/%"]
            sql += " AND (" + " OR ".join(clauses) + ")"
        sql += " ORDER BY bm25(fts) LIMIT ?"
        args.append(limit * 3)
        out, used = [], 0
        for agent, session, proj, ts, role, snip in self.db.execute(sql, args):
            if used + len(snip) > budget_chars or len(out) >= limit:
                break
            out.append({"agent": agent, "session": session, "project": proj, "ts": ts, "role": role, "snippet": snip})
            used += len(snip)
        return out

    def stats(self) -> dict:
        rows = self.db.execute("SELECT agent, count(*), count(distinct session) FROM chunks GROUP BY agent").fetchall()
        return {a: {"chunks": c, "sessions": s} for a, c, s in rows}

    def session_text(self, session: str) -> str:
        return "\n".join(r[0] for r in self.db.execute("SELECT text FROM chunks WHERE session=? ORDER BY id", (session,)))


def format_hits(hits: list[dict]) -> str:
    if not hits:
        return "No matching memory."
    return "\n".join(f"- [{h['agent']} {h['ts'][:10]} {Path(h['project']).name or '?'} {h['role']}] {h['snippet']}"
                     for h in hits)


def now() -> float:
    return time.time()
