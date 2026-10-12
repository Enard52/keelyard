# Proof gate

Agents often say "done" when nothing was run, or when tests went green only because they were edited.
The proof gate is a Stop hook. If the agent changed files in this session, it cannot finish until all of
these are true:

1. There is a requirement checklist (`proof_requirements`).
2. Every item has evidence: a command and its result, or a `path:line` (`proof_check`).
3. A test run after the last edit passed (`proof_run_tests` with `phase="after"`).
4. If `[proof].app_url` is set, there is a screenshot taken since the last edit.

When something is missing, the hook answers `{"decision": "block", "reason": ...}`. The reason lists what is
missing, so the agent knows exactly what to do next. To stop loops, the gate gives up after `max_blocks`
reminders (3 by default) and tells you. A turn that changed no files and wrote no checklist is never blocked.

## The report

Each session gets a self-contained HTML file in `.keelyard/proof/<session>/report.html`. It has no external
requests and embeds its fonts, so you can attach it to a PR.

![proof report](../img/proof-report.png)

The timeline at the bottom interleaves snapshots, test runs and every gate decision.

## From the CLI

```bash
keelyard proof add "SAVE10 takes 10% off" "unknown coupons raise ValueError"
keelyard proof test before            # optional baseline
keelyard proof test after
keelyard proof check 1 "test_save10 passes"
keelyard proof status                 # exit 0 when proven, 3 when not
keelyard proof report --open
```

The test command comes from `[proof].test_cmd`. If that is not set, keelyard detects it from `package.json`,
`Cargo.toml`, `go.mod` or Python test files. To use a different command for one run, pass
`--cmd "npm test"`.

## Limits

The gate checks that evidence exists. It does not check that the evidence is true. An agent that is
determined to lie can write a false sentence. The report exists so that a person can read the evidence
in one minute.
