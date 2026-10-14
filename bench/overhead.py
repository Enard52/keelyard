"""Measure the tokens keelyard itself adds to an agent session, and the net savings.

Tokens are estimated as characters / 4 of compact JSON or text (the same estimate keelyard uses everywhere).
Savings come from bench/vs_rtk_results.json (measured on real command logs), not from assumptions.
Writes bench/overhead.json and prints a table.
"""
from __future__ import annotations

import json
import sys
import tempfile
from importlib import resources
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from keelyard import brain, config, mcp_server  # noqa: E402
from keelyard.adapters import install  # noqa: E402


def tok(text: str) -> int:
    return round(len(text) / 4)


def schema_tokens(selection) -> tuple[int, int]:
    names = mcp_server.configure_tools(selection)
    tools = mcp_server.mcp._tool_manager._tools
    sent = [{"name": t.name, "description": t.description, "inputSchema": t.parameters} for t in tools.values()]
    return len(names), tok(json.dumps(sent, separators=(",", ":")))


def main() -> int:
    n_all, all_t = schema_tokens("all")
    n_core, core_t = schema_tokens("core")
    guides = resources.files("keelyard.adapters") / "guides"
    agents_block = tok((guides / "agents_block.md").read_text())
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "app.py").write_text("def f():\n    return 1\n")
        cfg = config.load(Path(d))
        fresh_brief = tok(brain.brief(cfg, "s1"))
    workflow = {n: tok(install.workflow_text(n)) for n in install.WORKFLOWS}
    fixed = {
        "mcp_tool_schemas_core": core_t,
        "mcp_instructions": tok(mcp_server.INSTRUCTIONS),
        "agents_md_block": agents_block,
        "session_brief_fresh_project": fresh_brief,
    }
    per_session_min = sum(fixed.values())
    brief_cap = int(cfg.section("brain")["brief_tokens"])
    rows = json.load(open(ROOT / "bench" / "vs_rtk_results.json"))
    saved = [r["raw_tokens"] - r["keelyard_tokens"] for r in rows]
    out = {
        "tool_count": {"core": n_core, "all": n_all},
        "schema_tokens": {"core": core_t, "all": all_t},
        "per_session_fixed": fixed,
        "per_session_total_fresh": per_session_min,
        "brief_cap": brief_cap,
        "on_demand_workflow_tokens": workflow,
        "filter_saving_per_command": dict(zip([r["command"] for r in rows], saved, strict=True)),
        "filter_saving_total_8_commands": sum(saved),
        "net_after_8_commands_fresh": sum(saved) - per_session_min,
        "commands_to_break_even_median": None,
    }
    s = sorted(saved)
    med = s[len(s) // 2]
    out["commands_to_break_even_median"] = -(-per_session_min // med) if med > 0 else None
    (ROOT / "bench" / "overhead.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
