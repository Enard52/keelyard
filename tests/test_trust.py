"""Adversarial tests: an agent (or a crash) trying to get a 'proven' it did not earn, or to lose user work."""

import json
import multiprocessing as mp
import sys

import pytest

from keelyard import config, hooks
from keelyard.proof import CLAIMED, COMMAND, VERIFIED, Proof, gate_status
from keelyard.snapshot import Shadow, SnapshotError

PYTEST = f"{sys.executable} -m pytest -q"
TEST = "from app import add\n\ndef test_add():\n    assert add(2, 2) == 4\n\ndef test_add_neg():\n    assert add(-1, 1) == 0\n"


def ev(event, **kw):
    return {"session_id": "s1", "hook_event_name": event, "cwd": ".", **kw}


def edit(cfg, project, rel, text):
    (project / rel).write_text(text, encoding="utf-8")
    hooks.handle("PostToolUse", ev("PostToolUse", tool_name="Edit", tool_input={"file_path": rel}), cfg)


@pytest.fixture
def started(cfg, project):
    (project / "tests" / "test_app.py").write_text(TEST, encoding="utf-8")
    hooks.handle("SessionStart", ev("SessionStart", source="startup"), cfg)
    return cfg


# (1) proof is bound to the file state ---------------------------------------------------------
def test_edit_after_passing_tests_reopens_the_proof(started, project):
    pf = Proof(started, "s1")
    edit(started, project, "app.py", "def add(a, b):\n    return a + b  # tidy\n")
    assert pf.run_tests("after", PYTEST)["exit"] == 0
    pf.auto_complete()
    assert pf.state() == "proven"
    (project / "app.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")  # sneaky edit, no hook fired
    gaps = pf.missing()
    assert pf.state() == "open" and any("Files changed after the last passing test run" in g for g in gaps)


# (2) evidence levels and forging ---------------------------------------------------------------
def test_evidence_levels_are_kept_apart(started, project):
    pf = Proof(started, "s1")
    edit(started, project, "app.py", "def add(a, b):\n    return b + a\n")
    pf.add_requirements(["add is commutative"])
    pf.check(1, "I looked at it")
    pf.record_shell_run("pytest -q", "2 passed in 0.01s", 0)
    pf.run_tests("after", PYTEST)
    lv = pf.levels()
    assert lv[CLAIMED] == 1 and lv[COMMAND] == 1 and lv[VERIFIED] == 1


def test_hand_edited_bundle_is_never_proven(started, project):
    pf = Proof(started, "s1")
    edit(started, project, "app.py", "def add(a, b):\n    return 0\n")
    assert pf.run_tests("after", PYTEST)["exit"] != 0
    d = json.loads(pf.path.read_text(encoding="utf-8"))
    d["test_runs"][-1]["exit"] = 0  # the agent "fixes" the evidence instead of the code
    pf.path.write_text(json.dumps(d), encoding="utf-8")
    gaps = pf.missing()
    assert pf.state() == "open" and "signature check failed" in gaps[0]
    d = json.loads(pf.path.read_text(encoding="utf-8"))
    d.pop("sig")  # removing the signature is no way out either
    pf.path.write_text(json.dumps(d), encoding="utf-8")
    assert pf.state() == "open"


def test_signature_key_lives_outside_the_project(started, project):
    Proof(started, "s1").add_requirements(["x"])
    assert not list(project.rglob("proof.key"))
    key = config.data_home() / "proof.key"
    assert key.exists() and (sys.platform == "win32" or oct(key.stat().st_mode)[-3:] == "600")


# (3) test weakening ----------------------------------------------------------------------------
@pytest.mark.parametrize("change, expect", [
    ("delete", "test file deleted"),
    ("skip", "skip/xfail/only added"),
    ("xfail", "skip/xfail/only added"),
    ("no_assert", "assertions removed"),
    ("drop_test", "tests removed"),
    ("config", "test config added"),
])
def test_weakened_tests_keep_the_proof_open(started, project, change, expect):
    pf = Proof(started, "s1")
    t = project / "tests" / "test_app.py"
    edit(started, project, "app.py", "def add(a, b):\n    return a + b\n\n")
    if change == "delete":
        t.unlink()
    elif change == "skip":
        t.write_text("import pytest\n" + TEST.replace("def test_add_neg", "@pytest.mark.skip\ndef test_add_neg"), encoding="utf-8")
    elif change == "xfail":
        t.write_text("import pytest\n" + TEST.replace("def test_add_neg", "@pytest.mark.xfail\ndef test_add_neg"), encoding="utf-8")
    elif change == "no_assert":
        t.write_text(TEST.replace("assert add(-1, 1) == 0", "add(-1, 1)"), encoding="utf-8")
    elif change == "drop_test":
        t.write_text(TEST.split("def test_add_neg")[0], encoding="utf-8")
    elif change == "config":
        (project / "pytest.ini").write_text("[pytest]\naddopts = --deselect tests/test_app.py::test_add_neg\n", encoding="utf-8")
    hooks.handle("PostToolUse", ev("PostToolUse", tool_name="Edit", tool_input={"file_path": "tests/test_app.py"}), started)
    pf.run_tests("after", PYTEST)
    pf.auto_complete()
    gaps = pf.missing()
    assert pf.state() == "open" and any(expect in g for g in gaps), gaps


def test_fewer_tests_ran_is_caught(started, project):
    pf = Proof(started, "s1")
    pf.run_tests("before", PYTEST)  # 2 passed
    edit(started, project, "app.py", "def add(a, b):\n    return a + b\n\n")
    pf.run_tests("after", f"{PYTEST} --deselect tests/test_app.py::test_add_neg")  # one test fewer
    assert any("fewer tests ran: 2 -> 1" in g for g in pf.missing())


def test_accepting_changed_tests_is_bound_to_those_files(started, project):
    pf = Proof(started, "s1")
    t = project / "tests" / "test_app.py"
    edit(started, project, "app.py", "def add(a, b):\n    return a + b\n\n")
    t.write_text(TEST.split("def test_add_neg")[0], encoding="utf-8")
    pf.run_tests("after", PYTEST)
    pf.auto_complete()
    pf.accept_tests("test_add_neg moved to test_math.py in the same change")
    assert pf.state() == "proven" and pf.levels()[CLAIMED] >= 1
    t.write_text(t.read_text(encoding="utf-8").replace("assert add(2, 2) == 4", "pass"), encoding="utf-8")
    pf.run_tests("after", PYTEST)
    assert any("assertions removed" in g for g in pf.missing())  # the old acknowledgement does not cover this


# (4) an unhooked gate is never green -------------------------------------------------------------
def test_gate_status_without_agents_is_unhooked(cfg):
    assert gate_status(cfg)["state"] == "unhooked"


def test_gate_status_wired_but_never_called_then_hooked(cfg, project):
    from keelyard.adapters.install import install

    install("claude", project)
    assert gate_status(cfg)["state"] == "unverified"
    hooks._seen(cfg, "claude", "SessionStart")
    assert gate_status(cfg)["state"] == "hooked"
    s = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    s["hooks"].pop("Stop")  # someone removes only the gate
    (project / ".claude" / "settings.json").write_text(json.dumps(s), encoding="utf-8")
    assert gate_status(cfg)["state"] == "unhooked"


# (5) parallel writers -------------------------------------------------------------------------------
def _add_req(root, i):
    cfg = config.load(root)
    Proof(cfg, "s1").add_requirements([f"req {i}"])


def _snap(root, i):
    cfg = config.load(root)
    (root / f"f{i}.txt").write_text(str(i), encoding="utf-8")
    Shadow(cfg).snapshot(tool="Edit", session=f"s{i}")


@pytest.mark.parametrize("fn", [_add_req, _snap])
def test_parallel_sessions_do_not_corrupt_state(cfg, project, fn):
    Shadow(cfg).snapshot("baseline")
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=fn, args=(project, i)) for i in range(12)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    if fn is _add_req:
        b = Proof(cfg, "s1").load()
        assert not b.tampered and sorted(r["text"] for r in b.requirements) == sorted(f"req {i}" for i in range(12))
    else:
        steps = Shadow(cfg).steps()
        assert [s.step for s in steps] == list(range(1, len(steps) + 1))
        assert set().union(*(s.files for s in steps[1:])) >= {f"f{i}.txt" for i in range(12)}


# (6) rewind never loses work ------------------------------------------------------------------------
def test_rewind_backs_up_files_snapshots_cannot_hold(cfg, project):
    sh = Shadow(cfg)
    (project / "notes.log").write_text("v1", encoding="utf-8")  # .gitignore'd: never snapshotted
    sh.snapshot("baseline")
    (project / "app.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    (project / "new.py").write_text("x = 1  # untracked user work\n", encoding="utf-8")
    sh.snapshot("Edit")
    (project / "draft.py").write_text("y = 2  # written after the last snapshot\n", encoding="utf-8")
    res = sh.rewind(1)
    assert "a + b" in (project / "app.py").read_text(encoding="utf-8")
    assert not (project / "draft.py").exists() and not (project / "new.py").exists()
    sh.rewind(res["safety_step"])  # and back: nothing was lost
    assert (project / "draft.py").read_text(encoding="utf-8").startswith("y = 2")
    assert (project / "new.py").exists() and (project / "notes.log").read_text(encoding="utf-8") == "v1"


def test_rewind_copies_aside_an_ignored_file_it_would_overwrite(cfg, project):
    sh = Shadow(cfg)
    (project / "cfg.yml").write_text("old", encoding="utf-8")
    sh.snapshot("baseline")
    (project / ".gitignore").write_text("*.log\ncfg.yml\n", encoding="utf-8")  # now ignored, still in step 1
    (project / "cfg.yml").write_text("precious local edits", encoding="utf-8")
    sh.snapshot("Edit")
    res = sh.rewind(1)
    assert "cfg.yml" in res["backed_up"]
    from pathlib import Path
    assert (Path(res["backup_dir"]) / "cfg.yml").read_text(encoding="utf-8") == "precious local edits"


def test_interrupted_rewind_is_detected_and_recovered(cfg, project, monkeypatch):
    sh = Shadow(cfg)
    sh.snapshot("baseline")
    (project / "app.py").write_text("def add(a, b):\n    return a * b  # latest\n", encoding="utf-8")
    sh.snapshot("Edit")
    real = sh._git

    def crash(*args, **kw):
        if args and args[0] == "checkout-index":
            raise KeyboardInterrupt  # power cut mid-restore
        return real(*args, **kw)

    monkeypatch.setattr(sh, "_git", crash)
    with pytest.raises(KeyboardInterrupt):
        sh.rewind(1)
    monkeypatch.setattr(sh, "_git", real)
    assert sh.interrupted()
    with pytest.raises(SnapshotError, match="recover"):
        sh.rewind(1)
    sh.recover()
    assert not sh.interrupted()
    assert "a * b  # latest" in (project / "app.py").read_text(encoding="utf-8")


# (7) secrets stay out ------------------------------------------------------------------------------
def test_secrets_never_enter_snapshots(cfg, project):
    (project / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-abcdefabcdefabcdef\n", encoding="utf-8")
    (project / ".env.example").write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")
    (project / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n", encoding="utf-8")
    sh = Shadow(cfg)
    st = sh.snapshot("baseline")
    assert ".env" not in st.files and "server.pem" not in st.files and ".env.example" in st.files
    assert b"sk-or-v1" not in sh._git("log", "-p", "--all")


def test_secret_already_snapshotted_by_an_old_version_is_dropped(cfg, project):
    (project / "creds.txt").write_text("token", encoding="utf-8")
    sh = Shadow(cfg)
    sh.snapshot("baseline")
    (project / ".keelyard" / "config.toml").write_text('[rewind]\nexclude = ["creds.txt"]\n', encoding="utf-8")
    sh2 = Shadow(config.load(project))
    sh2.snapshot("Edit")
    assert "creds.txt" not in sh2._names("ls-tree", "-r", "--name-only", sh2.steps()[-1].sha)
    assert (project / "creds.txt").exists()  # dropped from the timeline, never from disk


def test_include_secrets_is_opt_in(cfg, project):
    (project / ".keelyard").mkdir(exist_ok=True)
    (project / ".keelyard" / "config.toml").write_text("[rewind]\ninclude_secrets = true\n", encoding="utf-8")
    (project / ".env").write_text("A=1\n", encoding="utf-8")
    assert ".env" in Shadow(config.load(project)).snapshot("baseline").files
