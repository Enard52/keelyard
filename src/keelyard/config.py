"""Project configuration (.keelyard/config.toml) and on-disk layout."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = """\
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
"""


def find_root(start: Path | None = None) -> Path:
    """Project root: nearest ancestor with .keelyard or .git, else cwd."""
    env = os.environ.get("KEELYARD_ROOT")
    if env:
        return Path(env).resolve()
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / ".keelyard").is_dir() or (p / ".git").exists():
            return p
    return cur


def data_home() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    d = Path(base) / "keelyard"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Config:
    root: Path
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def state(self) -> Path:
        d = self.root / ".keelyard"
        if not d.exists():
            d.mkdir(parents=True)
            # Never let agent state leak into the user's own commits.
            (d / ".gitignore").write_text("*\n")
        return d

    def section(self, name: str) -> dict[str, Any]:
        defaults = tomllib.loads(DEFAULT_CONFIG).get(name, {})
        return {**defaults, **self.raw.get(name, {})}

    def model(self, key: str) -> dict[str, Any]:
        models = {**tomllib.loads(DEFAULT_CONFIG)["models"], **self.raw.get("models", {})}
        if key not in models:
            raise KeyError(f"no [models.{key}] in .keelyard/config.toml")
        return models[key]


def load(root: Path | None = None) -> Config:
    root = root or find_root()
    path = root / ".keelyard" / "config.toml"
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    return Config(root=root, raw=raw)


def init(root: Path) -> Path:
    cfg = Config(root=root)
    path = cfg.state / "config.toml"
    if not path.exists():
        path.write_text(DEFAULT_CONFIG)
    return path
