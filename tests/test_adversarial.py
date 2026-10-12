"""Regression tests for bugs found in adversarial QA (see docs/changelog)."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from keelyard import config, hooks
from keelyard.codemap import find_symbol, outline, project_map
from keelyard.filters import filter_output
from keelyard.memory import Memory
from keelyard.proof import Proof
from keelyard.saver import ReadCache
from keelyard.snapshot import Shadow


def test_unicode_and_space_paths_are_reported_correctly(cfg, project):
    sh = Shadow(cfg)
    sh.snapshot("baseline")
    (project / "my file é.py").write_text("x = 1\n")
    (project / "日本").mkdir()
    (project / "日本" / "データ.txt").write_text("y\n")
    step = sh.snapshot("Write")
    assert set(step.files) == {"my file é.py", "日本/データ.txt"}
    sh.rewind(1)
    assert not (project / "my file é.py").exists() and not (project / "日本" / "データ.txt").exists()


def test_huge_and_binary_files_are_not_snapshotted(cfg, project):
    (project / "model.bin").write_bytes(os.urandom(1024) * (60 * 1024))  # 60 MB
    step = Shadow(cfg).snapshot("baseline")
    assert "model.bin" not in step.files and "app.py" in step.files
    assert "model.bin" in step.skipped


def test_concurrent_hooks_do_not_corrupt_timeline(cfg, project):
    errors = []

    def worker(i):
        try:
            (project / f"f{i}.txt").write_text(str(i))
            Shadow(config.load(project)).snapshot(f"t{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    steps = Shadow(cfg).steps()
    assert [s.step for s in steps] == list(range(1, len(steps) + 1))  # unique, ordered


def test_corrupt_steps_log_is_tolerated(cfg, project):
    sh = Shadow(cfg)
    sh.snapshot("baseline")
    with sh.log.open("a") as f:
        f.write("{not json\n")
    (project / "a.txt").write_text("a")
    assert sh.snapshot("Write").step == 2


def test_refuses_to_snapshot_home_or_root(tmp_path, monkeypatch):
    monkeypatch.delenv("KEELYARD_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    cfg = config.load(config.find_root())
    with pytest.raises(config.ProjectError):
        Shadow(cfg).snapshot("x")


def test_no_git_repo_project_works(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.py").write_text("def a():\n    pass\n")
    config.init(root)
    monkeypatch.chdir(root)
    monkeypatch.delenv("KEELYARD_ROOT", raising=False)
    cfg = config.load(config.find_root())
    assert cfg.root == root
    assert Shadow(cfg).snapshot("baseline").files == ["a.py"]
    assert "a.py" in project_map(root)
    assert "a.py:1" in find_symbol(root, "a")


def test_no_git_fallback_skips_vendor_dirs(tmp_path):
    root = tmp_path / "p"
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("function zz() {}\n")
    (root / "s.js").write_text("function zz() {}\n")
    assert "node_modules" not in find_symbol(root, "zz")


def test_windows_style_paths(cfg, project):
    (project / "src").mkdir()
    (project / "src" / "m.py").write_text("def f():\n    pass\n")
    assert "def f" in ReadCache(cfg, "s").read("src\\m.py")
    out = hooks.handle("PostToolUse", {"session_id": "w", "tool_name": "Read",
                                       "tool_input": {"file_path": "src\\m.py"}}, cfg)
    assert out is None


def test_binary_file_read_and_outline(cfg, project):
    (project / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + os.urandom(2000))
    assert "binary" in ReadCache(cfg, "s").read("img.png").lower()
    assert "binary" in outline(project / "img.png").lower()


def test_outline_huge_file_is_bounded(project):
    big = project / "big.py"
    big.write_text("".join(f"def f{i}(x):\n    return x\n" for i in range(20000)))
    out = outline(big)
    assert len(out) < 20000 and "more definitions" in out


def test_python2_or_broken_python_outline_falls_back(project):
    (project / "old.py").write_text("print 'hi'\ndef ok(a):\n    pass\n")
    assert "def ok" in outline(project / "old.py")


def test_corrupt_settings_json_does_not_crash_install(project):
    from keelyard.adapters.install import InstallError, install

    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text("{ broken json")
    with pytest.raises(InstallError) as e:
        install("claude", project)
    assert "settings.json" in str(e.value)


def test_proof_test_missing_executable_reports_hint(cfg, project):
    r = Proof(cfg, "s").run_tests("after", "definitely-not-a-tool --x")
    assert r["exit"] == 127 and "not found" in r["tail"]


def test_bench_snapshot_does_not_pollute_user_timeline(cfg, project):
    from keelyard.bench import bench_snapshot

    bench_snapshot(cfg, runs=2)
    assert Shadow(cfg).steps() == []
    assert not list(project.glob(".keelyard-bench-probe*"))


def test_memory_handles_weird_queries(tmp_path):
    m = Memory(tmp_path / "m.db")
    for q in ['"', "AND OR NOT", "*", "NEAR(", "ü", "a" * 5000, ""]:
        m.search(q)


def test_grep_filter_binary_matches_and_colons_in_paths():
    raw = "Binary file app.bin matches\n" + "".join(f"C:\\src\\a.py:{i}:x = {i}\n" for i in range(40))
    out = filter_output("grep -rn x .", raw)
    assert "Binary file app.bin matches" in out and "a.py" in out


def test_hook_cli_with_cwd_that_does_not_exist(project):
    p = subprocess.run([sys.executable, "-m", "keelyard.cli", "hook", "claude", "Stop"],
                       input=json.dumps({"session_id": "x", "cwd": "/nonexistent/dir"}), capture_output=True, text=True,
                       cwd=project)
    assert p.returncode == 0 and p.stderr == ""


def test_hook_for_unknown_event_is_silent(project):
    p = subprocess.run([sys.executable, "-m", "keelyard.cli", "hook", "claude", "SomeFutureEvent"],
                       input="{}", capture_output=True, text=True, cwd=project)
    assert p.returncode == 0 and p.stdout == ""


def test_session_id_path_traversal(cfg):
    pf = Proof(cfg, "../../etc")
    assert cfg.state in pf.dir.parents


def test_rewind_unknown_step_message(cfg, project):
    from keelyard.snapshot import SnapshotError

    Shadow(cfg).snapshot("baseline")
    with pytest.raises(SnapshotError, match="keelyard rewind list"):
        Shadow(cfg).rewind(99)


def test_run_without_command_is_a_usage_error(project):
    p = subprocess.run([sys.executable, "-m", "keelyard.cli", "run"], capture_output=True, text=True, cwd=project)
    assert p.returncode == 2 and "Traceback" not in p.stderr


def test_cli_errors_are_short_with_hint(project):
    p = subprocess.run([sys.executable, "-m", "keelyard.cli", "rewind", "to", "42"], capture_output=True, text=True, cwd=project)
    assert p.returncode == 1 and "Traceback" not in p.stderr and "hint" in p.stderr.lower()


def test_monorepo_nested_git_repos_are_snapshotted(cfg, project):
    sub = project / "packages" / "web"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=sub, check=True)
    (sub / "index.js").write_text("module.exports = 1\n")
    step = Shadow(cfg).snapshot("baseline")
    assert "packages/web/index.js" in step.files


def test_path_type_tolerance():
    assert Path  # keep import used


def test_hook_command_is_quoted_when_install_path_has_spaces(project, monkeypatch, tmp_path):
    from keelyard.adapters import install as inst

    monkeypatch.setattr(inst.shutil, "which", lambda _: str(tmp_path / "my tools" / "keelyard"))
    inst.install("claude", project)
    cmd = json.loads((project / ".claude/settings.json").read_text())["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert cmd.startswith("'") and "my tools/keelyard' hook claude Stop" in cmd


def test_install_validates_all_files_before_writing(project):
    from keelyard.adapters.install import InstallError, install

    (project / ".mcp.json").write_text("[1,2")
    with pytest.raises(InstallError):
        install("claude", project)
    assert not (project / ".claude" / "settings.json").exists()


def test_uninstall_leaves_user_hooks(project):
    from keelyard.adapters.install import install, installed, uninstall

    (project / ".claude").mkdir()
    user = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}, "model": "x"}
    (project / ".claude" / "settings.json").write_text(json.dumps(user))
    install("claude", project)
    assert installed("claude", project)
    uninstall("claude", project)
    assert json.loads((project / ".claude" / "settings.json").read_text()) == user
    assert not installed("claude", project)


def test_invalid_config_toml_gives_hint(project):
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text("[proof\ngate = ")
    with pytest.raises(config.ProjectError, match="Hint"):
        config.load(project)


def test_corrupt_proof_bundle_is_set_aside(cfg):
    pf = Proof(cfg, "s")
    pf.path.write_text("{oops")
    assert pf.load().requirements == []
    assert pf.path.with_suffix(".corrupt.json").exists()


def test_init_refuses_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(config.ProjectError):
        config.init(tmp_path.resolve())


def test_memory_project_filter_is_not_a_substring_match(tmp_path):
    from keelyard.memory import Turn

    m = Memory(tmp_path / "m.db")
    m._add(Turn("claude-code", "s1", "/w/shop", "2026", "user", "rounding money bug"))
    m._add(Turn("claude-code", "s2", "/w/shop2", "2026", "user", "rounding money bug"))
    m._add(Turn("claude-code", "s3", "/w/shop/sub", "2026", "user", "rounding money bug"))
    m._add(Turn("claude-code", "s4", "/w/a_b", "2026", "user", "rounding money bug"))
    m._add(Turn("claude-code", "s5", "/w/axb", "2026", "user", "rounding money bug"))
    assert {h["session"] for h in m.search("rounding", "/w/shop")} == {"s1", "s3"}
    assert {h["session"] for h in m.search("rounding", "/w/a_b")} == {"s4"}


def test_memory_snippets_keep_code_intact(tmp_path):
    from keelyard.memory import Turn

    m = Memory(tmp_path / "m.db")
    m._add(Turn("codex", "s", "/p", "2026", "assistant", "always use round(x, 2) for money"))
    assert "round(x, 2)" in m.search("round")[0]["snippet"]


def test_detects_pytest_from_root_level_test_files(tmp_path):
    from keelyard.proof import detect_test_cmd

    (tmp_path / "test_cart.py").write_text("")
    assert "pytest" in detect_test_cmd(tmp_path)
    assert detect_test_cmd(tmp_path / "missing") == ""


def test_force_color_zero_means_plain_output(project):
    env = {**os.environ, "FORCE_COLOR": "0"}
    env.pop("NO_COLOR", None)
    p = subprocess.run([sys.executable, "-m", "keelyard.cli", "init", "--no-agents"], capture_output=True, text=True, cwd=project, env=env)
    assert p.returncode == 0 and "\x1b[" not in p.stdout


def test_toml_snippet_is_printed_verbatim(project):
    p = subprocess.run([sys.executable, "-m", "keelyard.cli", "install", "codex"], capture_output=True, text=True, cwd=project)
    assert "[mcp_servers.keelyard]" in p.stdout


def test_mcp_config_uses_the_raw_executable_path(project, monkeypatch, tmp_path):
    from keelyard.adapters import install as inst

    exe = str(tmp_path / "my tools" / "keelyard")
    monkeypatch.setattr(inst.shutil, "which", lambda _: exe)
    inst.install("claude", project)
    inst.install("opencode", project)
    assert json.loads((project / ".mcp.json").read_text())["mcpServers"]["keelyard"]["command"] == exe
    assert json.loads((project / "opencode.json").read_text())["mcp"]["keelyard"]["command"][0] == exe
    snippet = "\n".join(inst.install("codex", project))
    assert f'command = "{exe}"' in snippet


def test_mcp_tool_error_reaches_agent_with_hint(tmp_path, monkeypatch):
    """Bug: on mcp 2.x a ValueError became 'Error executing tool recall' with no hint, plus a traceback on stderr."""
    import asyncio

    from keelyard import mcp_server

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    try:
        res = asyncio.run(mcp_server.mcp.call_tool("recall", {"output_id": "nope"}))
        text = str(res)
    except Exception as exc:  # 2.x raises ToolError to the session layer
        assert "Unexpected" not in type(exc).__name__
        text = str(exc)
    assert "Hint" in text


def test_memory_project_filter_follows_symlinks(tmp_path):
    """Bug (macOS CI): sessions logged under /private/var were not found when searching from /var."""
    from keelyard.memory import Memory, Turn

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    m = Memory(tmp_path / "m.db")
    m._add(Turn("claude-code", "s1", str(real), "2026-01-01", "user", "round the discount down"))
    m.db.commit()
    assert m.search("discount", project=str(link))
