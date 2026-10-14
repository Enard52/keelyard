"""The agent interface, end to end: a scripted MCP client + Claude-style hooks complete a task."""

import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from keelyard import selftest


def test_scripted_agent_completes_full_workflow():
    rep = selftest.run()
    failed = [f"{c.name}: {c.detail}" for c in rep.checks if not c.ok]
    assert not failed, failed
    assert len(rep.checks) >= 10


async def _tools(project, which="all"):
    env = {**os.environ, "KEELYARD_MCP_TOOLS": which} if which else {k: v for k, v in os.environ.items() if k != "KEELYARD_MCP_TOOLS"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "keelyard.cli", "mcp"], cwd=str(project), env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        return (await s.list_tools()).tools


def test_every_tool_and_parameter_is_described(project):
    tools = asyncio.run(_tools(project))
    assert len(tools) >= 20
    for t in tools:
        assert t.description and len(t.description) > 40, t.name
        ann = getattr(t, "annotations", None)
        assert ann is not None and ann.title, t.name
        schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
        for name, prop in schema.get("properties", {}).items():
            assert prop.get("description"), f"{t.name}.{name} has no description"
        out = getattr(t, "output_schema", None) or getattr(t, "outputSchema", None)
        assert out is not None, f"{t.name} has no output schema"


def test_default_toolset_is_small_and_cheap(project):
    """Every schema is sent in every session: the default exposes only the workflow tools, without pydantic titles."""
    import json

    tools = asyncio.run(_tools(project, None))
    names = {t.name for t in tools}
    assert names == {"proof_requirements", "proof_check", "proof_run_tests", "proof_status", "rewind_list", "rewind_to",
                     "read_file", "run_compact", "recall", "find_symbol", "memory_search", "swarm", "workflow"}
    size = sum(len(json.dumps(t.model_dump(exclude_none=True, by_alias=True))) for t in tools) // 4
    every = sum(len(json.dumps(t.model_dump(exclude_none=True, by_alias=True))) for t in asyncio.run(_tools(project))) // 4
    assert size < every * 0.7, (size, every)
    assert '"title": "Path"' not in json.dumps([t.model_dump(by_alias=True) for t in tools])


def test_workflow_tool_returns_guides(project):
    from keelyard import mcp_server

    out = mcp_server.workflow("debug")
    assert "Reproduce" in out["steps"]
