# Always on

Tools only help if the agent remembers to use them. keelyard therefore puts a little of itself into the
agent's context at the moments that matter, with a hard token budget each time.

## What the agent sees, and when

| moment | what keelyard adds | budget |
|---|---|---|
| session start | a **brief**: the rules (rewind, proof, cheap exploration, helpers), open proof items, a project map digest, and past-session notes that match the current task | `brief_tokens`, 600 by default |
| after the context is compacted | the same brief again, marked "re-sent after compaction" | same |
| each prompt you send | up to 4 snippets from earlier sessions **in this project** that match the prompt. Nothing at all if none match. | `recall_tokens`, 250 by default |
| before reading a file again | if it is unchanged: "you already have it", plus its outline so the agent can find its place. If it changed: only the diff. | about 300 tokens of outline |
| before a destructive command | `rm -rf`, `git reset --hard`, `git clean -f`, `git checkout .`, `git push --force`, `DROP`/`TRUNCATE`, `DELETE` without `WHERE`, and migrations (Django, Alembic, Prisma, Rails, Knex, Sequelize): keelyard **takes a snapshot first** and tells the agent which step restores the files | one line |
| before editing code with no test nearby | "no tests found for billing.py" (looks for `test_x.py`, `x_test.go`, `x.test.ts`, `tests/` and the like) | one line, once per file |
| when the session gets large | if you set `plan_tokens`, a hint to hand bulk work to helpers once the session passes `budget_warn_at` of it | one line |

keelyard never decides for you. A destructive command is not blocked; the snapshot just makes it undoable.

## Never spammy

Every hint has a cooldown per kind (`nudge_cooldown_s`, 5 minutes) and there is a cap per session
(`max_nudges_per_session`, 12). The snapshot before a destructive command happens every time, even when the
hint itself is rate-limited.

```toml
[brain]
brief = true
brief_tokens = 600
recall = true
recall_tokens = 250
nudges = true
nudge_cooldown_s = 300
max_nudges_per_session = 12
plan_tokens = 0          # e.g. 200000; 0 turns the budget hint off
budget_warn_at = 0.6
```

Past-session recall reads keelyard's memory index. The Stop hook refreshes it at most every 10 minutes;
`keelyard memory index` does it by hand.

## Per agent

| | Claude Code | Codex | OpenCode |
|---|---|---|---|
| brief at start | SessionStart `additionalContext` | SessionStart `additionalContext` | system prompt (`experimental.chat.system.transform`) |
| brief after compaction | SessionStart with `source: compact` | **gap**: no post-compaction event | kept in the compaction summary (`experimental.session.compacting`) |
| recall per prompt | UserPromptSubmit `additionalContext` | UserPromptSubmit `additionalContext` | queued, added to the next system prompt (`chat.message`) |
| repeat read → outline/diff | PreToolUse deny with reason | **gap**: Codex has no read tool hook | tool error with the same text |
| snapshot before destructive | PreToolUse on Bash | PreToolUse on shell | `tool.execute.before` |
| hints | PreToolUse `additionalContext` + a visible `systemMessage` for destructive commands | same JSON; whether Codex shows PreToolUse context is **not verified** | queued, added to the next system prompt |
| budget hint | from `transcript_path` size | same | **gap**: no transcript path; set nothing, it stays off |

The Claude Code column is covered by the test suite at the hook level. The Codex and OpenCode columns follow
their documented hook and plugin APIs (`@opencode-ai/plugin` 1.19), but have **not yet been run against the
real agents**.
