"""Spawn the real MCP stdio server and drive it with the official MCP client."""

import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _text(result):
    return "".join(getattr(c, "text", "") for c in result.content)


async def _drive(project):
    params = StdioServerParameters(command=sys.executable, args=["-m", "keelyard.cli", "mcp"], cwd=str(project),
                                   env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert {"proof_requirements", "proof_check", "proof_run_tests", "proof_status", "rewind_list", "rewind_to",
                    "read_file", "run_compact", "swarm", "swarm_verify", "memory_search", "route_task", "outline", "project_map",
                    "find_symbol", "recall", "usage_report"} <= names

            out = _text(await s.call_tool("proof_requirements", {"items": ["add works"]}))
            assert "add works" in out
            first = _text(await s.call_tool("read_file", {"path": "app.py"}))
            assert "return a + b" in first
            again = _text(await s.call_tool("read_file", {"path": "app.py"}))
            assert "unchanged" in again
            tests = _text(await s.call_tool("proof_run_tests", {"phase": "after", "command": f"{sys.executable} -m pytest -q"}))
            assert tests.startswith("exit=0")
            v = _text(await s.call_tool("swarm_verify", {"answer": "see app.py:2 `return a + b`", "files": ["app.py"]}))
            assert v.startswith("VERIFIED")
            plan = _text(await s.call_tool("swarm", {"tasks": [{"kind": "ask", "prompt": "q", "files": ["app.py"]}]}))
            assert "subagents" in plan  # default config has no real strong/cheap key -> plan for own subagents
            mem = _text(await s.call_tool("memory_search", {"query": "anything"}))
            assert "No matching memory" in mem
            return names


def test_mcp_stdio_roundtrip(project, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text('[models.cheap]\nprovider="openai"\nbase_url="http://x"\nmodel=""\n')
    names = asyncio.run(_drive(project))
    assert len(names) >= 12
