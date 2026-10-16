# What keelyard guarantees, and what it doesn't

keelyard is a local tool that runs as you. It makes an agent's claims checkable and its file edits undoable.
It is not a sandbox. This page lists exactly what holds and where the limits are.

## Proof

| keelyard guarantees | it does not guarantee |
|---|---|
| "proven" means a passing test run was recorded **for the current file contents**. Any change to a snapshotted file after that run (even one made without a hook firing) reopens the proof. | That your tests are good. A proof is only as strong as the test suite. |
| Evidence is shown at three levels, never merged: **test-verified** (keelyard ran the test command itself), **command-succeeded** (the agent ran tests in its shell and the agent harness reported the result), **agent-claimed** (the agent wrote it, e.g. a checklist tick or `accept-tests`). | That agent-claimed evidence is true. It is shown so you can judge it. |
| Proof bundles are signed with a key kept outside the project (`<data home>/keelyard/proof.key`, mode 600). A bundle edited by hand, or with its signature removed, is never reported as proven again in that session. | Protection against a process that deliberately reads that key. Anything running as your user can. Signing stops casual forging, not a determined attacker. |
| Weakened tests keep the proof open: deleted test files, fewer test functions or assertions, new `skip`/`xfail`/`only` markers, changed or added test config, fewer tests in the run than before. Compared against the files as they were before the session's first edit. | Catching every weakening. Changing an expected value (`== 81` to `== 90`), or a test that checks the wrong thing, still looks fine. The counts are pattern-based per language. |
| If no agent's Stop hook is wired, or a wired agent has never called keelyard, status and doctor say so in yellow and never show a green "proven". | That an agent obeys the gate. Claude Code and Codex let the Stop hook block; OpenCode cannot veto "idle", so keelyard sends the missing items as a new prompt. After `max_blocks` reminders the gate lets the agent stop and records that. |
| Parallel sessions and hooks write proof and timeline state under file locks; a torn write cannot produce a half bundle (atomic replace). | Consistency across machines or network file systems with broken locking. |

## Rewind

| keelyard guarantees | it does not guarantee |
|---|---|
| Every rewind first snapshots the current state, so it can be undone with the step number it prints. | Undoing anything outside the project folder. |
| Files a snapshot cannot hold (gitignored, secrets, larger than `max_file_mb`) but that a rewind would overwrite or delete are copied to `.keelyard/backup/<time>/` first. | Undoing **databases, migrations that ran, deployed services, sent emails, pushed commits, or package installs**. A snapshot holds files only. Before a destructive command (`rm -rf`, `git reset --hard`, `DROP TABLE`, migrations) keelyard snapshots the files and warns; the database itself is not restored. |
| An interrupted rewind (crash, Ctrl-C) leaves a journal. keelyard refuses to rewind again until `keelyard rewind recover` puts back the state from just before it. | Recovery if `.keelyard/` itself is deleted. |
| Your own `.git` is never touched (separate shadow repository, own index). | |

## Secrets

- Never snapshotted by default: `.env`, `.env.*` (except `.env.example`/`.sample`/`.template`), `*.pem`, `*.key`,
  `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `id_rsa*`/`id_ed25519*`/..., `.npmrc`, `.pypirc`, `.netrc`,
  `.git-credentials`, `credentials.json`, `service-account*.json`, `*.tfstate`, `secrets/`. Change it with
  `[rewind].include_secrets = true` or add patterns with `[rewind].exclude`.
- Memory, proof bundles and reports pass text through a redactor (API keys, tokens, private keys, JWTs,
  `PASSWORD=...` style assignments). It is pattern-based: an unusual secret format can slip through.
- keelyard never sends anything anywhere. The only network calls are the ones you configure (swarm helper models).

## Tokens

- keelyard's own additions (brief, hints, footers) are budgeted. `keelyard run` returns the raw output when
  filtering would not save more than its own footer costs.
- Filters never drop an error or warning line: tested against real logs from pytest, cargo, go, node, eslint,
  ruff, npm and git (`tests/corpus/`), also with thousands of lines of padding.
- The lean preset saves tokens partly by **turning tools off** (9 OpenCode built-ins, keelyard's MCP list).
- Benchmarks used a free model, so there is no cost claim. See [BENCHMARKS](BENCHMARKS.md) for the split
  between cached and uncached input.

## Per agent

| capability | Claude Code | Codex | OpenCode |
|---|---|---|---|
| proof gate at the end of a turn | Stop hook blocks | Stop hook blocks (approve hooks once with `/hooks`) | cannot block "idle": missing items sent as a new prompt |
| evidence from shell test runs | command-succeeded | command-succeeded | command-succeeded |
| `proof test` / `proof_run_tests` | test-verified | test-verified | test-verified (MCP off in lean: use the CLI) |
| snapshot after each edit | yes | yes | yes |
| shell output filtered in place | yes (`updatedToolOutput`) | sent the same way; not yet confirmed in a real Codex session | yes (plugin rewrites the output) |
| MCP tools | `.mcp.json` | `~/.codex/config.toml` or `--codex-project-mcp` | off by default (`KEELYARD_OPENCODE_MCP=1`) |
| checked how | scripted hook payloads in CI (`keelyard selftest`) | scripted hook payloads in CI | real sessions, OpenCode 2.0.22 on Windows 11 |

Real Claude Code and Codex sessions have not been benchmarked yet.
