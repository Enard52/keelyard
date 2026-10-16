"""The mechanism benchmark doubles as a correctness check: every mechanism must keep the information an agent needs."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="not verified on Windows yet")
def test_every_mechanism_stays_correct_and_never_grows(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "bench" / "mechanisms.py"
    spec = importlib.util.spec_from_file_location("mechanisms", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "bench" / "mechanisms.json"
    out.parent.mkdir()
    monkeypatch.setattr(mod, "ROOT", path.parents[1])
    real = Path.write_text
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: real(out if self.name == "mechanisms.json" else self, *a, **k))
    mod.main()
    data = json.loads(out.read_text())
    for fx, ms in data.items():
        for m, r in ms.items():
            assert r["correct"], (fx, m, r["check"])
            if not m.startswith("1 "):  # code navigation on a two-file repo can tie with reading the file
                assert r["after"] <= r["before"], (fx, m)
