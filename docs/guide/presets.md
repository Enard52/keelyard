# Presets: lowest-token settings

```bash
keelyard init --preset lean          # fewest tokens
keelyard init --preset balanced      # default
keelyard init --preset max-quality   # every keelyard tool over MCP
keelyard uninstall opencode          # reverts the preset too (only what keelyard added)
```

| | lean | balanced | max-quality |
|---|---|---|---|
| Proof | from the agent's own shell test runs | same | MCP proof tools + shell runs |
| Shell output filter | on | on | on |
| OpenCode | `agents.build` override: 1-paragraph system prompt; webfetch, websearch, subagent, skill, question, todowrite, execute (code mode), glob, grep denied; no MCP catalog | no MCP catalog | MCP server added |
| Claude Code | `.claude/settings.json` env: `BASH_MAX_OUTPUT_LENGTH=12000`, `MAX_MCP_OUTPUT_TOKENS=8000`, `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1` (your values win) | hooks + MCP | hooks + MCP |
| Codex | short rules block | hooks | hooks |
| Rules block | 3 lines | 3 lines (OpenCode) / full | full |

keelyard records exactly what it added in `.keelyard/preset.json`; uninstall removes only those keys, and only if
you did not change them. If `opencode.json` already defines `agents.build`, lean leaves it alone.

Trade-offs of lean: the agent has no web access, no subagents and no glob/grep tools (it uses the shell and the
file map in keelyard's brief instead). For Codex, the cheapest effective setting is in your user config, which
keelyard does not touch: `model_reasoning_effort = "low"` for routine fixes.

Measured effect: see [BENCHMARKS](../BENCHMARKS.md#presets-measured-on-opencode-2).
