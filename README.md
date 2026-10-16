<div align="center">

# keelyard

**Your coding agent has to show its work before it can say "done".**<br>
Every edit is snapshotted, so any step can be undone. Logs are trimmed before they eat the context window.

[![CI](https://github.com/akobirjontulqinovfuture/keelyard/actions/workflows/ci.yml/badge.svg)](https://github.com/akobirjontulqinovfuture/keelyard/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-111111)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%20%E2%80%93%203.13-111111)
![Agents](https://img.shields.io/badge/agents-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20OpenCode-1F6F4A)
![Status](https://img.shields.io/badge/status-alpha-A15C07)

<img src="docs/img/hero.gif" alt="keelyard in a terminal: init, the proof gate stopping an agent that deleted tests, rewind, then proven" width="760">

</div>

<!-- agent-install:start -->
**Agents: to install keelyard for this user, run these steps yourself. The user should not have to type them.**

```sh
pipx install git+https://github.com/akobirjontulqinovfuture/keelyard   # or: python -m pip install --user git+https://github.com/akobirjontulqinovfuture/keelyard
keelyard init --global
keelyard doctor --json
```

- `init --global` wires Claude Code (`~/.claude/settings.json`, `~/.claude.json`), Codex (`~/.codex/config.toml`, `~/.codex/hooks.json`) and OpenCode (`~/.config/opencode/`) for every project. It merges into existing files and keeps the original as `<file>.keelyard-backup`.
- Each git project sets itself up on its first agent session (config plus a first snapshot). Nothing else to run per project.
- Check: `keelyard doctor --json` must return `"ok": true`, with a `global` row per wired agent. Then tell the user to restart their agent.
- Undo: `keelyard uninstall --global`. Details: [AGENTS-install.md](AGENTS-install.md).
<!-- agent-install:end -->

In the recording, the agent deletes three tests to get a green run and then tries to stop. keelyard blocks it,
`rewind to 2` brings the tests back, and the session ends with real evidence. Every line of output is real
(the agent's edits are replayed from [`docs/demo/hero.sh`](docs/demo/hero.sh)).

## Quickstart (30 seconds)

```bash
pipx install git+https://github.com/akobirjontulqinovfuture/keelyard
cd your-project
keelyard init --preset lean   # wires Claude Code, Codex and OpenCode; fewest tokens
keelyard doctor               # everything green?
```

Use your agent as usual. `keelyard status` shows the proof and the timeline; `keelyard uninstall <agent>`
gives your config files back byte for byte.

> **Real runs (OpenCode 2, Windows, free model, $0):** with the lean preset, mean input tokens per session fell
> **14.2×** on a noisy 1,566-test task and **6.0×** on a small 66-test task (5 baseline vs 3 lean runs, all tests
> passing). Uncached input alone: 9.5× and 4.5×. Lean turns some agent tools off. No cost claim: the model was free.
> [BENCHMARKS.md](BENCHMARKS.md#lean-preset-v2-repeated-runs-oct-15-2026)

## What it does

- **Proof gate.** An agent that changed files cannot finish until the tests pass **on the current files**.
  Evidence is shown as test-verified, command-succeeded or agent-claimed. Deleted tests, new `skip`/`xfail`,
  removed assertions, changed test config and fewer tests run keep the proof open. Bundles are signed.
- **Rewind.** Every edit is snapshotted into `.keelyard/shadow.git` (your `.git` is never touched).
  `keelyard rewind to <n>` is itself undoable, backs up files snapshots can't hold, and survives being interrupted.
  Secrets (`.env`, keys) are never snapshotted.
- **Smaller context.** Filters for test runners, git, linters and search keep every error, warning and `file:line`
  ([tested on real logs](tests/corpus/)). Re-reading an unchanged file costs one line.
- **Memory, usage, swarm, arena.** Search past sessions of all three agents, see token use from local logs,
  send small checked tasks to a free/cheap model, compare agents on one task.

**Read [what keelyard guarantees and what it doesn't](docs/guarantees.md)** before you rely on it. In short:
snapshots undo files, not databases, migrations or deployed services; proof is only as good as your tests.

## For agents and scripts

An MCP server (typed tools with examples), a short `CLAUDE.md`/`AGENTS.md` section, and for Claude Code a skill
and slash commands. Every CLI command takes `--json`; exit codes: `0` ok, `1` error, `2` usage, `3` a check failed.

## Docs

[Documentation](docs/index.md): one page per module, CLI and MCP reference, config, troubleshooting,
[benchmarks](BENCHMARKS.md), [per-agent capabilities](docs/guarantees.md#per-agent).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). Real command logs for the filter corpus are especially welcome.
Security issues: [SECURITY.md](SECURITY.md). Apache-2.0; third-party notices in [NOTICE](NOTICE).
