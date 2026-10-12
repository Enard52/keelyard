import subprocess

import pytest

from keelyard.snapshot import Shadow, SnapshotError


def test_snapshot_rewind_fork(cfg, project, tmp_path):
    user_head = subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True).stdout
    sh = Shadow(cfg)
    s1 = sh.snapshot("baseline")
    assert s1.step == 1 and "app.py" in s1.files
    assert sh.snapshot("noop") is None  # unchanged tree -> no step

    (project / "app.py").write_text("def add(a, b):\n    return a - b  # broken\n")
    (project / "junk.py").write_text("x = 1\n")
    (project / "debug.log").write_text("ignored by .gitignore\n")
    s2 = sh.snapshot("Edit")
    assert set(s2.files) == {"app.py", "junk.py"}
    assert "a - b" in sh.diff(2)

    res = sh.rewind(1)
    assert (project / "app.py").read_text().endswith("a + b\n")
    assert not (project / "junk.py").exists()
    assert (project / "debug.log").exists()  # ignored files are never touched
    assert res["removed"] == ["junk.py"]

    sh.rewind(res["safety_step"])  # rewind is itself undoable
    assert "a - b" in (project / "app.py").read_text()

    dest = sh.fork(1, tmp_path / "fork")
    assert (dest / "app.py").read_text().endswith("a + b\n")
    with pytest.raises(SnapshotError):
        sh.fork(1, dest)

    # the user's own git repo is untouched
    assert not (project / ".git" / "refs" / "heads" / "timeline").exists()
    after = subprocess.run(["git", "log", "--oneline"], cwd=project, capture_output=True, text=True)
    assert after.returncode != 0 or after.stdout == ""
    assert user_head  # sanity: status was readable
