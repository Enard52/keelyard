# Memory and usage

## Memory

keelyard indexes the session logs that Claude Code (`~/.claude/projects`), Codex (`~/.codex/sessions`) and
OpenCode (`~/.local/share/opencode/storage`) already keep on disk. The index is SQLite FTS5, stored in
`~/.local/share/keelyard/memory.db` with mode 600. Secrets such as API keys, tokens and private keys are
redacted before anything is stored.

```bash
keelyard memory index
keelyard memory search "websocket reconnect"
keelyard memory stats
```

The agent uses the `memory_search` tool, which indexes new sessions before every search and by default
only searches sessions from the current project.

## Usage

`keelyard usage` reads the same logs and adds up input, output and cache tokens by day, model or agent.
keelyard ships no prices. To get a cost column, add `[prices."model-name"]` to the config. Models without
a price are marked rather than guessed.
