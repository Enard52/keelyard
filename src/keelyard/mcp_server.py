"""MCP stdio server exposing all five modules to any MCP-capable agent."""

from __future__ import annotations

import json

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

from . import config, session
from .memory import Memory, format_hits
from .proof import Proof
from .report import render
from .saver import ReadCache, compress_output, route
from .saver import run_compact as _run_compact
from .snapshot import Shadow
from .swarm import Swarm, Task, format_results, subagent_plan, verify_citations, verify_patch

INSTRUCTIONS = """keelyard keeps you honest and cheap.
Before saying a task is done: proof_requirements (list the user's asks), make the change,
proof_run_tests phase=after, proof_check each requirement with concrete evidence, proof_screenshot for web apps.
Prefer read_file over re-reading files, run_compact for noisy commands, memory_search before re-deriving past fixes,
and swarm for bulk read/summarise/draft work. Use rewind_list/rewind_to if you broke something."""

mcp = _Server("keelyard", instructions=INSTRUCTIONS)


def _ctx():
    cfg = config.load()
    return cfg, session.current(cfg)


# ---------------------------------------------------------------- proof
@mcp.tool()
def proof_requirements(items: list[str]) -> str:
    """Record the user's requirements as a checklist (one short item each). Call at the start of a task."""
    cfg, sid = _ctx()
    return json.dumps(Proof(cfg, sid).add_requirements(items), indent=1)


@mcp.tool()
def proof_check(requirement_id: int, evidence: str) -> str:
    """Mark a requirement verified. Evidence must say what you ran or observed (command, output, file:line)."""
    cfg, sid = _ctx()
    return json.dumps(Proof(cfg, sid).check(requirement_id, evidence))


@mcp.tool()
def proof_run_tests(phase: str = "after", command: str = "") -> str:
    """Run the project's tests and record the result as evidence. phase: 'before' or 'after' your change."""
    cfg, sid = _ctx()
    r = Proof(cfg, sid).run_tests(phase, command or None)
    return f"exit={r['exit']} in {r['seconds']}s\n{compress_output(r['tail'], 3000)}"


@mcp.tool()
def proof_screenshot(url: str = "") -> str:
    """Screenshot the running web app (Playwright) and attach it to the proof bundle."""
    cfg, sid = _ctx()
    return json.dumps(Proof(cfg, sid).screenshot(url or None))


@mcp.tool()
def proof_status() -> str:
    """What is still missing before the proof gate lets you finish, plus the HTML report path."""
    cfg, sid = _ctx()
    pf = Proof(cfg, sid)
    gaps = pf.missing()
    return ("PROVEN" if not gaps else "MISSING:\n- " + "\n- ".join(gaps)) + f"\nreport: {render(pf)}"


# ---------------------------------------------------------------- rewind
@mcp.tool()
def rewind_list(last: int = 20) -> str:
    """List recent workspace snapshots (one per edit/shell tool call)."""
    cfg, _ = _ctx()
    steps = Shadow(cfg).steps()[-last:]
    return "\n".join(f"#{s.step} {s.tool} {', '.join(s.files[:5])}" for s in steps) or "no snapshots yet"


@mcp.tool()
def rewind_diff(step: int) -> str:
    """Show what changed at a snapshot step."""
    cfg, _ = _ctx()
    return compress_output(Shadow(cfg).diff(step), 8000)


@mcp.tool()
def rewind_to(step: int) -> str:
    """Restore the workspace files to a snapshot step. A safety snapshot is taken first, so this is undoable."""
    cfg, _ = _ctx()
    return json.dumps(Shadow(cfg).rewind(step))


# ---------------------------------------------------------------- saver
@mcp.tool()
def read_file(path: str, start: int = 1, end: int = 0, force: bool = False) -> str:
    """Read a project file. Repeat reads of an unchanged file return a one-line notice; changed files return a diff."""
    cfg, sid = _ctx()
    return ReadCache(cfg, sid).read(path, start, end or None, force)


@mcp.tool()
def run_compact(command: str, timeout: int = 600) -> str:
    """Run a command (no shell) and return compressed output: errors kept, noise and repeats collapsed."""
    cfg, _ = _ctx()
    r = _run_compact(cfg, command, timeout)
    return f"exit={r['exit']} ({r['raw_tokens']}→{r['returned_tokens']} approx tokens)\n{r['output']}"


@mcp.tool()
def route_task(task: str, n_files: int = 0) -> str:
    """Suggest whether a subtask needs the strong model or a cheap one (transparent keyword heuristic)."""
    return json.dumps(route(task, n_files))


# ---------------------------------------------------------------- swarm
@mcp.tool()
async def swarm(tasks: list[dict]) -> str:
    """Run many cheap helper tasks in parallel and verify them.
    Each task: {"kind": "ask"|"summarize"|"draft_edit"|"grep", "prompt": str, "files": [paths]}.
    Answers must cite path:line (checked); drafts are checked with git apply --check and never applied."""
    cfg, _ = _ctx()
    ts = [Task(kind=t.get("kind", "ask"), prompt=t.get("prompt", ""), files=list(t.get("files", []))) for t in tasks]
    try:
        sw = Swarm(cfg)
    except KeyError:
        return subagent_plan(ts)
    if sw.model.get("model") in ("", "set-me"):
        return subagent_plan(ts)
    return format_results(await sw.run(ts))


@mcp.tool()
def swarm_verify(answer: str, files: list[str], kind: str = "ask") -> str:
    """Verify an answer from any helper (including your own subagents): citations for 'ask', patch applicability for 'draft_edit'."""
    cfg, _ = _ctx()
    if kind == "draft_edit":
        ok, _, notes = verify_patch(cfg.root, answer)
    else:
        ok, notes = verify_citations(cfg.root, answer, files)
    return ("VERIFIED" if ok else "UNVERIFIED") + (": " + "; ".join(notes) if notes else "")


# ---------------------------------------------------------------- memory
@mcp.tool()
def memory_search(query: str, this_project_only: bool = True, budget_chars: int = 2400) -> str:
    """Search past Claude Code / Codex / OpenCode sessions for how something was done before. Returns short snippets."""
    cfg, _ = _ctx()
    m = Memory()
    m.ingest()
    return format_hits(m.search(query, str(cfg.root) if this_project_only else None, budget_chars))


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
