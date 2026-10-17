import subprocess

from keelyard.brain import rename_hint
from keelyard.config import load


def _repo(tmp_path):
    for i in range(3):
        (tmp_path / f"u{i}.py").write_text("from t import calc_tax\nx = calc_tax(1)\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("calc_taxes = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return load(tmp_path)


def test_rename_hint_lists_every_file_and_one_command(tmp_path):
    h = rename_hint(_repo(tmp_path), "Rename the function calc_tax to compute_tax everywhere.")
    assert "6 uses in 3 files" in h and "u0.py u1.py u2.py" in h and "other.py" not in h
    assert "perl -pi -e" in h


def test_no_hint_without_rename(tmp_path):
    assert rename_hint(_repo(tmp_path), "Fix the bug in calc_tax") == ""
