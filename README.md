# keelyard

**A local trust-and-thrift layer for AI coding agents.** keelyard plugs into Claude Code, Codex and
OpenCode through their hooks and MCP, and adds five things they do not do on their own:

| Module | What it does |
|---|---|
| **Proof** | A Stop-hook gate. If the agent changed files, it can't finish until it has recorded a requirement checklist, a passing test run made *after* its last edit and, for web apps, a screenshot. You get a self-contained HTML report. |
| **Rewind** | A shadow git repo (`.keelyard/shadow.git`) snapshots the worktree after every edit or shell call. You can list, diff, rewind and fork by step, from a TUI or the CLI. It never touches your own `.git`. |
| **Swarm** | The main agent hands bulk read/summarise/draft work to many parallel helper calls on a cheap or local model (any OpenAI-compatible or Anthropic API). Answers must cite `path:line` and are checked; draft patches are checked with `git apply --check` and never applied. With no helper model set, it hands back a plan for the agent's own subagents. |
| **Saver** | Saves tokens *inside* the agent, so it works on subscription plans: repeat reads of unchanged files are blocked (reset on compaction), changed files come back as diffs, noisy command output is compressed, and a transparent router suggests cheap vs strong model per subtask. |
| **Memory** | Reads your Claude Code, Codex and OpenCode transcripts, redacts secrets, and indexes them in local SQLite FTS5. `memory_search` returns short snippets under a character budget. |

Everything runs locally. Nothing is sent anywhere unless you configure a helper model for Swarm.

> Status: alpha (0.1). The Claude Code hook format and the MCP stdio server are tested end to end.
> The Codex and OpenCode adapters follow their documented formats but have not been run against
> those agents yet. See [Verified vs not verified](#verified-vs-not-verified).

## Install

```bash
pip install keelyard            # or: uv tool install keelyard   (not on PyPI yet: pip install git+https://github.com/akobirjontulqinovfuture/keelyard)
cd your-project
keelyard install claude         # writes .claude/settings.json hooks + .mcp.json
keelyard install codex          # writes .codex/hooks.json; prints the MCP snippet for ~/.codex/config.toml
keelyard install opencode       # writes .opencode/plugin/keelyard.js + opencode.json
```

Installs are idempotent and merge with the config you already have. All settings live in `.keelyard/config.toml`.
keelyard writes a `.gitignore` into `.keelyard/` so none of its state is ever committed.

## Try it in 10 seconds

```bash
bash examples/demo.sh
```

This replays the exact JSON Claude Code sends to hooks, in a throwaway repo. The "agent" edits a file and
deletes the tests. When it tries to stop, the gate blocks it. Then you rewind the deletion but keep
the edit, record proof, and the gate opens and writes `report.html`.

## CLI

```text
keelyard proof status|req|check|test|shot|report
keelyard timeline [-i]          # -i = curses TUI: enter = diff, r = rewind
keelyard diff N | rewind N | fork N DIR | snapshot
keelyard swarm tasks.json [--model cheap]
keelyard mem ingest|search "query"|stats
keelyard compress < build.log
keelyard bench                  # measures savings on *your* machine and transcripts
```

MCP tools: `proof_requirements`, `proof_check`, `proof_run_tests`, `proof_screenshot`, `proof_status`,
`rewind_list`, `rewind_diff`, `rewind_to`, `read_file`, `run_compact`, `route_task`, `swarm`,
`swarm_verify`, `memory_search`.

## Models

Model names are plain strings in your config; keelyard does not ship assumptions about any vendor's lineup.

```toml
[models.cheap]                  # used by Swarm helpers
provider = "openai"             # any OpenAI-compatible /chat/completions (Ollama, vLLM, OpenRouter, ...)
base_url = "http://localhost:11434/v1"
model = "qwen2.5-coder:7b"
api_key_env = ""                # name of an env var; keys are never stored in config

[models.strong]
provider = "anthropic"
model = "whatever-you-use"
api_key_env = "ANTHROPIC_API_KEY"
```

## Measured numbers

Every number here comes from `keelyard bench` or a script in this repo, run on an 8-core Linux box with
no GPU. Token counts are approximate (`chars / 4`) and are only meant for comparisons. Full detail is in
[docs/BENCHMARKS.md](docs/BENCHMARKS.md).

| What | Result |
|---|---|
| `compress_output` on 6 real build/test logs in `bench/corpus/` | 8,900 → 4,263 approx tokens (−52.1%). Big wins on progress-heavy logs (git clone −90%, failing pytest −64%, npm −58%); **no gain** on short pip, cargo and passing-pytest logs. |
| Snapshot after a one-file edit, 36-file repo | median 11.0 ms |
| Snapshot after a one-file edit, Django (7,083 files) | first snapshot 2.09 s, then median 71.7 ms (max 113.6 ms) |
| Swarm, 12 tasks, local qwen2.5-coder 1.5B (Q4, CPU) | 4 min 15 s; 3/12 verified (2 local greps + 1 of 2 patches). **0/8 Q&A answers had valid citations**, and the verifier flagged all 8. Small local models are too weak for cited answers, so use a 7B+ or hosted cheap model. |
| Swarm fan-out (mock server, test suite) | 200 tasks, concurrency cap of 50 respected, 20 planted bad citations caught out of 20 |

Not measured yet: read-dedupe and memory savings on real transcripts. The harness for both is in
`keelyard bench`, but the build machine had no agent transcripts. Run it on yours.

## Verified vs not verified

- **Verified (automated tests, 21 passing):** Claude Code hook JSON in and out through the real CLI binary; MCP
  stdio server driven by the official MCP Python client; snapshot, rewind, undo-rewind and fork; the proof gate lifecycle
  including failing tests and the max-reminders escape; read dedupe and diffs; compaction reset; secret redaction;
  transcript parsing for all three agents (from fixture files shaped like their formats); installers.
- **Not verified yet:** a live Claude Code, Codex or OpenCode session. The OpenCode plugin API usage
  (`tool.execute.*`, `session.idle`, `client.session.prompt`) and Codex hooks (Claude-compatible
  `hooks.json`; Codex asks you to trust new hooks via `/hooks`) are written from their docs. Playwright screenshots
  need `pip install 'keelyard[web]' && playwright install chromium` and are not covered by CI.

## Security

- Local-first: state lives in `.keelyard/` (git-ignored) and `$XDG_DATA_HOME/keelyard/memory.db` (mode 600).
- Secrets (API keys, tokens, private keys, URL credentials, `*_SECRET=` assignments) are redacted before
  anything is written to memory, the proof bundle or the swarm prompts.
- `read_file` refuses paths outside the project and keelyard's own state. Commands run without a shell.
- Swarm never applies patches. Hooks never crash the agent; errors go to `.keelyard/hook.log`.

See [SECURITY.md](SECURITY.md).

## Roadmap

- Live end-to-end runs against Claude Code, Codex and OpenCode in CI (needs agent credentials)
- Optional embeddings re-ranking for memory (FTS5 only today)
- Smarter routing based on measured outcomes rather than keywords
- Proof checks for more stacks (mobile, CLI snapshot tests), plus PR comment integration
- Rewind of side effects outside the worktree (databases, containers)

## License

Apache-2.0
