"""Helper swarm: fan cheap subtasks out to many small-model workers, then verify them.

The main (expensive) agent stays the planner and the judge. Workers only read,
summarise, search and draft. Nothing a worker returns is applied automatically:
drafts come back as patches that were checked with `git apply --check`, and
claims about the code must cite file:line references that keelyard verifies.
"""

from __future__ import annotations

import asyncio
import json
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
    kind: str  # ask | summarize | draft_edit | grep
    prompt: str = ""
    files: list[str] = field(default_factory=list)
    id: int = 0
    symbols: list[str] = field(default_factory=list)  # narrow the context pack to these definitions


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
    attempts: int = 0
    candidates: int = 0
    escalated: bool = False
    tests_passed: bool | None = None
    model: str = ""  # model that produced the accepted answer (cooperative swarm)
    critic: str | None = None  # the peer reviewer's verdict on it
    consensus: int = 0  # how many candidates agreed with it


# --------------------------------------------------------------------------- providers
async def complete(client: httpx.AsyncClient, model: dict[str, Any], system: str, user: str,
                   temperature: float = 0.1) -> tuple[str, int, int]:
    key = os.environ.get(model.get("api_key_env") or "", "")
    if model["provider"] == "anthropic":
        r = await client.post(
            model["base_url"].rstrip("/") + "/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": model["model"], "max_tokens": model.get("max_tokens", 1500), "system": system,
                  "temperature": temperature,
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
        json={"model": model["model"], "temperature": temperature, "max_tokens": model.get("max_tokens", 1500),
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
    )
    r.raise_for_status()
    j = r.json()
    u = j.get("usage", {})
    return j["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


FREE_HINT = ('point [models.cheap] at a free model, e.g. base_url = "https://openrouter.ai/api/v1", '
             'model = "<name>:free", api_key_env = "OPENROUTER_API_KEY"; or run Ollama locally (`ollama pull qwen2.5-coder:7b`)')


def explain(e: BaseException) -> str:
    """One line a person can act on, instead of an httpx traceback summary. Never includes request headers (keys)."""
    if isinstance(e, httpx.HTTPStatusError):
        url, code = str(e.request.url), e.response.status_code
        if code in (401, 403):
            return f"{url} rejected the API key (HTTP {code}). Hint: check the variable named in api_key_env"
        if code == 404:
            return f"{url} says not found (HTTP 404): wrong base_url, or the model is not available there. Hint: {FREE_HINT}"
        if code == 429:
            return f"{url} is rate-limiting (HTTP 429) after retries. Hint: lower [swarm].concurrency or try later"
        if code == 402:
            return f"{url} wants payment (HTTP 402). Hint: use a ':free' model; keelyard never needs a paid one"
        return f"{url} answered HTTP {code}"
    if isinstance(e, httpx.ConnectError | httpx.ConnectTimeout):
        url = str(e.request.url) if getattr(e, "_request", None) is not None else "the helper model"
        return f"cannot reach {url}. Hint: {FREE_HINT}"
    if isinstance(e, httpx.TimeoutException):
        return "the helper model timed out. Hint: a smaller model, or raise [models.<key>].timeout"
    if isinstance(e, httpx.TransportError):
        url = str(e.request.url) if getattr(e, "_request", None) is not None else "the helper model"
        return f"connection to {url} failed ({type(e).__name__}: {str(e)[:120] or 'closed early'}). Hint: {FREE_HINT}"
    return f"{type(e).__name__}: {str(e)[:200]}"


def preflight(model: dict[str, Any]) -> str | None:
    """Problems we can see before spending a call."""
    env = model.get("api_key_env") or ""
    if model.get("model") in ("", "set-me"):
        return f"model {model.get('model')!r} is not set. Hint: {FREE_HINT}"
    if env and not os.environ.get(env):
        return f"${env} is not set (api_key_env for {model.get('model')}). Hint: export it, or {FREE_HINT}"
    return None


async def _with_retry(fn, attempts: int | None = None):
    attempts = attempts or int(os.environ.get("KEELYARD_RETRIES", "4"))  # free tiers rate-limit hard
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
    return p.read_text(errors="replace", encoding="utf-8").splitlines()


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


def _symbol_ranges(lines: list[str], symbols: list[str]) -> list[tuple[int, int]]:
    """1-based inclusive line ranges of the named top-level or nested definitions (indent-based)."""
    out = []
    for name in symbols:
        rx = re.compile(rf"^(\s*)(export\s+)?(default\s+)?(async\s+)?(def|class|function|fn|func|const|let|var|type|interface)\s+"
                        rf"{re.escape(name.split('.')[-1])}\b")
        for i, ln in enumerate(lines):
            m = rx.match(ln)
            if not m:
                continue
            indent, j = len(m.group(1)), i + 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent
                                      or lines[j].lstrip().startswith((")", "}", "]"))):
                j += 1
            while i > 0 and lines[i - 1].lstrip().startswith("@"):  # decorators
                i -= 1
            out.append((i + 1, j))
    return out


def context_pack(root: Path, files: list[str], symbols: list[str] | None = None, budget_chars: int = MAX_FILE_CHARS) -> str:
    """Only what a helper needs: whole small files, or just the named definitions plus imports, with real line
    numbers so citations stay checkable."""
    chunks = []
    for f in files:
        lines = _file_lines(root, f)
        if lines is None:
            chunks.append(f"=== {f} (missing) ===")
            continue
        keep: set[int] = set()
        ranges = _symbol_ranges(lines, symbols or []) if symbols else []
        if ranges:
            keep |= {i for i, ln in enumerate(lines, 1) if re.match(r"\s*(import|from|use|#include|require)\b", ln)}
            for a, b in ranges:
                keep |= set(range(a, b + 1))
        shown, last = [], 0
        for i, ln in enumerate(lines, 1):
            if keep and i not in keep:
                continue
            if keep and last and i != last + 1:
                shown.append("   …")
            shown.append(f"{i}: {ln}")
            last = i
        label = f"{f} (only {', '.join(symbols or [])})" if ranges else f
        chunks.append(f"=== {label} ===\n{redact(chr(10).join(shown))[:budget_chars]}")
    return "\n\n".join(chunks)


def _context(root: Path, files: list[str]) -> str:
    return context_pack(root, files)


# --------------------------------------------------------------------------- swarm
REPLACE_SYSTEM = (
    "You fix code. You get one definition and a change request. Reply with only the complete new version of that "
    "definition (same name, same indentation) in one ```code block. No explanation."
)


def splice_definition(root: Path, rel: str, symbol: str, answer: str) -> str | None:
    """Build a unified diff that replaces `symbol` in `rel` with the code block in `answer`. None if impossible."""
    import difflib

    m = re.search(r"```[\w+-]*\n(.*?)```", answer, re.S)
    new = (m.group(1) if m else answer).rstrip("\n")
    lines = _file_lines(root, rel)
    ranges = _symbol_ranges(lines or [], [symbol])
    if not lines or not ranges or not re.search(rf"\b{re.escape(symbol.split('.')[-1])}\b", new):
        return None
    a, b = ranges[0]
    while b > a and not lines[b - 1].strip():  # keep the blank lines after the definition
        b -= 1
    indent = len(lines[a - 1]) - len(lines[a - 1].lstrip())
    new_lines = new.splitlines()
    cur = len(new_lines[0]) - len(new_lines[0].lstrip()) if new_lines else 0
    if cur != indent:
        new_lines = [(" " * indent + ln[cur:]) if ln.strip() else ln for ln in new_lines]
    after = lines[:a - 1] + new_lines + lines[b:]
    diff = "".join(difflib.unified_diff([x + "\n" for x in lines], [x + "\n" for x in after], f"a/{rel}", f"b/{rel}", n=3))
    return diff or None


ASK_SCHEMA = ('Reply with JSON only: {"answer": "<short answer>", "citations": ["path:line", ...], '
              '"quotes": ["exact code text"]}.')


def parse_ask(text: str) -> str:
    """Accept the JSON schema or free text; return one string the citation checker can read."""
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            j = json.loads(m.group(0))
            if isinstance(j, dict) and "answer" in j:
                cites = " ".join(str(c) for c in j.get("citations") or [])
                quotes = " ".join(f"`{q}`" for q in j.get("quotes") or [] if isinstance(q, str))
                return f"{j['answer']}\nSources: {cites} {quotes}".strip()
        except ValueError:
            pass
    return text.strip()


FAILED_RX = re.compile(r"^(?:FAILED|ERROR) (\S+)|^--- FAIL: (\S+)|^test (\S+) \.\.\. FAILED|^\s+✕ (.+)$", re.M)


def failing_tests(output: str) -> set[str]:
    """Names of failing tests from pytest, go test, cargo test or jest output (empty if unknown)."""
    return {next(g for g in m.groups() if g) for m in FAILED_RX.finditer(output)}


def test_patch(cfg: Config, patch: str, cmd: str, timeout: int = 300, baseline: set[str] | None = None) -> tuple[bool, str]:
    """Apply a patch to a throwaway copy of the project and run the tests there. The project is never touched.

    Passes when the suite is green, or, if the suite already failed before the patch (`baseline`), when the patch
    fixes at least one failing test and breaks none."""
    import shutil
    import tempfile

    from .codemap import tracked_files
    from .proc import split_cmd

    with tempfile.TemporaryDirectory(prefix="keelyard-try-") as tmp:
        dst = Path(tmp)
        for rel in tracked_files(cfg.root):
            src = cfg.root / rel
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue  # stale bytecode can mask the patch (same size, same second)
            if src.is_file():
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst / rel)
        if patch.strip():
            p = subprocess.run(["git", "apply", "--recount", "-"], cwd=dst, input=patch, text=True, encoding="utf-8",
                               errors="replace", capture_output=True)
            if p.returncode != 0:
                return False, f"patch does not apply: {p.stderr.strip()[:200]}"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            t = subprocess.run(split_cmd(cmd), cwd=dst, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return False, f"tests timed out after {timeout}s"
        except FileNotFoundError as e:
            return False, f"test command not found: {e}"
        out = t.stdout + t.stderr
        tail = out.strip().splitlines()[-12:]
        if not patch.strip():
            return t.returncode == 0, out
        if t.returncode == 0:
            return True, "tests pass"
        now = failing_tests(out)
        if baseline and now and now < baseline:
            return True, f"fixes {len(baseline - now)} failing test(s), breaks none ({len(now)} still failing, they were before)"
        if baseline and now:
            new = now - baseline
            if new:
                return False, "breaks tests that passed before: " + ", ".join(sorted(new)[:5]) + "\n" + "\n".join(tail)
            return False, "fixes no failing test:\n" + "\n".join(tail)
        return False, "tests fail:\n" + "\n".join(tail)


def baseline_failures(cfg: Config, cmd: str, timeout: int = 300) -> set[str]:
    """Failing tests before any patch, run in a throwaway copy so the project gets no caches or side effects."""
    ok, out = test_patch(cfg, "", cmd, timeout)
    return set() if ok else failing_tests(out)


def _vote(cands: list[tuple[str, bool, list[str]]]) -> int:
    """Among verified answers, prefer the one whose citations most other answers agree with."""
    def cites(t: str) -> set[str]:
        return {f"{Path(a).name}:{b}" for a, b, _ in CITE.findall(t)}
    best, score = 0, -1
    for i, (text, ok, _) in enumerate(cands):
        if not ok:
            continue
        agree = sum(len(cites(text) & cites(o)) for j, (o, _, _) in enumerate(cands) if j != i)
        if agree > score:
            best, score = i, agree
    return best


class Swarm:
    def __init__(self, cfg: Config, model_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 best_of: int | None = None, retries: int | None = None, escalate: str | None = None,
                 test_patches: bool | None = None):
        self.cfg = cfg
        self.opts = cfg.section("swarm")
        self.model = cfg.model(model_key or self.opts["helper_model"])
        self.transport = transport
        self.best_of = max(1, int(self.opts["best_of"] if best_of is None else best_of))
        self.retries = max(0, int(self.opts["retries"] if retries is None else retries))
        esc = self.opts["escalate_model"] if escalate is None else escalate
        self.escalate = None
        if esc:
            try:
                m = cfg.model(esc)
                if m.get("model") not in ("", "set-me", None) and m != self.model:
                    self.escalate = m
            except KeyError:
                pass
        self.test_patches = bool(self.opts["test_patches"] if test_patches is None else test_patches)
        from .proof import detect_test_cmd

        self.test_cmd = cfg.section("proof").get("test_cmd") or detect_test_cmd(cfg.root)
        self._baseline: set[str] | None = None
        self._baseline_lock = asyncio.Lock()

    async def _sample(self, client, model, t: Task, feedback: str, temp: float,
                      extra: str = "") -> tuple[str, bool, list[str], int, int, bool | None]:
        root = self.cfg.root
        ctx = context_pack(root, t.files, t.symbols)
        fb = f"\n\nYour previous attempt was rejected:\n{feedback}\nFix exactly that." if feedback else ""
        fb += f"\n\n{extra}" if extra else ""
        if t.kind == "draft_edit":
            if len(t.files) == 1 and len(t.symbols) == 1:
                # small models are far better at rewriting one definition than at writing diffs; keelyard
                # builds the diff itself
                text, ti, to = await _with_retry(lambda: complete(
                    client, model, REPLACE_SYSTEM, f"Change requested: {t.prompt}{fb}\n\n{ctx}", temp))
                diff = splice_definition(root, t.files[0], t.symbols[0], text)
                text = f"```diff\n{diff}```" if diff else text
            else:
                text, ti, to = await _with_retry(lambda: complete(
                    client, model, DRAFT_SYSTEM, f"Change requested: {t.prompt}{fb}\n\n{ctx}", temp))
            ok, patch, notes = verify_patch(root, text)
            tests = None
            if ok and self.test_patches and self.test_cmd:
                if self._baseline is None:
                    async with self._baseline_lock:
                        if self._baseline is None:
                            self._baseline = await asyncio.to_thread(baseline_failures, self.cfg, self.test_cmd)
                tests, msg = await asyncio.to_thread(test_patch, self.cfg, patch, self.test_cmd, 300, self._baseline)
                notes.append(msg)
                ok = tests
            return patch, ok, notes, ti, to, tests
        q = t.prompt if t.kind == "ask" else (t.prompt or "Summarise what this code does, its public API and anything surprising.")
        text, ti, to = await _with_retry(lambda: complete(client, model, SYSTEM + " " + ASK_SCHEMA, f"{q}{fb}\n\n{ctx}", temp))
        answer = parse_ask(text)
        ok, notes = verify_citations(root, answer, t.files)
        return answer, ok, notes, ti, to, None

    async def _one(self, client: httpx.AsyncClient, sem: asyncio.Semaphore, t: Task) -> Result:
        root = self.cfg.root
        if t.kind == "grep":
            return Result(t.id, t.kind, True, True, _grep(root, t.prompt), ["local ripgrep, no model call"])
        r = Result(t.id, t.kind, True, False, "")
        feedback = ""
        stages = [(self.model, self.best_of, False)] * (1 + self.retries)
        if self.escalate:
            stages.append((self.escalate, 1, True))
        try:
            for model, n, esc in stages:
                r.attempts += 1
                async with sem:
                    cands = await asyncio.gather(*(self._sample(client, model, t, feedback, 0.1 if k == 0 else 0.7)
                                                   for k in range(n)), return_exceptions=True)
                good = [c for c in cands if not isinstance(c, BaseException)]
                r.candidates += len(cands)
                for c in good:
                    r.tokens_in += c[3]
                    r.tokens_out += c[4]
                if not good:
                    raise cands[0]  # type: ignore[misc]
                if t.kind == "draft_edit":
                    passing = [c for c in good if c[1]]
                    pick = min(passing, key=lambda c: len(c[0])) if passing else good[0]
                else:
                    pick = good[_vote([(c[0], c[1], c[2]) for c in good])]
                r.output, r.verified, r.notes, r.tests_passed = pick[0], pick[1], list(pick[2]), pick[5]
                r.escalated = esc
                if r.verified:
                    break
                feedback = "; ".join(pick[2])[:600]
            if r.attempts > 1 or r.candidates > 1:
                r.notes.append(f"{r.candidates} candidates over {r.attempts} round(s)" + (", escalated" if r.escalated else ""))
            return r
        except Exception as e:  # noqa: BLE001 - one failed worker must not sink the swarm
            return Result(t.id, t.kind, False, False, "", [explain(e)], r.tokens_in, r.tokens_out,
                          r.attempts, r.candidates)

    async def run(self, tasks: list[Task]) -> list[Result]:
        if len(tasks) > self.opts["max_tasks"]:
            raise ValueError(f"{len(tasks)} tasks exceeds [swarm].max_tasks={self.opts['max_tasks']}")
        for i, t in enumerate(tasks, 1):
            t.id = t.id or i
        sem = asyncio.Semaphore(int(self.opts["concurrency"]))
        limits = httpx.Limits(max_connections=int(self.opts["concurrency"]) * self.best_of + 4)
        async with httpx.AsyncClient(timeout=180, limits=limits, transport=self.transport) as client:
            return list(await asyncio.gather(*(self._one(client, sem, t) for t in tasks)))


# --------------------------------------------------------------------------- planner
EDIT_VERBS = re.compile(r"\b(fix|add|change|implement|rename|refactor|remove|update|make|support|handle|raise|return)\b", re.I)


def plan(cfg: Config, goal: str, files: list[str] | None = None, max_tasks: int = 8) -> list[Task]:
    """Split a goal into small, well-scoped tasks with focused context: one task per file that defines a symbol
    the goal mentions (or per given file), narrowed to those symbols. Deterministic; no model call."""
    from .codemap import find_symbol, tracked_files

    kind = "draft_edit" if EDIT_VERBS.search(goal) else "ask"
    idents = [w for w in dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", goal))
              if w.lower() not in STOPWORDS]
    by_file: dict[str, list[str]] = {}
    for f in files or []:
        by_file.setdefault(f, [])
    if not files:
        for w in idents:
            hits = find_symbol(cfg.root, w, limit=5)
            for line in hits.splitlines():
                m = re.match(r"(.+?):(\d+):", line)
                if m:
                    by_file.setdefault(m.group(1), [])
                    if w not in by_file[m.group(1)]:
                        by_file[m.group(1)].append(w)
        if not by_file:  # fall back to files whose names the goal mentions
            low = goal.lower()
            for rel in tracked_files(cfg.root):
                if Path(rel).stem.lower() in low and len(Path(rel).stem) > 2:
                    by_file.setdefault(rel, [])
    tasks = []
    for i, (f, syms) in enumerate(list(by_file.items())[:max_tasks], 1):
        focus = f" Focus on {', '.join(syms)}." if syms else ""
        g = goal.strip()
        g = g if g.endswith((".", "?", "!")) else g + "."
        tasks.append(Task(kind=kind, prompt=f"{g}{focus} Only change/answer about {f}.", files=[f], id=i,
                          symbols=syms))
    return tasks


STOPWORDS = set("the and for with that this from into when then than make sure should would could please about "
                "into only also code file files function class method test tests bug".split())


def subagent_tasks(cfg: Config, tasks: list[Task]) -> list[dict]:
    """Ready-to-send prompts for the host agent's own subagents (Claude Code Task tool, OpenCode subagents)."""
    out = []
    for t in tasks:
        pack = context_pack(cfg.root, t.files, t.symbols, budget_chars=6000)
        if t.kind == "draft_edit":
            want = ("Return only a unified diff (a/ b/ paths) in one ```diff block. Do not edit files yourself. "
                    "It will be checked with swarm_verify(kind=\"draft_edit\") and the tests.")
        else:
            want = ASK_SCHEMA + " It will be checked with swarm_verify: every path:line must exist."
        out.append({"id": t.id, "kind": t.kind, "files": t.files, "symbols": t.symbols,
                    "subagent_prompt": f"{t.prompt}\n\n{want}\n\nContext (line-numbered):\n{pack}"})
    return out




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
