# Benchmarks

Machine: 8 vCPU Linux box, no GPU, Python 3.13. Measured on 2026-10-12. Token counts are `chars / 4`.

## Output compression (`keelyard bench`, section `compress`)

The corpus is in `bench/corpus/`. Each file is real output from a real command run on the box, with temporary paths
rewritten to `/tmp/demo`:

| Log | Command | Raw | Compressed |
|---|---|---|---|
| cargo-build.log | `cargo build` (serde, serde_json) | 198 | 198 |
| git-clone-progress.log | `git clone --progress psf/requests` | 2,101 | 220 |
| npm-install-verbose.log | `npm install express --loglevel=verbose` | 2,744 | 1,142 |
| pip-install-verbose.log | `pip install -v httpx rich` | 1,159 | 1,158 |
| pytest-verbose-failing.log | `pytest -v` with 60 passing and 3 failing tests | 1,814 | 661 |
| pytest-verbose-passing.log | `pytest -v -rA` on this repo | 884 | 884 |
| **total** | | **8,900** | **4,263 (−52.1%)** |

All 12 `FAILED`/`assert`/`KeyError` lines of the failing pytest log survive compression.
The corpus is small. Please contribute more real logs.

## Snapshots

`bench_snapshot`: write a one-line probe file, then snapshot. Five runs each.

| Repo | Tracked files | First snapshot | Median | Max |
|---|---|---|---|---|
| keelyard | 36 | n/a | 11.0 ms | 12.2 ms |
| django (shallow clone) | 7,083 | 2.09 s | 71.7 ms | 113.6 ms |

## Swarm with a small local model

These are real calls to `qwen2.5-coder-1.5b-instruct` (Q4_K_M GGUF) served by Ollama on CPU, with concurrency 4.
There were 12 tasks against this repo: 8 Q&A or summaries, 2 patch drafts and 2 greps.

- Wall time: 4 min 15 s; helper tokens: 14,452 in, 1,409 out.
- Verified: 3/12. Both greps are local and need no model. One patch passed `git apply --check`; the other did not apply.
- Q&A: 0/8 answers contained a valid `path:line` citation, and the verifier marked all 8 UNVERIFIED.
  A second run with a format example in the prompt also verified 0/8. One answer copied the example's
  file name, so the example was removed again.

Conclusion: the verification layer does its job, but a 1.5B model is not a useful helper. Use a 7B+ local model or
a hosted cheap model. We have not yet measured how well larger models verify.

## Not yet measured

- `reads`: repeated identical reads in real Claude Code transcripts (harness exists, no transcripts on the build box).
- `memory`: recall@8 and snippet/transcript ratio on real sessions (harness exists, same reason).
