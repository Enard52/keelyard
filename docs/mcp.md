# MCP reference

Generated from the running server by `docs/demo/gen_reference.py`.

The server is `keelyard mcp` (stdio). It sends these instructions to the agent on connect:

```text
keelyard: proof, rewind, smaller context. For a change: proof_requirements -> find_symbol,
read_file(ranges) -> edit (auto-snapshotted; rewind_to undoes) -> run_compact -> proof_run_tests(phase="after")
-> proof_check each item -> proof_status proven. Step-by-step guides: workflow("plan"|"debug"|"review").
```

Every tool returns a JSON object (MCP structured content). Errors are MCP tool errors whose text says what went wrong and, where there is one, a `Hint:` with the fix.

| tool | read-only | destructive | summary |
|---|---|---|---|
| [`proof_requirements`](#proof_requirements) |  |  | Record what the user asked for as a checklist. Call this first. Duplicate items are ignored. |
| [`proof_check`](#proof_check) |  |  | Mark one requirement as verified, with concrete evidence (a command and its result, or file:line). |
| [`proof_run_tests`](#proof_run_tests) |  |  | Run the project's tests and record the result as evidence. |
| [`proof_status`](#proof_status) | yes |  | Is the work proven? Returns {"proven", "missing": [what to do next], "requirements", "report"}. |
| [`rewind_list`](#rewind_list) | yes |  | List recent workspace snapshots, oldest first. One is taken after every edit or shell command. |
| [`rewind_to`](#rewind_to) |  | yes | Restore project files to how they were after `step`. A safety snapshot is taken first, |
| [`read_file`](#read_file) | yes |  | Read a project file. A repeat read of an unchanged file returns a one-line notice instead of the |
| [`run_compact`](#run_compact) |  |  | Run a command and return output with failures, errors and file:line kept and noise dropped. |
| [`recall`](#recall) | yes |  | Return the full raw output that run_compact or the shell-output filter shortened. |
| [`find_symbol`](#find_symbol) | yes |  | Where is a symbol defined? Returns {"matches": ["path:line: signature", ...]}. |
| [`swarm`](#swarm) |  |  | Run small tasks on the configured helper model in parallel. Each answer is checked: citations (path:line) |
| [`memory_search`](#memory_search) | yes |  | Search past Claude Code, Codex and OpenCode sessions. New sessions are indexed first. |
| [`workflow`](#workflow) | yes |  | A short step-by-step guide: plan (plan-implement-verify), debug (loop), review (diff checklist). |

## proof_requirements

Record what the user asked for as a checklist. Call this first. Duplicate items are ignored.

Returns {"requirements": [{"id", "text", "done", "evidence"}]}.

| parameter | type | default | description |
|---|---|---|---|
| `items` | array | required | One short, checkable item per user ask, e.g. ["discount applies once", "empty cart costs 0"]. |

## proof_check

Mark one requirement as verified, with concrete evidence (a command and its result, or file:line).

Returns the updated requirement.

| parameter | type | default | description |
|---|---|---|---|
| `requirement_id` | integer | required | The id from proof_requirements, e.g. 1. |
| `evidence` | string | required | What you ran or saw, e.g. "pytest tests/test_cart.py::test_once passed" or "cart.py:14 caps at one use". |

## proof_run_tests

Run the project's tests and record the result as evidence.

Returns {"exit", "passed", "seconds", "cmd", "output"} where output is a compact tail.

| parameter | type | default | description |
|---|---|---|---|
| `phase` | "before" / "after" | "after" | "before" your change (baseline) or "after" it (required by the gate). |
| `command` | string | "" | Optional override, e.g. "pytest -q tests/test_cart.py". Default: [proof].test_cmd or auto-detected. |

## proof_status

Is the work proven? Returns {"proven", "missing": [what to do next], "requirements", "report"}.

No parameters.

## rewind_list

List recent workspace snapshots, oldest first. One is taken after every edit or shell command.

Returns {"steps": [{"step", "tool", "ts", "files", "n_files"}], "total"}.

| parameter | type | default | description |
|---|---|---|---|
| `last` | integer | 20 | How many recent steps, e.g. 20. |

## rewind_to

Restore project files to how they were after `step`. A safety snapshot is taken first,
so calling rewind_to(safety_step) undoes this. Returns {"restored", "removed", "safety_step", "new_step"}.

| parameter | type | default | description |
|---|---|---|---|
| `step` | integer | required | A step number from rewind_list, e.g. 3. |

## read_file

Read a project file. A repeat read of an unchanged file returns a one-line notice instead of the
text; a changed file returns only the diff since your last read. Returns {"path", "content"}.

| parameter | type | default | description |
|---|---|---|---|
| `path` | string | required | Project-relative path, e.g. "src/cart.py". Windows separators are accepted. |
| `start` | integer | 1 | First line, 1-based. |
| `end` | integer | 0 | Last line, inclusive; 0 = end of file. |
| `force` | boolean | false | Return the full text even if you read it before (e.g. after compaction). |

## run_compact

Run a command and return output with failures, errors and file:line kept and noise dropped.
Returns {"exit", "output"}; the output ends with an id for recall() when anything was cut.

| parameter | type | default | description |
|---|---|---|---|
| `command` | string | required | Command line, run without a shell, e.g. "pytest -q" or "git log -n 20". |
| `timeout` | integer | 600 | Seconds before the command is killed. |

## recall

Return the full raw output that run_compact or the shell-output filter shortened.

| parameter | type | default | description |
|---|---|---|---|
| `output_id` | string | required | The id printed by run_compact, e.g. "3f9a1c2b7d4e". |

## find_symbol

Where is a symbol defined? Returns {"matches": ["path:line: signature", ...]}.

| parameter | type | default | description |
|---|---|---|---|
| `name` | string | required | Function, class or type name, e.g. "Cart". |

## swarm

Run small tasks on the configured helper model in parallel. Each answer is checked: citations (path:line)
must exist; drafts must apply and pass the tests in a throwaway copy (never applied to your files).
Failed answers are retried with the checker's notes, best-of-N, then escalated to the strong model if set.
With no helper model configured, returns {"mode": "plan", "subagent_tasks": [...]} for your own subagents.

| parameter | type | default | description |
|---|---|---|---|
| `tasks` | array | required | Each: {"kind": "ask"|"summarize"|"draft_edit"|"grep", "prompt": str, "files": [paths], "symbols": [names]}. "symbols" narrows the context to those definitions. Tip: swarm_plan builds this list for you. Example: [{"kind": "ask", "prompt": "Where is the discount applied?", "files": ["cart.py"]}] |

## memory_search

Search past Claude Code, Codex and OpenCode sessions. New sessions are indexed first.
Returns {"hits": [{"agent", "session", "project", "ts", "role", "snippet"}]}.

| parameter | type | default | description |
|---|---|---|---|
| `query` | string | required | Words to look for, e.g. "stripe webhook signature". |
| `this_project_only` | boolean | true | Only sessions that ran in this project. |
| `budget_chars` | integer | 2400 | Max characters of snippets returned. |

## workflow

A short step-by-step guide: plan (plan-implement-verify), debug (loop), review (diff checklist).

| parameter | type | default | description |
|---|---|---|---|
| `name` | "plan" / "debug" / "review" | required | Which guide. |
