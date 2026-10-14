Review. Use before saying done, or when asked to review a change.

Check the diff (rewind_list, then git diff or the step diffs) against each item, in this order:
1. Correct: does it do what each requirement says? Edge cases: empty input, None, unicode, large input.
2. Safe: secrets, injection, unchecked input, destructive operations, error paths that swallow failures.
3. Tested: is every behaviour change covered by a test that would fail without it?
4. Small: remove dead code, debug prints, unrelated edits, and new dependencies you did not need.
5. Clear: names say what things are; comments say why, not what.
Report findings as path:line with a one-line reason, most serious first. Say "no findings" if there are none.
