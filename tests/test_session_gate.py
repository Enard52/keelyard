"""The session-bench gate: a task under 70% saving, or with lower success than baseline, fails."""
import json
import subprocess
import sys
from pathlib import Path

REPORT = Path(__file__).parents[1] / "bench" / "session" / "report.py"


def _run(tmp_path, rows, *args):
    f = tmp_path / "r.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return subprocess.run([sys.executable, str(REPORT), str(f), *args], capture_output=True, text=True)


def _r(task, setup, total, correct=True):
    return {"task": task, "setup": setup, "total": total, "correct": correct}


def test_gate_passes_at_70(tmp_path):
    p = _run(tmp_path, [_r("a", "baseline", 1000), _r("a", "lean", 300)])
    assert p.returncode == 0 and "pass" in p.stdout


def test_gate_flags_low_saving(tmp_path):
    p = _run(tmp_path, [_r("a", "baseline", 1000), _r("a", "lean", 400)])
    assert p.returncode == 1 and "FAIL" in p.stdout and "GATE FAIL" in p.stderr


def test_gate_flags_lost_quality(tmp_path):
    p = _run(tmp_path, [_r("a", "baseline", 1000), _r("a", "lean", 100, False)])
    assert p.returncode == 1


def test_gate_zero_is_report_only(tmp_path):
    assert _run(tmp_path, [_r("a", "baseline", 1000), _r("a", "lean", 900)], "--gate", "0").returncode == 0
