## keelyard

This project uses keelyard (MCP server `keelyard`). It snapshots every edit and will not let you
finish until the work is proven.

- Start a task with `proof_requirements` (one short, checkable item per thing the user asked).
- Explore with `project_map`, `find_symbol`, `outline` before reading whole files; use `read_file`.
- Use `run_compact` for tests, builds and long logs; `recall` returns the full text if you need it.
- Broke something? `rewind_list`, then `rewind_to` a step. It is undoable.
- Before saying done: `proof_run_tests` with phase "after", `proof_check` each item with evidence,
  then `proof_status` must return `"proven": true`.
- Solved this before? `memory_search` looks through past Claude Code, Codex and OpenCode sessions.

Without MCP, the same actions exist as `keelyard <command> --json` (exit codes: 0 ok, 1 error,
2 usage, 3 check not passed).
