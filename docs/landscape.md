# Landscape

Tools people use to make coding agents cheaper or more reliable, and what keelyard took from them.
"Measured" means we ran it; everything else is the project's own claim or a description, not our number.
Stars and licenses from GitHub, October 2026.

| project | stars | license | technique | effect | in keelyard |
|---|---|---|---|---|---|
| rtk | 83k | Apache-2.0 | per-command output filters | measured: 56,522 → 5,747 tokens on our 8 commands (keelyard: 5,901) | `run`, `filter`, `run_compact` (own code) |
| repomix | 28.8k | MIT | pack repo, compress to structure | claimed large reductions; not measured | `code outline`, `project_map` |
| aider | 49.5k | Apache-2.0 | ranked repo map | described; not measured | `project_map`, swarm context packs |
| serena | 30k | see repo | symbol-level find/edit over LSP | described; not measured | `find_symbol`, `read_file` ranges |
| context7 | 63k | MIT | fetch current library docs on demand | described; not measured | not adopted (network service, off-mission) |
| code2prompt | 7.7k | MIT | repo to prompt with templates | described | not adopted (overlaps repomix idea) |
| LLMLingua | 6.8k | MIT | model-based prompt compression | paper claims up to 20x | not adopted (needs a model at runtime) |
| caveman | 111.8k | Apache-2.0 | terse-reply rule | claimed output savings; not measured | one "Be terse" rule |
| claude-context | 12.6k | MIT | vector code search via MCP | described | not adopted (needs embedding service) |
| ccusage | 19k | see repo | usage from local logs | n/a | `usage` (own code) |
| superpowers | 299k | MIT | skills: plan, debug, review workflows | n/a | workflow pack, lazy (240/181/182 tokens on demand) |
| spec-kit | 141k | MIT | spec → plan → tasks | n/a | `proof add` requirements + plan workflow |
| claude-task-master | 28k | see repo | task lists for agents | n/a | covered by proof requirements |
| claude-code-router | 37.7k | MIT | route requests to cheaper models | n/a | `route_task`, swarm escalation |
| playwright-mcp | 38k | Apache-2.0 | browser control for agents | n/a | `proof_screenshot` (optional extra) |

