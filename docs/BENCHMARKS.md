# Benchmarks

Machine: 8 vCPU Linux box, no GPU, Python 3.13. Measured on 2026-10-12. Token counts are `chars / 4`.

## Head-to-head with rtk (`bench/vs_rtk.py`)

```bash
gh release download -R rtk-ai/rtk -p 'rtk-x86_64-unknown-linux-musl.tar.gz' && tar xzf rtk-*.tar.gz
git clone --depth 1 https://github.com/django/django /tmp/djb
git clone --depth 80 https://github.com/psf/requests /tmp/req
python bench/vs_rtk.py --rtk ./rtk --django /tmp/djb --history /tmp/req --json bench/vs_rtk_results.json
python bench/plot_vs_rtk.py
```

The script builds scratch repos: a Django clone with 5 edited files, 3 untracked and 1 deleted; a pytest project with
4 failing tests out of 125; and a Rust crate with 2 failing tests out of 42. It runs each command once and feeds the
same raw output to keelyard, while rtk runs the command itself. `FORCE_COLOR` is removed and `NO_COLOR=1` is set
for all runs. "Facts" are extracted from the raw output with fixed rules (see `facts_*` in the script) and count as
kept when every part appears verbatim in the filtered text.

| command | facts | raw tok | keelyard tok | keelyard kept | rtk tok | rtk kept |
|---|---|---|---|---|---|---|
| git status | 9 | 161 | 61 | 100% | 58 | 100% |
| git log -n 40 (requests) | 40 | 6,807 | 950 | 100% | 2,378 | 100% |
| git diff | 91 | 1,653 | 1,064 | 100% | 1,557 | 100% |
| grep -rn (django) | 15 | 277 | 230 | 100% | 277 | 100% |
| find *.py (admin) | 30 | 299 | 136 | 100% | 113 | 100% |
| ruff check (django/utils) | 307 | 43,582 | 3,022 | 100% | 1,050 | 24% |
| pytest -v (4 failing of 125) | 7 | 3,289 | 312 | 100% | 195 | 71% |
| cargo test (2 failing of 42) | 6 | 454 | 126 | 100% | 119 | 100% |
| **total** | | 56,522 | 5,901 | | 5,747 | |

Caveats: one run per command, eight commands, fact rules written by us. rtk drops line numbers from ruff results and
some assertion lines from pytest, which is why its retention is lower on those two. rtk handles many more tools.

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

`keelyard bench` snapshots into a temporary shadow repo (your timeline is untouched). *Warm*: one file edited, snapshot. *Cold*: the index is dropped first. Five runs each, Linux box, Oct 2026.

| Repo | Tracked files | First snapshot | Warm median | Cold median |
|---|---|---|---|---|
| keelyard | 112 | 174 ms | 8 ms | 24 ms |
| django (shallow clone) | 7,083 | 2.34 s | 88 ms | 427 ms |

Only files changed since the last snapshot are size-checked, so warm cost tracks the edit, not the repo.

## Arena, local run

`examples/arena/discount`, five hidden checks, qwen-coder 1.5B on Ollama: do nothing 0/5, one-shot qwen 0/5 (226 in / 63 out tokens), reference fix 5/5. No Claude Code, Codex or OpenCode runs yet.

## Feature matrix

`python bench/feature_matrix.py` runs every CLI command and flag, every hook and every MCP tool; results in [feature-matrix.md](feature-matrix.md).

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
