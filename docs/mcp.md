# MCP reference

Generated from the running server by `docs/demo/gen_reference.py`.

The server is `keelyard mcp` (stdio). It sends these instructions to the agent on connect:

```text
keelyard: proof, rewind and a smaller context for this project.

Workflow for any task that changes files:
1. proof_requirements(items=[...])  one short, checkable item per thing the user asked for.
2. Explore cheaply: project_map, find_symbol, outline, then read_file (repeat reads are deduplicated).
3. Make the change. Every edit is snapshotted automatically; rewind_list / rewind_to undo mistakes.
4. run_compact for noisy commands (tests, builds, git log); recall(output_id) if you need the full text.
5. proof_run_tests(phase="after"), then proof_check(requirement_id, evidence) for each item.
6. proof_status must say proven=true before you tell the user you are done; the Stop hook enforces it.
Use memory_search before re-deriving something solved in an earlier session. For bulk read/summarise/draft
work, swarm_plan(goal) then swarm(tasks): answers are checked (citations, patches tested in a copy).
```

Every tool returns a JSON object (MCP structured content). Errors are MCP tool errors whose text says what went wrong and, where there is one, a `Hint:` with the fix.

| tool | read-only | destructive | summary |
|---|---|---|---|
| [`proof_requirements`](#proof_requirements) |  |  | Record what the user asked for as a checklist. Call this first. Duplicate items are ignored. |
| [`proof_check`](#proof_check) |  |  | Mark one requirement as verified, with concrete evidence (a command and its result, or file:line). |
| [`proof_run_tests`](#proof_run_tests) |  |  | Run the project's tests and record the result as evidence. |
| [`proof_screenshot`](#proof_screenshot) |  |  | Screenshot the running web app and attach it to the proof bundle. Returns {"ok", "path"} or an error. |
| [`proof_status`](#proof_status) | yes |  | Is the work proven? Returns {"proven", "missing": [what to do next], "requirements", "report"}. |
| [`rewind_list`](#rewind_list) | yes |  | List recent workspace snapshots, oldest first. One is taken after every edit or shell command. |
| [`rewind_diff`](#rewind_diff) | yes |  | The unified diff a snapshot step made. Returns {"step", "files", "diff"} (long diffs are shortened). |
| [`rewind_to`](#rewind_to) |  | yes | Restore project files to how they were after `step`. A safety snapshot is taken first, |
| [`read_file`](#read_file) | yes |  | Read a project file. A repeat read of an unchanged file returns a one-line notice instead of the |
| [`run_compact`](#run_compact) |  |  | Run a command and return output with failures, errors and file:line kept and noise dropped. |
| [`recall`](#recall) | yes |  | Return the full raw output that run_compact or the shell-output filter shortened. |
| [`outline`](#outline) | yes |  | Signatures and classes with line numbers. Read this before reading a whole file. |
| [`project_map`](#project_map) | yes |  | Files per directory with approximate token sizes. Start here in an unfamiliar repo. |
| [`find_symbol`](#find_symbol) | yes |  | Where is a symbol defined? Returns {"matches": ["path:line: signature", ...]}. |
| [`usage_report`](#usage_report) | yes |  | Token usage and cost from local Claude Code, Codex and OpenCode logs. Cost is null for unpriced models. |
| [`route_task`](#route_task) | yes |  | Suggest the strong or the cheap model for a subtask (a transparent keyword heuristic, not a model call). |
| [`swarm`](#swarm) |  |  | Run small tasks on the configured helper model in parallel. Each answer is checked: citations (path:line) |
| [`swarm_plan`](#swarm_plan) | yes |  | Split a goal into small tasks, one per relevant file, each with a minimal context pack (only the named |
| [`swarm_verify`](#swarm_verify) | yes |  | Verify an answer from any helper, including your own subagents. Returns {"verified", "notes"}. |
| [`memory_search`](#memory_search) | yes |  | Search past Claude Code, Codex and OpenCode sessions. New sessions are indexed first. |
| [`status`](#status) | yes |  | One call to orient yourself: version, project root, snapshot count, proof state. |

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

## proof_screenshot

Screenshot the running web app and attach it to the proof bundle. Returns {"ok", "path"} or an error.

| parameter | type | default | description |
|---|---|---|---|
| `url` | string | "" | Page to capture, e.g. "http://localhost:3000/cart". Default: [proof].app_url. |

## proof_status

Is the work proven? Returns {"proven", "missing": [what to do next], "requirements", "report"}.

No parameters.

## rewind_list

List recent workspace snapshots, oldest first. One is taken after every edit or shell command.

Returns {"steps": [{"step", "tool", "ts", "files", "n_files"}], "total"}.

| parameter | type | default | description |
|---|---|---|---|
| `last` | integer | 20 | How many recent steps, e.g. 20. |

## rewind_diff

The unified diff a snapshot step made. Returns {"step", "files", "diff"} (long diffs are shortened).

| parameter | type | default | description |
|---|---|---|---|
| `step` | integer | required | A step number from rewind_list, e.g. 3. |

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

## outline

Signatures and classes with line numbers. Read this before reading a whole file.

| parameter | type | default | description |
|---|---|---|---|
| `path` | string | required | Project-relative path, e.g. "src/cart.py". |

## project_map

Files per directory with approximate token sizes. Start here in an unfamiliar repo.

No parameters.

## find_symbol

Where is a symbol defined? Returns {"matches": ["path:line: signature", ...]}.

| parameter | type | default | description |
|---|---|---|---|
| `name` | string | required | Function, class or type name, e.g. "Cart". |

## usage_report

Token usage and cost from local Claude Code, Codex and OpenCode logs. Cost is null for unpriced models.

| parameter | type | default | description |
|---|---|---|---|
| `by` | "day" / "model" / "agent" | "day" | How to group rows. |

## route_task

Suggest the strong or the cheap model for a subtask (a transparent keyword heuristic, not a model call).

| parameter | type | default | description |
|---|---|---|---|
| `task` | string | required | The subtask, e.g. "summarise these 30 log files". |
| `n_files` | integer | 0 | How many files it touches. |

## swarm

Run small tasks on the configured helper model in parallel. Each answer is checked: citations (path:line)
must exist; drafts must apply and pass the tests in a throwaway copy (never applied to your files).
Failed answers are retried with the checker's notes, best-of-N, then escalated to the strong model if set.
With no helper model configured, returns {"mode": "plan", "subagent_tasks": [...]} for your own subagents.

| parameter | type | default | description |
|---|---|---|---|
| `tasks` | array | required | Each: {"kind": "ask"|"summarize"|"draft_edit"|"grep", "prompt": str, "files": [paths], "symbols": [names]}. "symbols" narrows the context to those definitions. Tip: swarm_plan builds this list for you. Example: [{"kind": "ask", "prompt": "Where is the discount applied?", "files": ["cart.py"]}] |

## swarm_plan

Split a goal into small tasks, one per relevant file, each with a minimal context pack (only the named
definitions plus imports). Returns {"tasks"} to pass to swarm, and {"subagent_tasks"} with ready prompts
for your own subagents. Deterministic: no model call.

| parameter | type | default | description |
|---|---|---|---|
| `goal` | string | required | What you want done, e.g. "fix total() so SAVE10 takes 10% off". |
| `files` | array | [] | Limit to these files; empty = find the files that define the symbols the goal names. |
| `max_tasks` | integer | 8 | Upper bound on tasks. |

## swarm_verify

Verify an answer from any helper, including your own subagents. Returns {"verified", "notes"}.

| parameter | type | default | description |
|---|---|---|---|
| `answer` | string | required | The answer or unified diff to check. |
| `files` | array | [] | Files the answer may cite, e.g. ["cart.py"]. |
| `kind` | "ask" / "draft_edit" | "ask" | "ask": check path:line citations; "draft_edit": check the patch applies. |

## memory_search

Search past Claude Code, Codex and OpenCode sessions. New sessions are indexed first.
Returns {"hits": [{"agent", "session", "project", "ts", "role", "snippet"}]}.

| parameter | type | default | description |
|---|---|---|---|
| `query` | string | required | Words to look for, e.g. "stripe webhook signature". |
| `this_project_only` | boolean | true | Only sessions that ran in this project. |
| `budget_chars` | integer | 2400 | Max characters of snippets returned. |

## status

One call to orient yourself: version, project root, snapshot count, proof state.

No parameters.
