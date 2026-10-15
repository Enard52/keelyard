
## Real agent run: OpenCode 2.0.22 on Windows 11 (Oct 15, 2026)

One run each, same task and same free model (`opencode/big-pickle`, cost reported by OpenCode: $0).
Task: fix a SAVE10 coupon, reject unknown coupons, floor `inventory.remove` at zero (3 failing of 66 tests).
Raw data: [`bench/real/`](bench/real/); numbers produced by `bench/real/summarize.py` from `opencode session export`.

| | baseline (no keelyard) | with keelyard |
|---|---|---|
| tests after run | 66/66 pass | 66/66 pass |
| model calls | 5 | 6 |
| input tokens, uncached | 16,436 | 13,654 |
| input tokens, cache read | 28,864 | 68,544 |
| input tokens, total | 45,300 | 82,198 |
| output + reasoning | 897 | 1,568 |
| wall time | 65 s | 122 s |
| proof | none | proven, 4 requirements with evidence |

Honest reading: on this small task keelyard **cost more tokens** (+81% total input), not fewer.
The main causes seen in the export: OpenCode 2 "code mode" injects an ~8.9k-char catalog for keelyard's
13 MCP tools, and the agent spent one call (19.7k chars) searching that catalog. Test output itself was
smaller with keelyard (`proof_run_tests`: 2,967 chars vs 7,008 + 5,789 raw `pytest -v` in the baseline),
but the shell-output filter did not fire because in code mode the agent never called the shell tool directly.
The 56k→6k savings measured earlier apply to noisy command output, which this task did not produce.
Rewind was verified on the same project: `rewind to 1` → 3 failed; `rewind to 2` → 66 passed
([screenshot](docs/img/real/rewind.svg)). Status/proof: [screenshot](docs/img/real/status.svg).

### After the lean-mode fix (commit f93dbaa), same PC, same free model, n=1 per row

keelyard no longer puts an MCP tool catalog into OpenCode's context, counts the agent's own shell test runs as
proof, and filters shell output. Data: `bench/real/opencode_bigpickle_lean.json`, `opencode_bigpickle_noisy.json`.

| task | run | tests after | model calls | input total (incl. cache) | input uncached | tool output chars |
|---|---|---|---|---|---|---|
| shop (66 tests) | baseline | 66/66 | 5 | 44,075 | 6,571 | 14,502 |
| shop (66 tests) | keelyard before fix | 66/66 | 6 | 82,198 | 13,654 | 26,746 |
| shop (66 tests) | **keelyard lean** | 66/66, proven | 5 | **37,493 (−15%)** | 4,021 | 2,806 (−81%) |
| noisy shop (1,566 tests, `pytest -v`) | baseline | 1566/1566 | 6 | 87,168 | 18,496 | 54,407 |
| noisy shop (1,566 tests, `pytest -v`) | **keelyard lean** | 1566/1566, proven | 5 | **37,257 (2.3× fewer)** | 7,049 (2.6× fewer) | 2,854 (19× fewer) |

What limits the ratio: OpenCode's own system prompt and tool definitions are resent on every model call
(about 6k tokens per call here), so five calls cost ~30k tokens before any project content. keelyard cuts
what it controls (tool output 19×, e.g. `pytest -v` 12,849 → 279 tokens) but cannot reach 10× on whole-session
tokens for short tasks. The gap grows with longer sessions and noisier output.
