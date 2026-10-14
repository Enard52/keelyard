#!/usr/bin/env bash
# The README hero recording. Everything shown is real keelyard output; the agent's own actions
# (edits and the hook calls Claude Code would make) are replayed silently between commands.
#   asciinema rec --cols 92 --rows 26 -c "bash docs/demo/hero.sh" hero.cast && agg hero.cast hero.gif
set -euo pipefail
HERE=$(cd "$(dirname "$0")/../.." && pwd)
export HOME=$(mktemp -d)  # the project shows as ~/shop, not a temp path
D=$HOME/shop && mkdir -p "$D" && cd "$D" && git init -q
git config user.email demo@example.com; git config user.name demo
cp "$HERE/examples/arena/discount/repo/"*.py .
hook() { echo "{\"session_id\":\"s1\",\"cwd\":\"$D\"$2}" | keelyard hook claude "$1" >/dev/null || true; }
edit() { hook PostToolUse ",\"tool_name\":\"$1\",\"tool_input\":{\"file_path\":\"$2\"}"; }
type() { printf '\033[38;5;245m$\033[0m '; for ((i = 0; i < ${#1}; i++)); do printf '%s' "${1:i:1}"; sleep 0.035; done; sleep 0.35; echo; }
say() { printf '\033[38;5;242m# %s\033[0m\n' "$1"; sleep 1.1; }
run() { type "$1"; eval "$1"; sleep "${2:-1.6}"; echo; }

clear
printf '\033[1mkeelyard\033[0m\033[38;5;245m  your coding agent has to prove its work, and every step can be undone\033[0m\n\n'
sleep 1.8
run "keelyard init --agent claude" 2.2
say "Claude Code works on: support coupon SAVE10, keep the tests green."
hook SessionStart ',"source":"startup"'
hook UserPromptSubmit ',"prompt":"Support coupon SAVE10 (10% off) in cart.total(). Keep the tests green."'
keelyard proof add "SAVE10 takes 10% off" "unknown coupons raise ValueError" >/dev/null
printf 'def total(prices, coupon=None):\n    return sum(prices) * (0.9 if coupon else 1)\n' > cart.py; edit Edit cart.py
printf 'from cart import total\n\n\ndef test_plain():\n    assert total([10, 5]) == 15\n' > test_cart.py; edit Write test_cart.py
hook Stop ''
say "It deleted three tests and tried to stop. The gate said no."
run "keelyard status" 2.4
run "keelyard rewind list" 1.8
run "keelyard rewind to 2" 2.0
cat > cart.py <<'PY'
COUPONS = {"SAVE10": 0.10}


def total(prices, coupon=None):
    subtotal = sum(prices)
    if coupon is None:
        return subtotal
    if coupon not in COUPONS:
        raise ValueError(f"unknown coupon: {coupon}")
    return round(subtotal * (1 - COUPONS[coupon]), 2)
PY
edit Edit cart.py
keelyard proof test after >/dev/null
keelyard proof check 1 "test_save10 passes" >/dev/null
keelyard proof check 2 "test_unknown_coupon_raises passes" >/dev/null
say "Tests restored, real fix written, evidence recorded."
run "keelyard proof status" 2.5
