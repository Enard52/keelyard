"""Helper swarm: fan cheap subtasks out to many small-model workers, then verify them.

The main (expensive) agent stays the planner and the judge. Workers only read,
summarise, search and draft. Nothing a worker returns is applied automatically:
drafts come back as patches that were checked with `git apply --check`, and
claims about the code must cite file:line references that keelyard verifies.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import Config
from .redact import redact

MAX_FILE_CHARS = 24000
CITE = re.compile(r"([\w./\-]+\.[A-Za-z0-9]+):(\d+)(?:-(\d+))?")
QUOTE = re.compile(r"`([^`\n]{6,120})`")

SYSTEM = (
    "You are a precise helper for a coding agent. Answer only from the files given. "
    "Cite every claim as path:line. Quote code in backticks exactly as it appears. "
    "If the files do not answer the question, say so. Be brief. "
    "Write citations as <path>:<line> using the paths shown in the === headers."
)
DRAFT_SYSTEM = (
    "You write minimal unified diffs (git format, paths prefixed a/ and b/) for the requested change, "
    "using only the files given. Output only the diff inside one ```diff block."
)


@dataclass
class Task:
    kind: str  # ask | summarize | draft_edit | grep | run
    prompt: str = ""
    files: list[str] = field(default_factory=list)
    id: int = 0


@dataclass
class Result:
    id: int
    kind: str
    ok: bool
    verified: bool
    output: str
    notes: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


# --------------------------------------------------------------------------- providers
async def complete(client: httpx.AsyncClient, model: dict[str, Any], system: str, user: str) -> tuple[str, int, int]:
    key = os.environ.get(model.get("api_key_env") or "", "")
    if model["provider"] == "anthropic":
        r = await client.post(
            model["base_url"].rstrip("/") + "/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": model["model"], "max_tokens": model.get("max_tokens", 1500), "system": system,
                  "messages": [{"role": "user", "content": user}]},
        )
        r.raise_for_status()
        j = r.json()
        text = "".join(b.get("text", "") for b in j.get("content", []))
        u = j.get("usage", {})
        return text, u.get("input_tokens", 0), u.get("output_tokens", 0)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = await client.post(
        model["base_url"].rstrip("/") + "/chat/completions",
        headers=headers,
        json={"model": model["model"], "temperature": 0.1, "max_tokens": model.get("max_tokens", 1500),
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
    )
    r.raise_for_status()
    j = r.json()
    u = j.get("usage", {})
    return j["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


async def _with_retry(fn, attempts: int = 4):
    for i in range(attempts):
        try:
            return await fn()
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (408, 429, 500, 502, 503, 504) or i == attempts - 1:
                raise
        except httpx.TransportError:
            if i == attempts - 1:
                raise
        await asyncio.sleep(min(20, 0.5 * 2 ** i + random.random()))


# --------------------------------------------------------------------------- verification
def _file_lines(root: Path, rel: str) -> list[str] | None:
    p = (root / rel).resolve()
    if root not in p.parents or not p.is_file():
        return None
    return p.read_text(errors="replace").splitlines()


def verify_citations(root: Path, answer: str, files: list[str]) -> tuple[bool, list[str]]:
    notes, good, bad = [], 0, 0
    by_name = {Path(f).name: f for f in files}
    for path, a, b in CITE.findall(answer):
        lines = _file_lines(root, path)
        if lines is None and Path(path).name in by_name:  # models often cite by basename
            lines = _file_lines(root, by_name[Path(path).name])
        lo, hi = int(a), int(b or a)
        if lines is None:
            bad += 1
            notes.append(f"cites missing file {path}")
        elif not (1 <= lo <= hi <= len(lines)):
            bad += 1
            notes.append(f"cites {path}:{lo}-{hi} but file has {len(lines)} lines")
        else:
            good += 1
    corpus = "\n".join("\n".join(_file_lines(root, f) or []) for f in files)
    names = {Path(f).name for f in files} | set(files)
    for q in QUOTE.findall(answer):
        q = q.strip()
        if q in names or CITE.fullmatch(q) or q.startswith(" ") or not q:
            continue  # file names and citation-only quotes are not code claims
        if q not in corpus:
            bad += 1
            notes.append(f"quoted text not found in files: `{q[:60]}`")
    if good == 0:
        notes.append("no verifiable file:line citations")
    return (good > 0 and bad == 0), notes


def verify_patch(root: Path, answer: str) -> tuple[bool, str, list[str]]:
    m = re.search(r"```(?:diff|patch)?\n(.*?)```", answer, re.S)
    patch = (m.group(1) if m else answer).strip() + "\n"
    if "@@" not in patch:
        return False, patch, ["no hunk found in worker output"]
    p = subprocess.run(["git", "apply", "--check", "--recount", "-"], cwd=root, input=patch, text=True, encoding="utf-8", errors="replace", capture_output=True)  # noqa: E501
    if p.returncode != 0:
        return False, patch, [f"patch does not apply: {p.stderr.strip()[:300]}"]
    return True, patch, ["git apply --check passed (not applied)"]


# --------------------------------------------------------------------------- local kinds
def _grep(root: Path, pattern: str, limit: int = 200) -> str:
    rg = ["rg", "-n", "--no-heading", "-S", "-m", "20", pattern, "."]
    try:
        p = subprocess.run(rg, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        lines = p.stdout.splitlines()
    except FileNotFoundError:
        p = subprocess.run(["git", "grep", "-n", "-I", "-E", pattern], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")  # noqa: E501
        lines = p.stdout.splitlines()
    more = f"\n... {len(lines) - limit} more" if len(lines) > limit else ""
    return "\n".join(lines[:limit]) + more


def _context(root: Path, files: list[str]) -> str:
    chunks = []
    for f in files:
        lines = _file_lines(root, f)
        if lines is None:
            chunks.append(f"=== {f} (missing) ===")
            continue
        numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines, 1))
        chunks.append(f"=== {f} ===\n{redact(numbered)[:MAX_FILE_CHARS]}")
    return "\n\n".join(chunks)


# --------------------------------------------------------------------------- swarm
class Swarm:
    def __init__(self, cfg: Config, model_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self.opts = cfg.section("swarm")
        self.model = cfg.model(model_key or self.opts["helper_model"])
        self.transport = transport

    async def _one(self, client: httpx.AsyncClient, sem: asyncio.Semaphore, t: Task) -> Result:
        root = self.cfg.root
        if t.kind == "grep":
            return Result(t.id, t.kind, True, True, _grep(root, t.prompt), ["local ripgrep, no model call"])
        async with sem:
            try:
                if t.kind == "draft_edit":
                    text, ti, to = await _with_retry(lambda: complete(
                        client, self.model, DRAFT_SYSTEM, f"Change requested: {t.prompt}\n\n{_context(root, t.files)}"))
                    ok, patch, notes = verify_patch(root, text)
                    return Result(t.id, t.kind, True, ok, patch, notes, ti, to)
                q = t.prompt if t.kind == "ask" else (t.prompt or "Summarise what this code does, its public API and anything surprising.")
                text, ti, to = await _with_retry(lambda: complete(client, self.model, SYSTEM, f"{q}\n\n{_context(root, t.files)}"))
                ok, notes = verify_citations(root, text, t.files)
                return Result(t.id, t.kind, True, ok, text.strip(), notes, ti, to)
            except Exception as e:  # noqa: BLE001 - one failed worker must not sink the swarm
                return Result(t.id, t.kind, False, False, "", [f"{type(e).__name__}: {str(e)[:200]}"])

    async def run(self, tasks: list[Task]) -> list[Result]:
        if len(tasks) > self.opts["max_tasks"]:
            raise ValueError(f"{len(tasks)} tasks exceeds [swarm].max_tasks={self.opts['max_tasks']}")
        for i, t in enumerate(tasks, 1):
            t.id = t.id or i
        sem = asyncio.Semaphore(int(self.opts["concurrency"]))
        limits = httpx.Limits(max_connections=int(self.opts["concurrency"]) + 4)
        async with httpx.AsyncClient(timeout=120, limits=limits, transport=self.transport) as client:
            return list(await asyncio.gather(*(self._one(client, sem, t) for t in tasks)))


def subagent_plan(tasks: list[Task]) -> str:
    """When no helper model is configured, hand the plan back for the agent's own subagents."""
    lines = ["Delegate these to parallel subagents (Claude Code Task tool, Codex/OpenCode subagents).",
             "Ask each to cite path:line; then pass their answers to swarm_verify."]
    for i, t in enumerate(tasks, 1):
        lines.append(f"{i}. [{t.kind}] {t.prompt} files={t.files}")
    return "\n".join(lines)


def format_results(results: list[Result], max_chars_each: int = 1500) -> str:
    out = []
    for r in results:
        status = "VERIFIED" if r.verified else ("UNVERIFIED" if r.ok else "FAILED")
        out.append(f"--- task {r.id} [{r.kind}] {status}" + (f" ({'; '.join(r.notes)})" if r.notes else ""))
        out.append(r.output[:max_chars_each])
    v = sum(r.verified for r in results)
    out.append(f"=== {v}/{len(results)} verified; helper tokens in={sum(r.tokens_in for r in results)} "
               f"out={sum(r.tokens_out for r in results)}")
    return "\n".join(out)
