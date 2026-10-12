# Contributing

```bash
git clone https://github.com/akobirjontulqinovfuture/keelyard && cd keelyard
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check src tests
```

Ground rules:

- **No invented numbers.** Any performance claim in docs must come from `keelyard bench` or a script in the repo,
  with the machine and date noted in `docs/BENCHMARKS.md`.
- **Hooks must never break the agent.** Anything in `hooks.handle` that can fail must be caught; add a test.
- **Local-first.** New features may not send data off the machine unless the user configured that endpoint.
- **Redact before you store.** Anything persisted goes through `keelyard.redact.redact`.

Good first contributions:

- A filter for a tool we don't cover yet, with a real output sample and a fact-retention test
- Real command logs for `bench/corpus/` (strip secrets and personal paths)
- Adapters for more agents (Aider, Cursor CLI, Gemini CLI, Antigravity)
- A live-session test for Codex or OpenCode
- Better compression rules for a specific tool's output

Layout: `src/keelyard/{proof,report,snapshot,tui,swarm,saver,filters,codemap,memory,usage,arena,hooks,mcp_server,cli,bench}.py`,
`adapters/` per agent, and tests in `tests/`.
