"""Rewind: a shadow git repository that snapshots the worktree after agent tool calls.

The shadow repo lives in .keelyard/shadow.git and never touches the user's own
.git (no commits, no stash, no index changes there). It honours .gitignore.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config


class SnapshotError(RuntimeError):
    pass


@dataclass
class Step:
    step: int
    sha: str
    tool: str
    session: str
    ts: float
    files: list[str]
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__)


class Shadow:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.root
        self.gitdir = cfg.state / "shadow.git"
        self.log = cfg.state / "steps.jsonl"

    # -- plumbing -----------------------------------------------------------
    def _git(self, *args: str, input: bytes | None = None, check: bool = True) -> bytes:
        env = {
            **os.environ,
            "GIT_DIR": str(self.gitdir),
            "GIT_WORK_TREE": str(self.root),
            "GIT_AUTHOR_NAME": "keelyard",
            "GIT_AUTHOR_EMAIL": "keelyard@localhost",
            "GIT_COMMITTER_NAME": "keelyard",
            "GIT_COMMITTER_EMAIL": "keelyard@localhost",
        }
        env.pop("GIT_INDEX_FILE", None)
        p = subprocess.run(["git", *args], cwd=self.root, env=env, input=input, capture_output=True)
        if check and p.returncode != 0:
            raise SnapshotError(f"git {' '.join(args)}: {p.stderr.decode(errors='replace').strip()}")
        return p.stdout

    def _ensure(self) -> None:
        if (self.gitdir / "HEAD").exists():
            return
        self.gitdir.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("config", "core.autocrlf", "false")
        self._git("config", "gc.auto", "0")
        excl = self.gitdir / "info" / "exclude"
        excl.parent.mkdir(exist_ok=True)
        excl.write_text(".keelyard/\n.git/\nnode_modules/\n.venv/\n__pycache__/\n")

    def steps(self) -> list[Step]:
        if not self.log.exists():
            return []
        out = []
        for line in self.log.read_text().splitlines():
            if line.strip():
                out.append(Step(**json.loads(line)))
        return out

    def get(self, n: int) -> Step:
        for s in self.steps():
            if s.step == n:
                return s
        raise SnapshotError(f"no step {n}")

    # -- operations ---------------------------------------------------------
    def snapshot(self, tool: str = "manual", session: str = "", note: str = "") -> Step | None:
        """Record the worktree. Returns None when nothing changed since the last step."""
        self._ensure()
        self._git("add", "-A", ".")
        tree = self._git("write-tree").decode().strip()
        prev = self.steps()
        parent = prev[-1].sha if prev else None
        if parent:
            prev_tree = self._git("rev-parse", f"{parent}^{{tree}}").decode().strip()
            if prev_tree == tree:
                return None
        args = ["commit-tree", tree, "-m", f"{tool} {note}".strip()]
        if parent:
            args[2:2] = ["-p", parent]
        sha = self._git(*args).decode().strip()
        self._git("update-ref", "refs/heads/timeline", sha)
        if parent:
            files = self._git("diff", "--name-only", parent, sha).decode().split()
        else:
            files = self._git("ls-tree", "-r", "--name-only", sha).decode().split()
        step = Step(prev[-1].step + 1 if prev else 1, sha, tool, session, time.time(), files, note)
        with self.log.open("a") as f:
            f.write(step.to_json() + "\n")
        return step

    def diff(self, n: int) -> str:
        s = self.get(n)
        parent = self._git("rev-list", "--parents", "-n1", s.sha).decode().split()[1:]
        if not parent:
            return self._git("show", "--stat", "--format=", s.sha).decode()
        return self._git("diff", parent[0], s.sha).decode(errors="replace")

    def rewind(self, n: int) -> dict:
        """Restore the worktree to step n. A safety snapshot is taken first, so rewind is undoable."""
        target = self.get(n)
        safety = self.snapshot(tool="pre-rewind", note=f"before rewind to {n}")
        cur_step = safety or self.steps()[-1]
        current = cur_step.sha
        added = [f for f in self._git("diff", "--name-only", "--diff-filter=A", target.sha, current).decode().splitlines() if f]
        for rel in added:
            p = self.root / rel
            if p.is_file() or p.is_symlink():
                p.unlink()
        self._git("read-tree", target.sha)
        self._git("checkout-index", "-a", "-f")
        after = self.snapshot(tool="rewind", note=f"restored step {n}")
        return {
            "restored": n,
            "removed": added,
            "safety_step": cur_step.step,
            "new_step": after.step if after else None,
        }

    def fork(self, n: int, dest: Path) -> Path:
        """Materialise step n into a separate directory to try another approach."""
        target = self.get(n)
        dest = dest.resolve()
        if dest.exists() and any(dest.iterdir()):
            raise SnapshotError(f"{dest} is not empty")
        dest.mkdir(parents=True, exist_ok=True)
        data = self._git("archive", "--format=tar", target.sha)
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            tf.extractall(dest, filter="data")
        return dest
