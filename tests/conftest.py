import subprocess

import pytest

from keelyard import config


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(2, 2) == 4\n")
    (root / ".gitignore").write_text("*.log\n")
    monkeypatch.setenv("KEELYARD_ROOT", str(root))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def cfg(project):
    return config.load(project)
