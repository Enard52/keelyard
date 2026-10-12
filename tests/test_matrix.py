import shutil
import subprocess
from pathlib import Path

import pytest
from matrix import run_all


def test_feature_matrix(tmp_path):
    bad = [f"{o.case.area}/{o.case.name}: {o.note}" for o in run_all(tmp_path) if not o.ok]
    assert not bad, "\n".join(bad)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_opencode_plugin_is_valid_javascript(tmp_path):
    src = Path(__file__).parents[1] / "src/keelyard/adapters/opencode_plugin.js"
    dst = tmp_path / "plugin.mjs"
    dst.write_text(src.read_text())
    assert subprocess.run(["node", "--check", str(dst)], capture_output=True).returncode == 0


def test_every_mcp_tool(tmp_path):
    import asyncio

    from matrix import make_project, run_mcp

    proj, env = make_project(tmp_path)
    (proj / ".keelyard").mkdir()
    subprocess.run(["git", "add", "-A"], cwd=proj)
    import sys

    subprocess.run([sys.executable, "-m", "keelyard.cli", "rewind", "snap"], cwd=proj, env=env, check=True)
    (proj / "app.py").write_text((proj / "app.py").read_text() + "# change\n")
    subprocess.run([sys.executable, "-m", "keelyard.cli", "rewind", "snap"], cwd=proj, env=env, check=True)
    res = asyncio.run(run_mcp(proj, env))
    bad = [f"{t} {a}: {n}" for t, a, ok, n in res if not ok]
    assert not bad, "\n".join(bad)
