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
# No checklist written? A passing test run after the last edit (also one run in the agent's shell) proves the task.
auto_requirements = true

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
# Samples per task (best-of-N), retries with verifier feedback, and the model tried once when all fail
# ("" = no escalation). Draft patches are also run against the tests in a temporary copy.
best_of = 2
retries = 1
escalate_model = "strong"
test_patches = true
# Cooperative mode (default; `keelyard swarm run --basic` turns it off for one run): models tried cheapest first
# ([] = helper_model then escalate_model), concurrent workers, a peer critic, and hard token caps
# (0 = no cap). Calls are refused before they are made once a cap would be crossed.
cooperative = true
ladder = []
workers = 64
critic = false
budget_tokens = 200000
task_budget_tokens = 20000

[brain]
# Give the agent a short keelyard brief at session start and again after context compaction.
brief = true
brief_tokens = 600
# Add the most relevant past-session snippets to each prompt (0 hits = nothing added).
recall = true
recall_tokens = 250
# Short hints while the agent works: destructive commands, edits with no tests nearby, budget.
nudges = true
# Seconds before the same kind of hint can repeat, and a hard cap per session.
nudge_cooldown_s = 300
max_nudges_per_session = 12
# Your plan's context/session token budget for "delegate to helpers" hints. 0 = off.
plan_tokens = 0
budget_warn_at = 0.6

[mcp]
# Tools the MCP server offers. Every schema costs tokens in every session, so the default is the 13 the
# workflow needs. "all" adds outline, project_map, rewind_diff, usage_report, route_task, swarm_plan,
# swarm_verify, status (and proof_screenshot, which "core" adds by itself when [proof].app_url is set).
tools = "core"

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


class ProjectError(RuntimeError):
    """Raised when keelyard is asked to act outside a real project."""


VENDOR_DIRS = {".git", ".keelyard", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
               ".ruff_cache", "dist", "build", "target", ".next", ".tox", ".idea", ".gradle"}


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

    def require_project(self) -> None:
        """Refuse to snapshot or write state in $HOME or / unless the user ran `keelyard init` there."""
        marker = (self.root / ".keelyard").is_dir()
        risky = self.root in (Path.home().resolve(), Path(self.root.anchor))
        if not marker and (risky or not (self.root / ".git").exists()):
            raise ProjectError(f"{self.root} is not a git repository or keelyard project. "
                               "Hint: run `keelyard init` in your project folder.")

    @property
    def state(self) -> Path:
        d = self.root / ".keelyard"
        if not (d / ".gitignore").exists():
            d.mkdir(parents=True, exist_ok=True)  # hooks race here; never fail on "already exists"
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
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except tomllib.TOMLDecodeError as e:
        raise ProjectError(f"{path} is not valid TOML: {e}. Hint: fix the line, or delete the file and run `keelyard init`.") from None
    return Config(root=root, raw=raw)


def init(root: Path) -> Path:
    cfg = Config(root=root)
    if root in (Path.home().resolve(), Path(root.anchor)):
        raise ProjectError(f"refusing to set up keelyard in {root}. Hint: cd into a project folder first.")
    path = cfg.state / "config.toml"
    if not path.exists():
        path.write_text(DEFAULT_CONFIG)
    return path
