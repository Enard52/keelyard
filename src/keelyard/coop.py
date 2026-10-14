"""Cooperative swarm: planner -> workers -> verifier, with a shared blackboard, a peer critic, voting,
cheapest-capable model routing and hard token budgets.

- Ledger: every model call reserves its worst-case cost first. A call that would cross the total or
  per-task cap is refused before it is made, so the budget can't be overshot by concurrent workers.
- Blackboard: facts that passed keelyard's checks, and approaches that failed, shared with later workers
  on the same files.
- Router: each task starts on the cheapest model in the ladder that has been succeeding for its kind,
  and moves up only when the checks fail.
- Critic: a second call reviews every candidate that passed the checks; a rejection sends the task
  back for another round.
- Vote: among accepted candidates, the one most others agree with wins.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass

import httpx

from .config import Config
from .swarm import CITE, Result, Swarm, Task, _with_retry, complete, context_pack, plan

CRITIC_SYSTEM = (
    "You are a strict code reviewer checking a peer's work. Reply with exactly one line: "
    "APPROVE, or REJECT: <the concrete problem>. Reject only for a real bug, a wrong answer, or a change "
    "that does not do what was asked."
)


class BudgetExceeded(Exception):
    pass


class Ledger:
    """Token accounting with hard caps (0 = no cap). Reserve the worst case, then settle the real usage."""

    def __init__(self, total: int = 0, per_task: int = 0):
        self.total, self.per_task = int(total), int(per_task)
        self.used = self.reserved = self.refused = self.calls = 0
        self.task: dict[int, int] = defaultdict(int)  # used + reserved per task
        self.by_model: dict[str, int] = defaultdict(int)
        self._freed = asyncio.Event()

    def _check(self, task: int, est: int, with_reserved: bool) -> None:
        if self.per_task and self.task[task] + est > self.per_task:
            raise BudgetExceeded(f"task budget {self.per_task} tokens reached")
        if self.total and self.used + (self.reserved if with_reserved else 0) + est > self.total:
            raise BudgetExceeded(f"swarm budget {self.total} tokens reached")

    def reserve(self, task: int, est: int) -> None:
        try:
            self._check(task, est, True)
        except BudgetExceeded:
            self.refused += 1
            raise
        self.reserved += est
        self.task[task] += est

    async def acquire(self, task: int, est: int) -> None:
        """Like reserve, but waits while only other workers' open reservations are in the way."""
        while True:
            try:
                self._check(task, est, False)  # can never fit: refuse now
            except BudgetExceeded:
                self.refused += 1
                raise
            try:
                self._check(task, est, True)
            except BudgetExceeded:
                self._freed.clear()
                await self._freed.wait()
                continue
            self.reserved += est
            self.task[task] += est
            return

    def settle(self, task: int, est: int, model: str, tokens_in: int, tokens_out: int) -> None:
        spent = tokens_in + tokens_out
        self.reserved -= est
        self.task[task] += spent - est
        self.used += spent
        self.by_model[model] += spent
        self.calls += 1
        self._freed.set()


@dataclass
class Note:
    task: int
    files: tuple[str, ...]
    text: str
    verified: bool


class Blackboard:
    """What workers learned, shared with the next workers on the same files."""

    def __init__(self, max_chars: int = 1200):
        self.notes: list[Note] = []
        self.max_chars = max_chars

    def post(self, task: int, files: list[str], text: str, verified: bool) -> None:
        self.notes.append(Note(task, tuple(files), " ".join(text.split())[:300], verified))

    def for_files(self, files: list[str], exclude: int = -1) -> str:
        want = set(files)
        rel = [n for n in self.notes if n.task != exclude and want & set(n.files)]
        good = [f"- {n.text}" for n in rel if n.verified]
        bad = [f"- {n.text}" for n in rel if not n.verified]
        parts = (["Verified by other workers:", *good] if good else []) + (["Tried and rejected:", *bad[-5:]] if bad else [])
        text = "\n".join(parts)
        return text[: self.max_chars]


class Router:
    """Cheapest-capable routing: skip a tier for a kind once it keeps failing there."""

    def __init__(self, ladder: list[str], min_seen: int = 3, min_rate: float = 0.34):
        self.ladder = ladder
        self.min_seen, self.min_rate = min_seen, min_rate
        self.stats: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])

    def record(self, kind: str, tier: int, ok: bool) -> None:
        s = self.stats[(kind, tier)]
        s[0] += 1
        s[1] += int(ok)

    def start(self, kind: str) -> int:
        for i in range(len(self.ladder) - 1):
            seen, ok = self.stats[(kind, i)]
            if not (seen >= self.min_seen and ok / seen < self.min_rate):
                return i
        return len(self.ladder) - 1


def _key(t: Task, text: str) -> str:
    """What two candidates must share to count as agreeing."""
    if t.kind == "draft_edit":
        return "\n".join(ln.strip() for ln in text.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
    return " ".join(sorted({f"{a.rsplit('/', 1)[-1]}:{b}" for a, b, _ in CITE.findall(text)}))


class Coop(Swarm):
    def __init__(self, cfg: Config, transport: httpx.AsyncBaseTransport | None = None, **kw):
        super().__init__(cfg, transport=transport, **kw)
        o = self.opts
        names = list(o.get("ladder") or [])
        if not names:
            names = [o["helper_model"]] + ([o["escalate_model"]] if self.escalate else [])
        self.ladder = []
        for n in names:
            m = cfg.model(n)
            if m.get("model") not in ("", "set-me", None):
                self.ladder.append(m)
        if not self.ladder:
            raise ValueError("no usable model in [swarm].ladder")
        self.router = Router([m["model"] for m in self.ladder])
        self.board = Blackboard()
        self.ledger = Ledger(o.get("budget_tokens", 0), o.get("task_budget_tokens", 0))
        self.workers = max(1, int(o.get("workers", 64)))
        self.critic = bool(o.get("critic", True))

    def _estimate(self, model: dict, t: Task, extra: str, feedback: str) -> int:
        ctx = context_pack(self.cfg.root, t.files, t.symbols)
        chars = len(ctx) + len(t.prompt) + len(extra) + len(feedback) + 1200  # + system prompt and framing
        return chars // 3 + int(model.get("max_tokens", 1500))  # chars/3 over-counts tokens on purpose

    async def _call(self, r: Result, est: int, model: dict, coro_fn):
        await self.ledger.acquire(r.id, est)
        ti = to = 0
        try:
            out = await coro_fn()
            ti, to = out[-2], out[-1]
            return out
        finally:
            self.ledger.settle(r.id, est, model["model"], ti, to)
            r.tokens_in += ti
            r.tokens_out += to

    async def _candidate(self, client, model, t: Task, r: Result, feedback: str, temp: float, extra: str):
        est = self._estimate(model, t, extra, feedback)

        async def go():
            out = await self._sample(client, model, t, feedback, temp, extra)
            return out[0], out[1], out[2], out[5], out[3], out[4]
        text, ok, notes, tests, _, _ = await self._call(r, est, model, go)
        verdict = None
        if ok and self.critic:
            user = f"Request: {t.prompt}\n\nPeer's {'patch' if t.kind == 'draft_edit' else 'answer'}:\n{text[:4000]}\n\n" \
                   f"{context_pack(self.cfg.root, t.files, t.symbols)}"
            cest = len(user) // 3 + 400 + 60
            critic_model = {**model, "max_tokens": 60}
            v, _, _ = await self._call(r, cest, model, lambda: _with_retry(
                lambda: complete(client, critic_model, CRITIC_SYSTEM, user, 0.0)))
            i = v.upper().find("REJECT")
            verdict = ("REJECT" + v[i + 6:].split("\n")[0][:200]).strip() if i >= 0 else "APPROVE"
        return text, ok, list(notes), tests, verdict

    async def _one(self, client: httpx.AsyncClient, sem: asyncio.Semaphore, t: Task) -> Result:
        if t.kind == "grep":
            return await super()._one(client, sem, t)
        r = Result(t.id, t.kind, True, False, "")
        feedback = ""
        start = self.router.start(t.kind)
        try:
            async with sem:
                for tier in range(start, len(self.ladder)):
                    model = self.ladder[tier]
                    for _ in range(1 + self.retries):
                        r.attempts += 1
                        extra = self.board.for_files(t.files, exclude=t.id)
                        cands = await asyncio.gather(*(self._candidate(client, model, t, r, feedback, 0.1 if k == 0 else 0.7, extra)
                                                       for k in range(self.best_of)), return_exceptions=True)
                        budget = [c for c in cands if isinstance(c, BudgetExceeded)]
                        good = [c for c in cands if not isinstance(c, BaseException)]
                        r.candidates += len(good)
                        if not good:
                            raise (budget or cands)[0]
                        keys = [_key(t, c[0]) for c in good]
                        accepted = [i for i, c in enumerate(good) if c[1] and not (c[4] or "").startswith("REJECT")]
                        pool = accepted or [i for i, c in enumerate(good) if c[1]] or list(range(len(good)))
                        best = max(pool, key=lambda i: (keys.count(keys[i]) if keys[i] else 1, -len(good[i][0])))
                        text, ok, notes, tests, verdict = good[best]
                        r.output, r.verified, r.notes, r.tests_passed = text, ok, notes, tests
                        r.critic, r.model, r.escalated = verdict, model["model"], tier > 0
                        r.consensus = keys.count(keys[best]) if keys[best] else 1
                        if accepted:
                            self.router.record(t.kind, tier, True)
                            self.board.post(t.id, t.files, f"{t.prompt[:80]} -> {text[:200]}", True)
                            r.notes.append(f"{r.candidates} candidates, {r.attempts} round(s), model {r.model}"
                                           + (f", {r.consensus} agreed" if r.consensus > 1 else ""))
                            return r
                        why = "; ".join(notes)[:300] if not ok else (verdict or "")
                        self.board.post(t.id, t.files, f"rejected for '{t.prompt[:60]}': {why}", False)
                        feedback = why
                    self.router.record(t.kind, tier, False)
            if r.critic and r.critic.startswith("REJECT") and r.verified:
                r.notes.append(f"critic objected: {r.critic}")
            return r
        except BudgetExceeded as e:
            r.ok, r.notes = bool(r.output), [*r.notes, f"stopped: {e}"]
            return r
        except Exception as e:  # noqa: BLE001 - one failed worker must not sink the swarm
            return Result(t.id, t.kind, False, False, "", [f"{type(e).__name__}: {str(e)[:200]}"], r.tokens_in, r.tokens_out,
                          r.attempts, r.candidates)

    async def run(self, tasks: list[Task]) -> list[Result]:
        if len(tasks) > self.opts["max_tasks"]:
            raise ValueError(f"{len(tasks)} tasks exceeds [swarm].max_tasks={self.opts['max_tasks']}")
        for i, t in enumerate(tasks, 1):
            t.id = t.id or i
        sem = asyncio.Semaphore(self.workers)
        limits = httpx.Limits(max_connections=self.workers * self.best_of + 4)
        async with httpx.AsyncClient(timeout=180, limits=limits, transport=self.transport) as client:
            return list(await asyncio.gather(*(self._one(client, sem, t) for t in tasks)))


def summary(coop: Coop, results: list[Result]) -> dict:
    verified = sum(r.verified for r in results)
    return {"tasks": len(results), "verified": verified, "tokens": coop.ledger.used,
            "tokens_per_verified": round(coop.ledger.used / verified) if verified else None,
            "calls": coop.ledger.calls, "refused_calls": coop.ledger.refused, "tokens_by_model": dict(coop.ledger.by_model),
            "budget_tokens": coop.ledger.total or None}


async def solve(cfg: Config, goal: str, files: list[str] | None = None, transport: httpx.AsyncBaseTransport | None = None,
                **kw) -> dict:
    """Planner -> workers -> verifier for one goal. Nothing is applied to the project."""
    tasks = plan(cfg, goal, files)
    coop = Coop(cfg, transport=transport, **kw)
    results = await coop.run(tasks)
    return {**summary(coop, results), "results": results}


