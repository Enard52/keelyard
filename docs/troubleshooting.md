# Troubleshooting

Start with `keelyard doctor`. Every failing line includes a hint.

**The agent is not blocked or snapshotted.** Run `keelyard doctor` and check the agents section. For Codex,
run `/hooks` in Codex and trust the keelyard hooks. Hooks call `keelyard` by its full path, so if you reinstall
keelyard somewhere else, run `keelyard init` again.

**Something failed silently.** Hooks never break your agent: they log the error and let the agent continue.
The log is `.keelyard/hook.log`, and `doctor` shows the last entry.

**"not a git repository or keelyard project".** keelyard refuses to snapshot your home folder or `/`. Run
`keelyard init` in the project folder.

**A large file is missing from a snapshot.** It is over `[rewind].max_file_mb`. `keelyard rewind list --json`
lists skipped files for each step.

**"no test command found".** Set `[proof].test_cmd`, or pass `--cmd`.

**The gate keeps blocking.** After `max_blocks` reminders (3 by default) it gives up and says so. To turn the
gate off, set `[proof].gate = false`.

**The project is in a path with spaces or non-ASCII characters.** Both are supported and covered by tests. If
something breaks, please open an issue and include the output of `keelyard doctor --json`.
