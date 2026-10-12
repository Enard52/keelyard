# Changelog

## 0.1.0 (unreleased)

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
