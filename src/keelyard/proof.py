"""Proof-of-work: the evidence an agent must collect before it may say "done"."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .proc import split_cmd
from .redact import redact
from .snapshot import Shadow

TAIL = 4000

TEST_CMD = re.compile(r"(?<![\w-])(pytest|py\.test|unittest|tox|nox|(npm|pnpm|yarn|bun)( run)? test|jest|vitest|mocha|"
                      r"go test|cargo test|dotnet test|mvn test|gradle\w* test|make test|rspec|phpunit)(?![\w-])")
_FAIL = re.compile(r"\b[1-9]\d* (failed|errors?|failures?)\b|^(FAIL|FAILED|--- FAIL)\b|panicked at|test result: FAILED",
                   re.M | re.I)
_PASS = re.compile(r"\b\d+ passed\b|^ok\b|^OK\b|test result: ok|^PASS\b|\b\d+ tests? passed", re.M)


def is_test_cmd(cmd: str) -> bool:
    return bool(TEST_CMD.search(cmd or ""))


def parse_test_exit(output: str) -> int | None:
    """Exit status of a test run judged from its output: 0 passed, 1 failed, None unknown."""
    if _FAIL.search(output or ""):
        return 1
    if _PASS.search(output or ""):
        return 0
    return None


def summary_line(output: str) -> str:
    lines = [ln.strip(" =") for ln in (output or "").splitlines() if _PASS.search(ln) or _FAIL.search(ln)]
    return lines[-1][:160] if lines else ""


def detect_test_cmd(root: Path) -> str:
    if (root / "package.json").exists():
        try:
            pkg = json.loads((root / "package.json").read_text())
            if "test" in pkg.get("scripts", {}):
                return "npm test --silent"
        except json.JSONDecodeError:
            pass
    if (root / "Cargo.toml").exists():
        return "cargo test"
    if (root / "go.mod").exists():
        return "go test ./..."
    markers = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "conftest.py")
    if ((root / "tests").is_dir() or (root / "test").is_dir() or any((root / m).exists() for m in markers)
            or any(root.glob("test_*.py")) or any(root.glob("*_test.py"))):
        py = "python" if shutil.which("python") else "python3"
        return f"{py} -m pytest -q"
    return ""


@dataclass
class Bundle:
    session: str
    task: str = ""
    started: float = field(default_factory=time.time)
    requirements: list[dict] = field(default_factory=list)
    test_runs: list[dict] = field(default_factory=list)
    screenshots: list[dict] = field(default_factory=list)
    blocks: int = 0
    gate: list[dict] = field(default_factory=list)  # every Stop decision: {"ts", "blocked", "open"}


class Proof:
    def __init__(self, cfg: Config, session: str):
        self.cfg = cfg
        self.session = session
        self.dir = cfg.state / "proof" / session
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "bundle.json"
        self.opts = cfg.section("proof")

    # -- persistence --------------------------------------------------------
    def load(self) -> Bundle:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text())
                known = Bundle.__dataclass_fields__
                return Bundle(**{k: v for k, v in d.items() if k in known})
            except (ValueError, TypeError):
                self.path.replace(self.path.with_suffix(".corrupt.json"))  # keep it for inspection, start clean
        return Bundle(session=self.session)

    def save(self, b: Bundle) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(b.__dict__, indent=2))
        tmp.replace(self.path)

    # -- evidence -----------------------------------------------------------
    def set_task(self, task: str) -> None:
        b = self.load()
        if not b.task:
            b.task = redact(task)[:4000]
        b.blocks = 0  # a new user prompt resets the gate's reminder budget
        self.save(b)

    def add_requirements(self, items: list[str]) -> list[dict]:
        b = self.load()
        for text in items:
            text = text.strip()
            if text and not any(r["text"] == text for r in b.requirements):
                b.requirements.append({"id": len(b.requirements) + 1, "text": redact(text), "done": False, "evidence": ""})
        self.save(b)
        return b.requirements

    def check(self, req_id: int, evidence: str) -> dict:
        if not evidence.strip():
            raise ValueError("evidence is required: say what you ran or observed")
        b = self.load()
        for r in b.requirements:
            if r["id"] == req_id:
                r["done"], r["evidence"], r["ts"] = True, redact(evidence)[:2000], time.time()
                self.save(b)
                return r
        raise ValueError(f"no requirement {req_id}")

    def run_tests(self, phase: str, cmd: str | None = None, timeout: int = 900) -> dict:
        if phase not in ("before", "after"):
            raise ValueError("phase must be 'before' or 'after'")
        cmd = cmd or self.opts.get("test_cmd") or detect_test_cmd(self.cfg.root)
        if not cmd:
            raise ValueError("no test command found for this project. "
                             "Hint: pass --cmd \"npm test\" (MCP: command=...) or set [proof].test_cmd in .keelyard/config.toml")
        t0 = time.time()
        try:
            p = subprocess.run(split_cmd(cmd), cwd=self.cfg.root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)  # noqa: E501
            code, out = p.returncode, (p.stdout + p.stderr)
        except subprocess.TimeoutExpired as e:
            code, out = 124, f"timeout after {timeout}s\n{e.stdout or ''}"
        except FileNotFoundError:
            exe = shlex.split(cmd)[0]
            code, out = 127, f"{exe}: command not found. Hint: install it, or set [proof].test_cmd in .keelyard/config.toml"
        except ValueError as e:  # unbalanced quotes in the command
            code, out = 2, f"could not parse test command {cmd!r}: {e}"
        run = {"phase": phase, "cmd": cmd, "exit": code, "ts": time.time(), "seconds": round(time.time() - t0, 2),
               "tail": redact(out[-TAIL:])}
        b = self.load()
        b.test_runs.append(run)
        self.save(b)
        return run

    def record_shell_run(self, cmd: str, output: str, exit_code: int | None = None) -> dict | None:
        """A test command the agent ran in its own shell counts as a test run: no extra tool call needed."""
        if not is_test_cmd(cmd):
            return None
        code = exit_code if isinstance(exit_code, int) else parse_test_exit(output)
        if code is None:
            return None
        run = {"phase": "after" if self.last_edit_ts() is not None else "before", "cmd": cmd, "exit": code,
               "ts": time.time(), "seconds": 0, "tail": redact((output or "")[-TAIL:]), "source": "shell"}
        b = self.load()
        b.test_runs.append(run)
        self.save(b)
        return run

    def auto_complete(self) -> bool:
        """With no written checklist, a passing test run after the last edit proves the task itself."""
        b = self.load()
        if b.requirements or not self.opts.get("auto_requirements", True):
            return False
        last = self.last_edit_ts()
        after = [t for t in b.test_runs if t["phase"] == "after" and (last is None or t["ts"] >= last)]
        if not after or after[-1]["exit"] != 0:
            return False
        t = after[-1]
        b.requirements.append({"id": 1, "text": (b.task or "the task").strip().strip('"')[:200], "done": True,
                               "evidence": f"`{t['cmd']}` exit {t['exit']}: {summary_line(t['tail'])}".strip(),
                               "ts": time.time(), "auto": True})
        self.save(b)
        return True

    def screenshot(self, url: str | None = None) -> dict:
        url = url or self.opts.get("app_url")
        if not url:
            raise ValueError("no url given and [proof].app_url not set")
        out = self.dir / f"shot-{int(time.time() * 1000)}.png"
        err = _screenshot(url, out)
        if err:
            raise RuntimeError(err)
        shot = {"url": url, "path": str(out), "ts": time.time()}
        b = self.load()
        b.screenshots.append(shot)
        self.save(b)
        return shot

    # -- the gate -----------------------------------------------------------
    def last_edit_ts(self) -> float | None:
        edits = [s.ts for s in Shadow(self.cfg).steps()
                 if s.session == self.session and s.tool not in ("pre-rewind", "baseline", "stop")]
        return max(edits) if edits else None

    def missing(self) -> list[str]:
        """Return what still has to be proven. Empty list = proof complete."""
        b = self.load()
        last_edit = self.last_edit_ts()
        if last_edit is None:
            # nothing changed in this session: a pure Q&A turn needs no proof, but a checklist that
            # was written down still has to be ticked off
            return [f"Requirement #{r['id']} not verified: {r['text']}" for r in b.requirements if not r["done"]]
        gaps = []
        after = [t for t in b.test_runs if t["phase"] == "after" and t["ts"] >= last_edit]
        auto_ok = self.opts.get("auto_requirements", True) and after and after[-1]["exit"] == 0
        if not b.requirements and not auto_ok:
            gaps.append("No requirement checklist yet (proof_requirements, or `keelyard proof add`).")
        for r in b.requirements:
            if not r["done"]:
                gaps.append(f"Requirement #{r['id']} not verified: {r['text']}")
        after = [t for t in b.test_runs if t["phase"] == "after" and t["ts"] >= last_edit]
        if not after:
            gaps.append("No test run after the last edit (proof_run_tests phase='after', or `keelyard proof test after`).")
        elif after[-1]["exit"] != 0:
            gaps.append(f"The last test run failed with exit {after[-1]['exit']}. Fix it, then run the tests again.")
        if self.opts.get("app_url"):
            shots = [s for s in b.screenshots if s["ts"] >= last_edit]
            if not shots:
                gaps.append("No screenshot of the running app since the last edit (proof_screenshot, or `keelyard proof shot`).")
        return gaps


def _screenshot(url: str, out: Path) -> str | None:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.screenshot(path=str(out), full_page=True)
            browser.close()
        return None
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001 - surface any browser failure to the agent
        return f"screenshot failed: {e}"
    if shutil.which("npx"):
        p = subprocess.run(["npx", "--yes", "playwright", "screenshot", "--full-page", url, str(out)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        return None if p.returncode == 0 and out.exists() else f"npx playwright failed: {p.stderr[-500:]}"
    return "playwright not available: pip install 'keelyard[web]' && playwright install chromium"
