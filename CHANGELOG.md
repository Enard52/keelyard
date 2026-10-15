# Changelog

## 0.1.0 (unreleased)

### OpenCode 2
- The OpenCode plugin supports OpenCode 2.x (`setup(ctx)`: context, compaction, prompt, tool and event hooks, MCP via
  `ctx.mcp.transform`) and 1.x (`server()`) from one file, now installed to `.opencode/plugins/keelyard.js`
- Fix: shell output from OpenCode (`bash`) and Codex (`shell`) was never filtered; only Claude's `Bash` was

### Cooperative swarm
- `keelyard.coop`: planner -> workers -> verifier with a shared blackboard, a optional peer critic, voting, cheapest-capable
  model routing (`[swarm].ladder`), and hard token budgets (`budget_tokens`, `task_budget_tokens`) enforced by
  reserving each call's worst case before it is sent. On by default (`cooperative = true`, `--basic` to opt out)
- Tested with 250 tasks and more than 200 calls in flight; token totals match exactly

### Smaller footprint, workflow pack
- MCP server exposes 13 core tools by default (`[mcp] tools = "core"`, or `"all"`, or a list); schemas
  drop pydantic titles. Measured: 1,582 vs 2,401 tokens per session (`bench/overhead.py`)
- Workflow pack: `workflow("plan"|"debug"|"review")` MCP tool, `/keelyard:plan|debug|review` for Claude Code,
  `keelyard-*` commands for OpenCode; installed by `init`, loaded only when asked for
- Compact guide block and brief rules; "be terse" rule
- Destructive-command check ignores text inside quotes (unless run via `bash -c`, `eval`, `ssh`) and only
  flags SQL when a SQL client is involved
- Snapshots skip keelyard's own wiring files and no longer force-add ignored files in untracked folders
- Screens and hero GIF show `~/` paths; release workflow with PyPI trusted publishing; gitleaks allowlist for test fixtures

### Always on and stronger helpers
- Brief at session start and after compaction, past-session recall per prompt, outline/diff on repeat reads
- Snapshot before destructive commands; rate-limited hints (no tests nearby, session budget); `[brain]` config
- Swarm: `swarm_plan`, context packs, JSON answers, one-definition rewrites, patches tested in a copy,
  best-of-N, retry with feedback, escalation, `subagent_tasks` for the host agent's subagents
- Windows CI; fixes for Windows paths, cp1252 output, CRLF diffs, racing state directory

### CLI overhaul (breaking renames)
- `x` → `run`, `compress` → `filter`, `timeline` → `rewind list -i`, `mem` → `memory`, `sym`/`map`/`outline` → `code find|map|outline`, `proof req` → `proof add`
- New `init` (detects Claude Code, Codex, OpenCode), `doctor`, `status`, `selftest`
- `--json` on every command, stable exit codes (0 ok, 1 error, 2 usage, 3 check failed), errors with hints
- Agent environment: 20 structured MCP tools, CLAUDE.md/AGENTS.md guide block, Claude Code skill and slash commands
- New design: Geist-based proof and arena reports, textual timeline, mkdocs-material docs site
- 35 bugs fixed from adversarial QA (see tests/test_adversarial.py)

### Initial

- Proof gate (Stop hook), HTML proof report
- Rewind: shadow-git snapshots, rewind/fork, curses timeline
- Helper swarm with citation and patch verification
- Saver: read dedupe, command-aware output filters (git, pytest, cargo/go/jest, grep, find, ruff/eslint/mypy),
  Claude Code PostToolUse output replacement, `recall`
- Structure-first reading: `outline`, `project_map`, `find_symbol`
- Unified memory (SQLite FTS5) and usage report across Claude Code, Codex, OpenCode
- Arena: one task across agents/models, tokens/cost/pass rate, HTML (+PNG) report
- Benchmarks: compression corpus, snapshot timing, head-to-head vs rtk with fact retention
