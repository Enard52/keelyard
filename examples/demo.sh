#!/usr/bin/env bash
# Replays what Claude Code sends to keelyard's hooks, in a throwaway project.
# Run: bash examples/demo.sh   (needs keelyard on PATH)
set -euo pipefail
D=$(mktemp -d)/shop && mkdir -p "$D/tests" && cd "$D" && git init -q
printf 'def total(prices):\n    return sum(prices)\n' > cart.py
printf 'from cart import total\n\ndef test_total():\n    assert total([1, 2]) == 3\n' > tests/test_cart.py
hook() { echo "{\"session_id\":\"demo\",\"cwd\":\"$D\"$2}" | keelyard hook claude "$1"; }

echo "== session starts, user asks for a discount feature"
hook SessionStart ',"source":"startup"'
hook UserPromptSubmit ',"prompt":"add a 10% discount to total()"'

echo "== agent edits a file and deletes the tests (oops)"
printf 'def total(prices, discount=0.1):\n    return sum(prices) * (1 - discount)\n' > cart.py
hook PostToolUse ',"tool_name":"Edit","tool_input":{"file_path":"cart.py"}'
rm -rf tests
hook PostToolUse ',"tool_name":"Bash","tool_input":{"command":"rm -rf tests"}'

echo "== agent tries to stop: the gate answers"
hook Stop ',"stop_hook_active":false'

echo "== timeline, then rewind the deletion but keep the edit"
keelyard timeline
keelyard rewind 2 >/dev/null
ls tests && cat cart.py

echo "== agent proves the work"
keelyard proof req "total() applies a 10% discount by default" "existing tests still pass"
printf 'from cart import total\n\ndef test_discount():\n    assert round(total([10]), 2) == 9.0\n' > tests/test_discount.py
printf 'from cart import total\n\ndef test_total():\n    assert round(total([1, 2], 0), 2) == 3\n' > tests/test_cart.py
hook PostToolUse ',"tool_name":"Write","tool_input":{"file_path":"tests/test_discount.py"}'
keelyard proof test after | head -1
keelyard proof check 1 "tests/test_discount.py: total([10]) == 9.0 passes"
keelyard proof check 2 "tests/test_cart.py restored via rewind and passes"
hook Stop ',"stop_hook_active":true' && echo "(no output = gate open)"
echo "== report: $(keelyard proof report)"
