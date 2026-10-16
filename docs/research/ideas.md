# Research: popular AI coding-agent repos and what keelyard can learn

Collected Oct 16, 2026 with the GitHub API (`gh api repos/<name>`). Ranked by popularity = stars + 3 × forks.
GitHub does not expose view counts for other people's repos, so views are not used. Star counts are what the API
returned that day. Core ideas are taken from each project's README/description; **no code was read or copied**.
Anything keelyard builds from these ideas is written from scratch.

Value column: token savings / quality (H, M, L; '-' = host, list or out of scope). Estimates, not measurements.
Left out on purpose: leaked system-prompt collections, refusal-removal tools, and free-provider gateways.

| # | repo | stars | forks | license | core idea | keelyard has it? | value |
|---|---|---:|---:|---|---|---|---|
| 1 | [affaan-m/ECC](https://github.com/affaan-m/ECC) | 281,253 | 41,819 | MIT | Harness bundle: skills, 'instincts' (learned rules), memory, security checks | partly (rules, memory, guards) | M/M |
| 2 | [anomalyco/opencode](https://github.com/anomalyco/opencode) | 214,287 | 28,758 | MIT | Open-source coding agent (host keelyard supports) | n/a (host) | - |
| 3 | [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | 220,317 | 22,141 | none | One CLAUDE.md: think first, simplicity, surgical changes, goal-driven (tests) execution | partly (proof gate = goal-driven); no 'surgical changes' rule | L/H |
| 4 | [anthropics/claude-code](https://github.com/anthropics/claude-code) | 151,218 | 26,850 | none | Coding agent; hooks, skills, MCP (host keelyard supports) | n/a (host) | - |
| 5 | [garrytan/gstack](https://github.com/garrytan/gstack) | 136,666 | 20,278 | MIT | Opinionated role skills (review, release, QA) for Claude Code | partly (workflow guides) | L/M |
| 6 | [openai/codex](https://github.com/openai/codex) | 129,532 | 20,389 | Apache-2.0 | Coding agent (host keelyard supports) | n/a (host) | - |
| 7 | [github/spec-kit](https://github.com/github/spec-kit) | 141,545 | 12,672 | MIT | Spec-driven development: spec → plan → tasks before code | partly (proof requirements, workflow plan) | L/M |
| 8 | [farion1231/cc-switch](https://github.com/farion1231/cc-switch) | 145,191 | 9,611 | MIT | Desktop switcher for agent configs/providers | no (out of scope) | L/L |
| 9 | [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) | 127,206 | 12,273 | Apache-2.0 | Codebase + docs → queryable knowledge graph | partly (find_symbol, related) | M/M |
| 10 | [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | 96,474 | 17,785 | MIT | Curated MCP server list | n/a (list) | - |
| 11 | [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) | 107,328 | 11,170 | MIT | Production engineering skills as agent instructions | partly (workflows) | L/M |
| 12 | [JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) | 113,042 | 6,540 | Apache-2.0 | Terse output style ('say less'), output/log shrinking, model routing | yes now (terse rule, filters, route) | H/M |
| 13 | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | 101,212 | 8,866 | Apache-2.0 | Captures session activity, compresses it, re-injects relevant context later | yes (memory_search, brief recall, work_state) | M/M |
| 14 | [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | 91,068 | 12,073 | MIT | Autonomous dev agent platform; condensers for long histories | partly (work_state as condensed state) | M/M |
| 15 | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 91,313 | 11,795 | NOASSERTION | Reference MCP servers (filesystem, git, memory, fetch) | partly | L/L |
| 16 | [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) | 78,711 | 12,594 | MIT | Tutorial: build a minimal agent harness | n/a | - |
| 17 | [Egonex-AI/Understand-Anything](https://github.com/Egonex-AI/Understand-Anything) | 86,616 | 7,300 | MIT | Interactive knowledge graph of code for exploration | no (UI) | L/L |
| 18 | [tt-a1i/archify](https://github.com/tt-a1i/archify) | 84,429 | 5,713 | MIT | Agent skill that draws architecture diagrams | no | L/L |
| 19 | [rtk-ai/rtk](https://github.com/rtk-ai/rtk) | 83,615 | 5,310 | Apache-2.0 | CLI proxy that filters dev-command output (60-90% fewer tokens) | yes (keelyard run, output filters; benchmarked vs rtk) | H/M |
| 20 | [cline/cline](https://github.com/cline/cline) | 70,418 | 7,680 | Apache-2.0 | IDE/CLI coding agent; plan/act modes, checkpoints | yes (rewind = checkpoints) | - |
| 21 | [headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom) | 75,514 | 5,865 | Apache-2.0 | Compresses tool output by content type (JSON crusher, code, prose), reversible retrieval, cache-prefix alignment, learn from failures | partly (logs, recall); no JSON-aware compression, no cache-stability check | H/M |
| 22 | [mem0ai/mem0](https://github.com/mem0ai/mem0) | 67,300 | 7,932 | Apache-2.0 | Memory layer: extract facts, store, retrieve | partly (FTS memory, no fact extraction) | M/M |
| 23 | [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) | 54,229 | 6,096 | NOASSERTION | Agile role-based workflow (analyst, PM, architect, dev) | partly (workflows) | L/L |
| 24 | [upstash/context7](https://github.com/upstash/context7) | 63,150 | 3,102 | MIT | Up-to-date library docs fetched on demand for agents | no | M/H |
| 25 | [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | 55,836 | 4,828 | NOASSERTION | Curated Claude Code resources | n/a (list) | - |
| 26 | [Aider-AI/aider](https://github.com/Aider-AI/aider) | 49,583 | 5,064 | Apache-2.0 | Pair-programming agent; ranked repo map (graph-ranked symbols) within a token budget | partly (project_map, find_symbol ranking); no graph-ranked map | H/M |
| 27 | [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | 46,713 | 3,848 | MIT | Indexed code graph MCP: call graph, impact analysis | partly (refs, related) | M/M |
| 28 | [wshobson/agents](https://github.com/wshobson/agents) | 40,912 | 4,340 | MIT | Marketplace of subagents/plugins | no (out of scope) | L/L |
| 29 | [continuedev/continue](https://github.com/continuedev/continue) | 36,231 | 5,479 | Apache-2.0 | Open-source coding agent / IDE assistant | n/a | - |
| 30 | [github/github-mcp-server](https://github.com/github/github-mcp-server) | 33,664 | 5,229 | MIT | GitHub MCP server | no (out of scope) | - |
| 31 | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | 38,239 | 3,262 | Apache-2.0 | Browser automation over MCP via accessibility snapshots | partly (proof_screenshot) | L/M |
| 32 | [musistudio/claude-code-router](https://github.com/musistudio/claude-code-router) | 37,705 | 3,163 | MIT | Route Claude Code requests to other models per task | partly (route_task heuristic) | M/L |
| 33 | [getzep/graphiti](https://github.com/getzep/graphiti) | 31,817 | 3,276 | Apache-2.0 | Temporal knowledge graph memory | no | L/M |
| 34 | [QwenLM/qwen-code](https://github.com/QwenLM/qwen-code) | 28,527 | 3,217 | Apache-2.0 | Coding agent CLI | n/a | - |
| 35 | [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) | 29,586 | 2,606 | Apache-2.0 | Persistent agent memory benchmarked on real sessions | partly (memory) | M/M |
| 36 | [oraios/serena](https://github.com/oraios/serena) | 30,326 | 2,114 | NOASSERTION | Semantic (LSP) code retrieval and symbol-level editing over MCP | partly (regex symbols; no LSP) | H/H |
| 37 | [mksglu/context-mode](https://github.com/mksglu/context-mode) | 30,136 | 2,124 | NOASSERTION | Sandboxed tool output (only summaries enter context), session event log in SQLite, 'think in code' | partly (filters, recall, work_state) | H/M |
| 38 | [eyaltoledano/claude-task-master](https://github.com/eyaltoledano/claude-task-master) | 28,233 | 2,619 | NOASSERTION | PRD → task graph with dependencies for agents | partly (proof requirements) | L/M |
| 39 | [PrefectHQ/fastmcp](https://github.com/PrefectHQ/fastmcp) | 28,106 | 2,478 | Apache-2.0 | Python MCP framework | uses official mcp SDK | - |
| 40 | [OthmanAdi/planning-with-files](https://github.com/OthmanAdi/planning-with-files) | 27,477 | 2,277 | MIT | Plan/findings/progress on disk, re-injected after /clear or compaction | yes (work_state in the brief) | M/H |
| 41 | [yamadashy/repomix](https://github.com/yamadashy/repomix) | 28,867 | 1,618 | MIT | Pack a repo into one AI-friendly file, with token counts | no (opposite approach) | L/L |
| 42 | [gastownhall/beads](https://github.com/gastownhall/beads) | 27,939 | 1,892 | MIT | Issue tracker as agent memory (dependency-aware tasks) | partly (work_state) | L/M |
| 43 | [SuperClaude-Org/SuperClaude_Framework](https://github.com/SuperClaude-Org/SuperClaude_Framework) | 23,909 | 1,992 | MIT | Commands, personas, token-efficiency mode | partly (terse rule, workflows) | L/M |
| 44 | [coleam00/context-engineering-intro](https://github.com/coleam00/context-engineering-intro) | 13,881 | 2,719 | MIT | Context-engineering templates (PRP) | partly | L/L |
| 45 | [ccusage/ccusage](https://github.com/ccusage/ccusage) | 19,031 | 879 | NOASSERTION | Token/cost usage from local agent logs | yes (keelyard usage) | - |
| 46 | [plandex-ai/plandex](https://github.com/plandex-ai/plandex) | 15,747 | 1,180 | MIT | Agent for large tasks; sandboxed diffs reviewed before apply | partly (rewind) | L/M |
| 47 | [ast-grep/ast-grep](https://github.com/ast-grep/ast-grep) | 16,250 | 477 | MIT | Structural (AST) code search and rewrite | no (regex search) | M/H |
| 48 | [BeehiveInnovations/pal-mcp-server](https://github.com/BeehiveInnovations/pal-mcp-server) | 11,785 | 1,035 | NOASSERTION | Ask other models (second opinion) from your agent | partly (swarm) | L/M |
| 49 | [microsoft/LLMLingua](https://github.com/microsoft/LLMLingua) | 6,756 | 438 | MIT | Learned prompt compression (drop low-information tokens) | no (needs a model; risky for code) | M/L |
| 50 | [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery) | 3,943 | 632 | none | Examples of every Claude Code hook | yes (keelyard uses hooks) | - |
| 51 | [graykode/abtop](https://github.com/graykode/abtop) | 3,752 | 341 | MIT | htop for agent sessions: tokens, context %, rate limits | partly (usage) | L/L |
| 52 | [liaohch3/claude-tap](https://github.com/liaohch3/claude-tap) | 3,289 | 285 | MIT | Intercept and inspect agent API traffic | no | L/L |
| 53 | [sourcegraph/zoekt](https://github.com/sourcegraph/zoekt) | 1,969 | 253 | Apache-2.0 | Trigram code search index | no (git grep) | L/L |
| 54 | [tickernelz/opencode-mem](https://github.com/tickernelz/opencode-mem) | 1,758 | 176 | MIT | OpenCode memory with local vector DB | partly (FTS memory) | L/L |
| 55 | [vshulcz/deja-vu](https://github.com/vshulcz/deja-vu) | 1,219 | 125 | MIT | Memory built from existing session history on disk | yes (memory ingests Claude/Codex/OpenCode logs) | - |
| 56 | [cased/kit](https://github.com/cased/kit) | 1,308 | 85 | MIT | Toolkit: code maps, symbol extraction, context assembly | partly | L/M |
| 57 | [riponcm/projectmem](https://github.com/riponcm/projectmem) | 865 | 53 | MIT | Records failed attempts/fixes and warns the agent before it repeats one | no | M/H |

## Top 10 ideas keelyard lacked, ranked by source popularity × estimated value

| # | idea | from | status in keelyard |
|---|---|---|---|
| 1 | Terse output rule: results only, code/errors kept exact | caveman, SuperClaude | **built**: in every preset, opt out with `--no-terse`/`KEELYARD_TERSE=0`; measured in `bench/terse.py` |
| 2 | Content-aware compression of JSON tool output | headroom | **built**: lossless (minified, same-key lists as columns/rows), only when output is JSON and it is smaller |
| 3 | Warn before repeating a failed attempt | projectmem | **built**: one hint, only when the same failure returns after a code change |
| 4 | Keep injected context byte-stable so the prompt cache stays warm | headroom (cache alignment) | **checked**: test that the brief is deterministic and has no timestamps |
| 5 | Plan/state on disk re-injected after compaction | planning-with-files, context-mode | already built (`work_state`, previous round) |
| 6 | "Surgical changes, simplicity first" rules | andrej-karpathy-skills | not built: adds tokens every turn; quality effect not measurable here at $0 |
| 7 | Graph-ranked repo map within a token budget | aider | not built yet; `find_symbol`/`related` cover lookups |
| 8 | Structural (AST) search | ast-grep, serena | not built: needs parsers per language |
| 9 | Up-to-date library docs on demand | context7 | not built: network service, out of scope |
| 10 | Learn corrections from failed sessions into the rules file | headroom learn | not built: needs a model to summarise; revisit with the local model |
