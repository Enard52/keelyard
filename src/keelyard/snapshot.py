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
from dataclasses import dataclass, field, fields
from pathlib import Path

from .config import VENDOR_DIRS, Config
from .locking import file_lock


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
    skipped: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)


# keelyard's own wiring files are not your work: rewinding must never remove or revert them.
EXCLUDE = (".keelyard/\n.git/\nnode_modules/\n.venv/\n__pycache__/\n"
           ".claude/skills/keelyard/\n.claude/commands/keelyard/\n.opencode/plugin/keelyard.js\n"
           ".opencode/command/keelyard-*.md\n")


WIRING = (".claude/", ".codex/", ".opencode/", "AGENTS.md", "CLAUDE.md", "opencode.json", ".mcp.json")


def user_first(files: list[str]) -> list[str]:
    """Your own files first, agent wiring (.claude/, AGENTS.md, ...) last, for display."""
    return sorted(files, key=lambda f: f.startswith(WIRING))


class Shadow:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.root
        state = cfg.root / ".keelyard"  # not cfg.state: that creates the folder, even in $HOME
        self.gitdir = state / "shadow.git"
        self.log = state / "steps.jsonl"
        self.lock = state / "timeline.lock"

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
            "GIT_OPTIONAL_LOCKS": "0",
        }
        env.pop("GIT_INDEX_FILE", None)
        try:
            p = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=self.root, env=env, input=input, capture_output=True)
        except FileNotFoundError:
            raise SnapshotError("git is not installed. Hint: install git (https://git-scm.com) - rewind needs it.") from None
        if check and p.returncode != 0:
            raise SnapshotError(f"git {' '.join(args)}: {p.stderr.decode(errors='replace').strip()}")
        return p.stdout

    def _names(self, *args: str) -> list[str]:
        return [f for f in self._git(*args, "-z").decode("utf-8", "surrogateescape").split("\0") if f]

    def _ensure(self) -> None:
        self.cfg.require_project()
        if (self.gitdir / "HEAD").exists():
            excl = self.gitdir / "info" / "exclude"
            try:
                if excl.read_text() != EXCLUDE:  # older timelines: pick up new exclusions
                    excl.write_text(EXCLUDE)
            except OSError:
                pass
            return
        self.cfg.state  # noqa: B018 - creates .keelyard with its .gitignore
        with file_lock(self.lock):
            if not (self.gitdir / "HEAD").exists():
                self._init_repo()

    def _init_repo(self) -> None:
        self.gitdir.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("config", "core.autocrlf", "false")
        self._git("config", "gc.auto", "0")
        excl = self.gitdir / "info" / "exclude"
        excl.parent.mkdir(exist_ok=True)
        excl.write_text(EXCLUDE)

    def steps(self) -> list[Step]:
        if not self.log.exists():
            return []
        out = []
        known = {f.name for f in fields(Step)}
        for line in self.log.read_text(errors="replace").splitlines():
            try:
                d = json.loads(line)
                out.append(Step(**{k: v for k, v in d.items() if k in known}))
            except (ValueError, TypeError):
                continue  # a torn or corrupted line must never break the timeline
        return out

    def get(self, n: int) -> Step:
        for s in self.steps():
            if s.step == n:
                return s
        last = self.steps()
        span = f"steps 1-{last[-1].step} exist" if last else "the timeline is empty"
        raise SnapshotError(f"no step {n} ({span}). Hint: run `keelyard rewind list`.")

    # -- operations ---------------------------------------------------------
    def snapshot(self, tool: str = "manual", session: str = "", note: str = "") -> Step | None:
        """Record the worktree. Returns None when nothing changed since the last step."""
        self._ensure()
        with file_lock(self.lock):
            return self._snapshot(tool, session, note)

    def _stage(self, parent: str | None) -> list[str]:
        """Stage the worktree into the shadow index; return paths skipped for size.

        Only paths that changed since the last snapshot are inspected, so a 7,000-file repo
        costs one `git add` plus a handful of stat calls per agent edit."""
        limit = float(self.cfg.section("rewind").get("max_file_mb", 20)) * 1024 * 1024
        self._git("add", "-A", "--ignore-errors", ".", check=False)
        nested = []
        skipped = []
        changed = (self._names("diff", "--cached", "--name-only", "--no-renames", parent) if parent
                   else self._names("ls-files", "--cached"))
        # whatever `git add` refused (empty nested repositories) is still untracked: usually nothing
        changed += self._names("ls-files", "--others", "--directory", "--exclude-standard")
        for rel in changed:
            path = self.root / rel
            if path.is_dir() and path.name not in VENDOR_DIRS:
                # `git add` skipped this dir: either it is (or holds) a nested repository, or all of it is ignored
                for dirpath, dirnames, _ in os.walk(path):
                    if (Path(dirpath) / ".git").exists():
                        nested.append(Path(dirpath).relative_to(self.root).as_posix())
                        dirnames[:] = []
                    else:
                        dirnames[:] = [d for d in dirnames if d not in VENDOR_DIRS]
                continue
            if path.is_dir():
                continue
            try:
                if path.is_file() and not path.is_symlink() and path.stat().st_size > limit:
                    skipped.append(rel)
            except OSError:
                continue
        # nested repositories (monorepos, vendored checkouts) would become opaque gitlinks: add their files
        for sub in nested:
            if any(part in VENDOR_DIRS for part in Path(sub).parts):
                continue
            self._git("rm", "--cached", "-q", "--ignore-unmatch", "--", sub, check=False)
            entries = []
            for dirpath, dirnames, filenames in os.walk(self.root / sub):
                dirnames[:] = [d for d in dirnames if d not in VENDOR_DIRS]
                for name in filenames:
                    p = Path(dirpath) / name
                    rel = p.relative_to(self.root).as_posix()
                    try:
                        if p.is_symlink() or p.stat().st_size > limit:
                            skipped.append(rel) if not p.is_symlink() else None
                            continue
                    except OSError:
                        continue
                    entries.append(rel)
            if entries:  # honour .gitignore and keelyard's excludes inside nested repositories too
                out = self._git("check-ignore", "--no-index", "--stdin", "-z", input="\0".join(entries).encode(), check=False)
                ignored = set(out.decode("utf-8", "surrogateescape").split("\0"))
                entries = [e for e in entries if e not in ignored]
            if entries:
                shas = self._git("hash-object", "-w", "--stdin-paths", input="\n".join(entries).encode()).decode().split()
                info = "".join(f"100644 {sha}\t{rel}\n" for sha, rel in zip(shas, entries, strict=True))
                self._git("update-index", "--add", "--index-info", input=info.encode())
        if skipped:
            self._git("rm", "--cached", "-q", "--ignore-unmatch", "--", *skipped, check=False)
        return sorted(skipped)

    def _snapshot(self, tool: str, session: str, note: str) -> Step | None:
        prev = self.steps()
        parent = prev[-1].sha if prev else None
        skipped = self._stage(parent)
        tree = self._git("write-tree").decode().strip()
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
            files = self._names("diff", "--name-only", parent, sha)
        else:
            files = self._names("ls-tree", "-r", "--name-only", sha)
        step = Step(prev[-1].step + 1 if prev else 1, sha, tool, session, time.time(), files, note, skipped)
        with self.log.open("a", encoding="utf-8") as f:
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
        self._ensure()
        with file_lock(self.lock):
            return self._rewind(n, target)

    def _rewind(self, n: int, target: Step) -> dict:
        safety = self._snapshot("pre-rewind", "", f"before rewind to {n}")
        cur_step = safety or self.steps()[-1]
        current = cur_step.sha
        added = self._names("diff", "--name-only", "--diff-filter=A", target.sha, current)
        for rel in added:
            p = self.root / rel
            if p.is_file() or p.is_symlink():
                p.unlink()
        self._git("read-tree", target.sha)
        self._git("checkout-index", "-a", "-f")
        after = self._snapshot("rewind", "", f"restored step {n}")
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
