from keelyard import hooks
from keelyard.saver import ReadCache, compress_output, route


def test_compress_keeps_errors_and_collapses_noise():
    noise = "\n".join(f"Downloading chunk {i}/5000 ... ok" for i in range(5000))
    text = "\x1b[32mstart\x1b[0m\n" + noise + "\nERROR: build failed at step 7\n" + noise + "\ndone"
    out = compress_output(text, 2000)
    assert "ERROR: build failed at step 7" in out
    assert "\x1b[" not in out
    assert len(out) < 2000 and "similar lines" in out


def test_compress_progress_bars():
    out = compress_output("50%\r75%\r100% done\nnext")
    assert out.splitlines()[0] == "100% done"


def test_read_cache_dedupes_and_diffs(cfg, project):
    big = "".join(f"line {i}\n" for i in range(200))
    (project / "big.txt").write_text(big)
    rc = ReadCache(cfg, "s")
    first = rc.read("big.txt")
    assert "line 199" in first
    assert "unchanged" in rc.read("big.txt")
    (project / "big.txt").write_text(big.replace("line 100\n", "line one hundred\n"))
    diff = rc.read("big.txt")
    assert "diff only" in diff and "+line one hundred" in diff and len(diff) < len(first) / 3
    assert "line 5" in rc.read("big.txt", 1, 10)  # ranged reads always return content
    rc.reset()
    assert "line 199" in rc.read("big.txt")


def test_read_cache_refuses_escape(cfg, project):
    rc = ReadCache(cfg, "s")
    for bad in ["../outside.txt", "/etc/passwd", ".keelyard/config.toml"]:
        try:
            rc.read(bad)
        except (PermissionError, FileNotFoundError):
            continue
        raise AssertionError(bad)


def test_claude_read_dedupe_hook(cfg, project):
    ev = {"session_id": "s2", "tool_name": "Read", "tool_input": {"file_path": str(project / "app.py")}}
    assert hooks.handle("PreToolUse", ev, cfg) is None
    hooks.handle("PostToolUse", ev, cfg)
    deny = hooks.handle("PreToolUse", ev, cfg)
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
    hooks.handle("PreCompact", {"session_id": "s2"}, cfg)
    assert hooks.handle("PreToolUse", ev, cfg) is None  # after compaction the content is gone, allow


def test_route():
    assert route("rename variable foo to bar")["tier"] == "cheap"
    assert route("debug the race condition in the scheduler and find the root cause")["tier"] == "strong"


def test_read_cache_diff_is_exact_and_force_returns_full(cfg, project):
    import re

    base = [f"def f{i}():\n    return {i}\n" for i in range(120)]
    (project / "m.py").write_text("".join(base))
    rc = ReadCache(cfg, "s2")
    rc.read("m.py")
    new = base.copy()
    new[7], new[90] = "def f7():\n    return 'seven'\n", "def f90():\n    return None\n"
    (project / "m.py").write_text("".join(new))
    diff = rc.read("m.py")
    assert "diff only" in diff and "+    return 'seven'" in diff and "-    return 90" in diff
    # correctness: applying the diff to what the agent had gives exactly the new file
    old_lines, out, i = "".join(base).splitlines(), [], 0
    for hunk in re.split(r"^@@", diff, flags=re.M)[1:]:
        start = int(re.match(r" -(\d+)", hunk).group(1)) - 1
        out += old_lines[i:start]
        i = start
        for ln in hunk.splitlines()[1:]:
            if ln.startswith("-"):
                i += 1
            elif ln.startswith("+"):
                out.append(ln[1:])
            elif ln.startswith(" "):
                out.append(ln[1:])
                i += 1
    out += old_lines[i:]
    assert out == "".join(new).splitlines()
    full = rc.read("m.py", force=True)
    assert "return 'seven'" in full and "def f119" in full and "unchanged" not in full


def test_read_cache_never_bigger_than_the_file(cfg, project):
    (project / "tiny.txt").write_text("x = 1\n")
    rc = ReadCache(cfg, "s3")
    first = rc.read("tiny.txt")
    assert rc.read("tiny.txt") == first  # the 'unchanged' notice would cost more than the file
