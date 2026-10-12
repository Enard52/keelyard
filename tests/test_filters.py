from keelyard import hooks
from keelyard.filters import filter_output, git_status

CARGO = """running 3 tests
test tests::ok_1 ... ok
test tests::ok_2 ... ok
test tests::bad_sum ... FAILED

failures:

---- tests::bad_sum stdout ----

thread 'tests::bad_sum' panicked at src/lib.rs:6:25:
assertion `left == right` failed: sum mismatch
  left: 4
 right: 5
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace


failures:
    tests::bad_sum

test result: FAILED. 2 passed; 1 failed; 0 ignored
"""

RUFF_FULL = """E501 Line too long (86 > 79)
  --> django/utils/_os.py:33:80
   |
33 |                     head, mode=parent_mode, exist_ok=exist_ok
   |                                                                ^^^^^
   |

E501 Line too long (90 > 79)
  --> django/utils/html.py:12:80
   |

Found 2 errors.
"""


def test_cargo_keeps_whole_failure_block():
    out = filter_output("cargo test", CARGO)
    for must in ["bad_sum", "sum mismatch", "left: 4", "right: 5", "test result: FAILED"]:
        assert must in out
    assert "ok_1" not in out and "RUST_BACKTRACE" not in out


def test_ruff_full_format_grouped_with_locations():
    out = filter_output("ruff check .", RUFF_FULL)
    assert "E501" in out and "_os.py:33:80" in out and "html.py:12:80" in out
    assert "^^^^" not in out


def test_pytest_failures_only():
    raw = "\n".join([f"test_x.py::test_ok[{i}] PASSED" for i in range(200)] + [
        "=================================== FAILURES ===================================",
        "___________________________________ test_bad ___________________________________",
        ">       assert parse('{}') == [1]", "E       KeyError: 'items'", "test_x.py:7: KeyError",
        "=========================== short test summary info ============================",
        "FAILED test_x.py::test_bad - KeyError: 'items'", "========================= 1 failed, 200 passed in 0.31s ========================="])
    out = filter_output("pytest -v", raw)
    assert "test_ok[5]" not in out
    for must in ["KeyError: 'items'", "test_x.py:7", "FAILED test_x.py::test_bad", "1 failed, 200 passed"]:
        assert must in out


def test_git_status_long_and_porcelain():
    long = "On branch main\nChanges not staged for commit:\n\tmodified:   a.py\n\tdeleted:    b.py\n\nUntracked files:\n\tc.md\n"
    assert git_status(long) == "branch main\nmodified (1): a.py\ndeleted (1): b.py\nuntracked (1): c.md"
    assert "untracked (1): n.txt" in git_status("## main\n M x.py\n?? n.txt\n")


def test_never_grows():
    assert filter_output("git status", "tiny") == "tiny"


def test_claude_bash_posttooluse_replaces_output(cfg, project):
    big = "\n".join(f"tests/test_a.py::test_{i} PASSED" for i in range(300))
    big += "\nFAILED tests/test_a.py::test_9 - boom\n= 1 failed, 299 passed ="
    ev = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "pytest -v"},
          "tool_response": {"stdout": big, "stderr": "", "interrupted": False, "isImage": False}}
    out = hooks.handle("PostToolUse", ev, cfg)
    new = out["hookSpecificOutput"]["updatedToolOutput"]
    assert set(new) == {"stdout", "stderr", "interrupted", "isImage"}
    assert "FAILED tests/test_a.py::test_9" in new["stdout"] and len(new["stdout"]) < len(big) / 5
    rid = new["stdout"].rsplit("keelyard recall ", 1)[1].rstrip("]")
    assert (cfg.state / "raw" / rid).read_text().startswith("tests/test_a.py::test_0")
    small = dict(ev, tool_response={"stdout": "ok", "stderr": "", "interrupted": False, "isImage": False})
    assert hooks.handle("PostToolUse", small, cfg) is None
