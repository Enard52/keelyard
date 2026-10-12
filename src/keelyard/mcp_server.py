"""MCP stdio server: the agent-facing interface to every keelyard module.

Every tool returns a JSON object (MCP structured content) with stable keys, so an
agent never has to parse prose. Errors come back as MCP tool errors whose text
starts with what went wrong and ends with a `Hint:` saying what to do next.
"""

from __future__ import annotations

import functools
import inspect
from typing import Annotated, Any, Literal

from pydantic import Field

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore
from mcp.types import ToolAnnotations

try:
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore

from . import __version__, config, session
from .codemap import find_symbol as _find_symbol
from .codemap import outline as _outline
from .codemap import project_map as _project_map
from .filters import run_filtered
from .memory import Memory
from .proof import Proof
from .report import render
from .saver import ReadCache, compress_output, route
from .snapshot import Shadow
from .swarm import Swarm, Task, subagent_plan, verify_citations, verify_patch
from .usage import collect as usage_collect

INSTRUCTIONS = """keelyard: proof, rewind and a smaller context for this project.

Workflow for any task that changes files:
1. proof_requirements(items=[...])  one short, checkable item per thing the user asked for.
2. Explore cheaply: project_map, find_symbol, outline, then read_file (repeat reads are deduplicated).
3. Make the change. Every edit is snapshotted automatically; rewind_list / rewind_to undo mistakes.
4. run_compact for noisy commands (tests, builds, git log); recall(output_id) if you need the full text.
5. proof_run_tests(phase="after"), then proof_check(requirement_id, evidence) for each item.
6. proof_status must say proven=true before you tell the user you are done; the Stop hook enforces it.
Use memory_search before re-deriving something solved in an earlier session, and swarm for bulk
read/summarise/draft work that a cheap model can do with checkable citations."""

mcp = _Server("keelyard", instructions=INSTRUCTIONS)


def _ann(title: str, read_only: bool = False, destructive: bool = False, idempotent: bool = False, open_world: bool = False):
    return ToolAnnotations.model_validate({"title": title, "readOnlyHint": read_only, "destructiveHint": destructive,
                                           "idempotentHint": idempotent, "openWorldHint": open_world})


def _tool(annotations: ToolAnnotations):
    """Register a tool; expected failures reach the agent as a ToolError with their hint text."""
    def deco(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                try:
                    return await fn(*args, **kwargs)
                except ToolError:
                    raise
                except (ValueError, KeyError, LookupError, OSError, RuntimeError, config.ProjectError) as exc:
                    raise ToolError(str(exc).strip("'\"")) from exc
            return mcp.tool(annotations=annotations)(awrapper)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ToolError:
                raise
            except (ValueError, KeyError, LookupError, OSError, RuntimeError, config.ProjectError) as exc:
                raise ToolError(str(exc).strip("'\"")) from exc
        return mcp.tool(annotations=annotations)(wrapper)
    return deco


def _ctx() -> tuple[config.Config, str]:
    cfg = config.load()
    cfg.require_project()
    return cfg, session.current(cfg)


Step = Annotated[int, Field(ge=1, description="A step number from rewind_list, e.g. 3.")]


# ---------------------------------------------------------------- proof
@_tool(_ann("Record requirements", idempotent=True))
def proof_requirements(
    items: Annotated[list[str], Field(min_length=1, description='One short, checkable item per user ask, e.g. ["discount applies once", "empty cart costs 0"].')],
) -> dict[str, Any]:
    """Record what the user asked for as a checklist. Call this first. Duplicate items are ignored.

    Returns {"requirements": [{"id", "text", "done", "evidence"}]}."""
    cfg, sid = _ctx()
    return {"requirements": Proof(cfg, sid).add_requirements(items)}


@_tool(_ann("Mark requirement verified", idempotent=True))
def proof_check(
    requirement_id: Annotated[int, Field(ge=1, description="The id from proof_requirements, e.g. 1.")],
    evidence: Annotated[str, Field(min_length=1, description='What you ran or saw, e.g. "pytest tests/test_cart.py::test_once passed" or "cart.py:14 caps at one use".')],
) -> dict[str, Any]:
    """Mark one requirement as verified, with concrete evidence (a command and its result, or file:line).

    Returns the updated requirement."""
    cfg, sid = _ctx()
    return Proof(cfg, sid).check(requirement_id, evidence)


@_tool(_ann("Run tests", open_world=True))
def proof_run_tests(
    phase: Annotated[Literal["before", "after"], Field(description='"before" your change (baseline) or "after" it (required by the gate).')] = "after",
    command: Annotated[str, Field(description='Optional override, e.g. "pytest -q tests/test_cart.py". Default: [proof].test_cmd or auto-detected.')] = "",
) -> dict[str, Any]:
    """Run the project's tests and record the result as evidence.

    Returns {"exit", "passed", "seconds", "cmd", "output"} where output is a compact tail."""
    cfg, sid = _ctx()
    r = Proof(cfg, sid).run_tests(phase, command or None)
    return {"exit": r["exit"], "passed": r["exit"] == 0, "seconds": r["seconds"], "cmd": r["cmd"],
            "output": compress_output(r["tail"], 3000)}


@_tool(_ann("Screenshot app", open_world=True))
def proof_screenshot(
    url: Annotated[str, Field(description='Page to capture, e.g. "http://localhost:3000/cart". Default: [proof].app_url.')] = "",
) -> dict[str, Any]:
    """Screenshot the running web app and attach it to the proof bundle. Returns {"ok", "path"} or an error."""
    cfg, sid = _ctx()
    return Proof(cfg, sid).screenshot(url or None)


@_tool(_ann("Proof status", read_only=True))
def proof_status() -> dict[str, Any]:
    """Is the work proven? Returns {"proven", "missing": [what to do next], "requirements", "report"}."""
    cfg, sid = _ctx()
    pf = Proof(cfg, sid)
    gaps = pf.missing()
    return {"proven": not gaps, "missing": gaps, "requirements": pf.load().requirements, "report": str(render(pf))}


# ---------------------------------------------------------------- rewind
def _step(s) -> dict[str, Any]:
    return {"step": s.step, "tool": s.tool, "ts": round(s.ts, 3), "files": s.files[:20], "n_files": len(s.files)}


@_tool(_ann("List snapshots", read_only=True))
def rewind_list(last: Annotated[int, Field(ge=1, le=500, description="How many recent steps, e.g. 20.")] = 20) -> dict[str, Any]:
    """List recent workspace snapshots, oldest first. One is taken after every edit or shell command.

    Returns {"steps": [{"step", "tool", "ts", "files", "n_files"}], "total"}."""
    cfg, _ = _ctx()
    steps = Shadow(cfg).steps()
    return {"steps": [_step(s) for s in steps[-last:]], "total": len(steps)}


@_tool(_ann("Show a step's diff", read_only=True))
def rewind_diff(step: Step) -> dict[str, Any]:
    """The unified diff a snapshot step made. Returns {"step", "files", "diff"} (long diffs are shortened)."""
    cfg, _ = _ctx()
    sh = Shadow(cfg)
    return {"step": step, "files": sh.get(step).files, "diff": compress_output(sh.diff(step), 8000)}


@_tool(_ann("Restore files to a step", destructive=True))
def rewind_to(step: Step) -> dict[str, Any]:
    """Restore project files to how they were after `step`. A safety snapshot is taken first,
    so calling rewind_to(safety_step) undoes this. Returns {"restored", "removed", "safety_step", "new_step"}."""
    cfg, _ = _ctx()
    return Shadow(cfg).rewind(step)


# ---------------------------------------------------------------- context saver
@_tool(_ann("Read file (deduplicated)", read_only=True))
def read_file(
    path: Annotated[str, Field(description='Project-relative path, e.g. "src/cart.py". Windows separators are accepted.')],
    start: Annotated[int, Field(ge=1, description="First line, 1-based.")] = 1,
    end: Annotated[int, Field(ge=0, description="Last line, inclusive; 0 = end of file.")] = 0,
    force: Annotated[bool, Field(description="Return the full text even if you read it before (e.g. after compaction).")] = False,
) -> dict[str, Any]:
    """Read a project file. A repeat read of an unchanged file returns a one-line notice instead of the
    text; a changed file returns only the diff since your last read. Returns {"path", "content"}."""
    cfg, sid = _ctx()
    return {"path": path, "content": ReadCache(cfg, sid).read(path, start, end or None, force)}


@_tool(_ann("Run command, compact output", open_world=True))
def run_compact(
    command: Annotated[str, Field(description='Command line, run without a shell, e.g. "pytest -q" or "git log -n 20".')],
    timeout: Annotated[int, Field(ge=1, le=3600, description="Seconds before the command is killed.")] = 600,
) -> dict[str, Any]:
    """Run a command and return output with failures, errors and file:line kept and noise dropped.
    Returns {"exit", "output"}; the output ends with an id for recall() when anything was cut."""
    cfg, _ = _ctx()
    code, out = run_filtered(command, cfg.root, cfg.state / "raw", timeout)
    return {"exit": code, "output": out}


@_tool(_ann("Full output by id", read_only=True))
def recall(output_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{1,64}$", description='The id printed by run_compact, e.g. "3f9a1c2b7d4e".')]) -> dict[str, Any]:
    """Return the full raw output that run_compact or the shell-output filter shortened."""
    cfg, _ = _ctx()
    p = cfg.state / "raw" / output_id
    if not p.exists():
        raise ValueError(f"unknown output id {output_id!r}. Hint: use the id from the last line of run_compact output.")
    return {"id": output_id, "output": p.read_text(errors="replace")}


@_tool(_ann("Outline a file", read_only=True))
def outline(path: Annotated[str, Field(description='Project-relative path, e.g. "src/cart.py".')]) -> dict[str, Any]:
    """Signatures and classes with line numbers. Read this before reading a whole file."""
    cfg, sid = _ctx()
    return {"path": path, "outline": _outline(ReadCache(cfg, sid).resolve(path))}


@_tool(_ann("Project map", read_only=True))
def project_map() -> dict[str, Any]:
    """Files per directory with approximate token sizes. Start here in an unfamiliar repo."""
    cfg, _ = _ctx()
    return {"map": _project_map(cfg.root)}


@_tool(_ann("Find a definition", read_only=True))
def find_symbol(name: Annotated[str, Field(min_length=1, description='Function, class or type name, e.g. "Cart".')]) -> dict[str, Any]:
    """Where is a symbol defined? Returns {"matches": ["path:line: signature", ...]}."""
    cfg, _ = _ctx()
    text = _find_symbol(cfg.root, name)
    return {"name": name, "matches": [ln for ln in text.splitlines() if ln.strip() and ":" in ln]}


@_tool(_ann("Token usage", read_only=True))
def usage_report(by: Annotated[Literal["day", "model", "agent"], Field(description="How to group rows.")] = "day") -> dict[str, Any]:
    """Token usage and cost from local Claude Code, Codex and OpenCode logs. Cost is null for unpriced models."""
    cfg, _ = _ctx()
    rows = usage_collect(cfg.raw.get("prices", {}), by=by)
    return {"by": by, "rows": [{"key": k, "input": r.input, "output": r.output, "cache_read": r.cache_read,
                                "cache_write": r.cache_write, "cost_usd": round(r.cost, 4) if r.priced else None}
                               for k, r in rows.items()]}


@_tool(_ann("Which model for a subtask", read_only=True))
def route_task(
    task: Annotated[str, Field(description='The subtask, e.g. "summarise these 30 log files".')],
    n_files: Annotated[int, Field(ge=0, description="How many files it touches.")] = 0,
) -> dict[str, Any]:
    """Suggest the strong or the cheap model for a subtask (a transparent keyword heuristic, not a model call)."""
    return route(task, n_files)


# ---------------------------------------------------------------- swarm
@_tool(_ann("Run helper tasks", open_world=True))
async def swarm(
    tasks: Annotated[list[dict[str, Any]], Field(min_length=1, description=(
        'Each: {"kind": "ask"|"summarize"|"draft_edit"|"grep", "prompt": str, "files": [paths]}. '
        'Example: [{"kind": "ask", "prompt": "Where is the discount applied?", "files": ["cart.py"]}]'))],
) -> dict[str, Any]:
    """Run many small tasks on the configured helper model in parallel and check each answer:
    citations (path:line) must exist, drafts must pass `git apply --check` (never applied).
    With no helper model configured, returns {"mode": "plan"} for your own subagents instead."""
    cfg, _ = _ctx()
    ts = [Task(kind=t.get("kind", "ask"), prompt=t.get("prompt", ""), files=list(t.get("files", []))) for t in tasks]
    try:
        sw = Swarm(cfg)
    except KeyError:
        sw = None
    if sw is None or sw.model.get("model") in ("", "set-me", None):
        return {"mode": "plan", "plan": subagent_plan(ts)}
    results = await sw.run(ts)
    return {"mode": "ran", "verified": sum(r.verified for r in results), "total": len(results),
            "results": [{"id": r.id, "kind": r.kind, "ok": r.ok, "verified": r.verified, "notes": r.notes,
                         "output": r.output[:1500], "tokens_in": r.tokens_in, "tokens_out": r.tokens_out} for r in results]}


@_tool(_ann("Verify a helper answer", read_only=True))
def swarm_verify(
    answer: Annotated[str, Field(description="The answer or unified diff to check.")],
    files: Annotated[list[str], Field(description='Files the answer may cite, e.g. ["cart.py"].')] = [],  # noqa: B006
    kind: Annotated[Literal["ask", "draft_edit"], Field(description='"ask": check path:line citations; "draft_edit": check the patch applies.')] = "ask",
) -> dict[str, Any]:
    """Verify an answer from any helper, including your own subagents. Returns {"verified", "notes"}."""
    cfg, _ = _ctx()
    if kind == "draft_edit":
        ok, _, notes = verify_patch(cfg.root, answer)
    else:
        ok, notes = verify_citations(cfg.root, answer, files)
    return {"verified": ok, "notes": notes}


# ---------------------------------------------------------------- memory
@_tool(_ann("Search past sessions", read_only=True))
def memory_search(
    query: Annotated[str, Field(min_length=1, description='Words to look for, e.g. "stripe webhook signature".')],
    this_project_only: Annotated[bool, Field(description="Only sessions that ran in this project.")] = True,
    budget_chars: Annotated[int, Field(ge=200, le=20000, description="Max characters of snippets returned.")] = 2400,
) -> dict[str, Any]:
    """Search past Claude Code, Codex and OpenCode sessions. New sessions are indexed first.
    Returns {"hits": [{"agent", "session", "project", "ts", "role", "snippet"}]}."""
    cfg, _ = _ctx()
    m = Memory()
    m.ingest()
    return {"query": query, "hits": m.search(query, str(cfg.root) if this_project_only else None, budget_chars)}


@_tool(_ann("keelyard status", read_only=True))
def status() -> dict[str, Any]:
    """One call to orient yourself: version, project root, snapshot count, proof state."""
    cfg, sid = _ctx()
    steps = Shadow(cfg).steps()
    pf = Proof(cfg, sid)
    return {"version": __version__, "root": str(cfg.root), "session": sid, "steps": len(steps),
            "last_step": _step(steps[-1]) if steps else None, "proven": not pf.missing(), "missing": pf.missing()}


def main() -> None:
    import logging

    for name in ("httpx", "httpcore", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
