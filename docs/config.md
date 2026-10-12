# Configuration

`keelyard init` writes `.keelyard/config.toml`. Every field is optional. This is the default file:

```toml
# keelyard configuration. Every field is optional.

[proof]
# Block the agent from finishing until a proof bundle exists.
gate = true
# Command used for before/after test runs. Empty = auto-detect.
test_cmd = ""
# URL of the running app; when set, a screenshot is required for proof.
app_url = ""
# Stop the gate from looping forever: give up after this many blocks per session.
max_blocks = 3

[rewind]
enabled = true
# Files larger than this are left out of snapshots and listed as skipped.
max_file_mb = 20
# Tools that trigger a snapshot after they run.
snapshot_tools = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "apply_patch", "write", "edit", "bash", "patch"]

[swarm]
# Max concurrent helper calls.
concurrency = 16
# Hard cap on tasks per swarm call.
max_tasks = 256
# Which [models.*] entry helpers use.
helper_model = "cheap"

[saver]
# Deny a repeat Read of an unchanged file (reset on context compaction).
dedupe_reads = true
# Filter large Bash results before the model reads them (raw output kept for `keelyard recall`).
filter_bash = true
filter_min_chars = 1200
# Max characters returned by compress_output before head/tail trimming.
max_output_chars = 6000

# Optional prices for `keelyard usage`, USD per million tokens. keelyard ships none.
# [prices."your-model-name"]
# input = 0.0
# output = 0.0
# cache_read = 0.0
# cache_write = 0.0

# Models are plain names you choose; keelyard never assumes a vendor's lineup.
# provider = "openai" (any OpenAI-compatible /chat/completions) or "anthropic".
[models.cheap]
provider = "openai"
base_url = "http://localhost:11434/v1"
model = "qwen2.5-coder:7b"
api_key_env = ""

[models.strong]
provider = "anthropic"
base_url = "https://api.anthropic.com"
model = "set-me"
api_key_env = "ANTHROPIC_API_KEY"
```

`.keelyard/` also holds snapshots (`shadow.git`, `steps.jsonl`), proof bundles, shortened outputs (`raw/`)
and the hook error log (`hook.log`). The folder contains a `.gitignore` with `*`, so it is never committed.

Environment variables:

| variable | effect |
|---|---|
| `KEELYARD_ROOT` | use this folder as the project root instead of searching upward for `.keelyard` or `.git` |
| `XDG_DATA_HOME` | where the memory index lives (default `~/.local/share/keelyard`) |
| `NO_COLOR`, `FORCE_COLOR=0` | plain terminal output |
