"""Session-benchmark fixtures: each task builds a fresh git repo, gives the agent one prompt, and checks the result.

Task types: tiny / small / large repos; read-heavy, log-heavy, edit-heavy, Q&A. Checks are hidden from the agent
(run after the session), so a run only counts as correct if the repo or the answer is actually right.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PY = sys.executable


def _w(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _pytest(root: Path, *args: str) -> bool:
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=root,
                       capture_output=True, text=True, timeout=600)
    return r.returncode == 0


CART = "def total(prices, coupon=None):\n    return sum(prices)\n"
CART_TESTS = "".join(
    f"def test_sum_{i}():\n    from cart import total\n    assert total([{i}, 1]) == {i + 1}\n\n" for i in range(60))


def _large(root: Path, n: int = 120) -> None:
    """~120 modules of realistic filler; the facts the tasks need live in two of them."""
    files = {}
    for i in range(n):
        body = [f'"""Module {i}: helpers for service area {i % 9}."""', "", "import os", ""]
        for j in range(6):
            body += [f"def helper_{i}_{j}(value, scale={j + 1}):",
                     f'    """Scale value for area {i}, step {j}."""',
                     "    if value is None:", "        return 0",
                     f"    return (value * scale + {i}) % {97 + j}", ""]
        files[f"app/mod_{i:03d}.py"] = "\n".join(body)
    files["app/__init__.py"] = ""
    files["app/settings_net.py"] = ('"""Network settings."""\n\nDEFAULT_TIMEOUT = 37\n\n\n'
                                    "def parse_port(text):\n    return text.strip()\n")
    files["tests/test_net.py"] = ("from app.settings_net import parse_port\n\n\n"
                                  "def test_parse_port_strips():\n    assert str(parse_port(' 80 ')) == '80'\n")
    files["conftest.py"] = ""
    _w(root, files)


TAX_USERS = 12


def _edit_heavy(root: Path) -> None:
    files = {"billing/__init__.py": "", "billing/tax.py": "def calc_tax(amount):\n    return round(amount * 0.12, 2)\n",
             "conftest.py": ""}
    for i in range(TAX_USERS):
        files[f"billing/use_{i:02d}.py"] = (f"from billing.tax import calc_tax\n\n\n"
                                            f"def price_{i}(x):\n    return x + calc_tax(x)\n")
    files["tests/test_tax.py"] = ("from billing.tax import calc_tax\n\n\n"
                                  "def test_tax():\n    assert calc_tax(100) == 12.0\n")
    _w(root, files)


def _check_rename(root: Path, _answer: str) -> bool:
    text = "".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py") if ".keelyard" not in p.parts)
    if "calc_tax" in text or text.count("compute_tax") < TAX_USERS + 2:
        return False
    _w(root, {"tests/test_hidden_rename.py": ("from billing.tax import compute_tax\nfrom billing.use_03 import price_3\n\n\n"
                                               "def test_h():\n    assert compute_tax(100) == 12.0 and price_3(100) == 112.0\n")})
    return _pytest(root, "tests")


def _check_coupon(root: Path, _answer: str) -> bool:
    _w(root, {"test_hidden.py": ("from cart import total\n\n\ndef test_h():\n"
                                 "    assert total([10, 10], 'SAVE10') == 18\n    assert total([10, 10]) == 20\n")})
    return _pytest(root, "test_hidden.py")


def _check_port(root: Path, _answer: str) -> bool:
    _w(root, {"tests/test_hidden_port.py": ("from app.settings_net import parse_port\n\n\ndef test_h():\n"
                                            "    assert parse_port(' 8080 ') == 8080\n")})
    return _pytest(root, "tests")


def _check_area(root: Path, _answer: str) -> bool:
    _w(root, {"test_hidden.py": "from geo import area\n\n\ndef test_h():\n    assert abs(area(2) - 12.566) < 0.01\n"})
    return _pytest(root, "test_hidden.py")


TASKS = {
    "tiny-fix": {
        "setup": lambda r: _w(r, {"geo.py": "import math\n\n\ndef area(r):\n    return math.pi * r * 2\n",
                                  "test_geo.py": "from geo import area\n\n\ndef test_one():\n    assert round(area(1), 3) == 3.142\n"}),
        "prompt": "area() in geo.py should return the area of a circle of radius r. Fix it and run the tests.",
        "check": _check_area},
    "small-feature": {
        "setup": lambda r: _w(r, {"cart.py": CART, "test_cart.py": CART_TESTS}),
        "prompt": "Make total() in cart.py apply coupon 'SAVE10' as 10% off (other coupons: no discount). Run the tests.",
        "check": _check_coupon},
    "log-heavy": {
        "setup": lambda r: _w(r, {"cart.py": CART, "test_cart.py": CART_TESTS, "test_bulk.py": (
            "import pytest\nfrom cart import total\n\n\n@pytest.mark.parametrize('n', range(1500))\n"
            "def test_bulk_sum(n):\n    assert total([n, 1]) == n + 1\n")}),
        "prompt": ("Make total() in cart.py apply coupon 'SAVE10' as 10% off (other coupons: no discount). "
                   "Then run `python -m pytest -v` and confirm everything passes."),
        "check": _check_coupon},
    "read-heavy-large": {
        "setup": _large,
        "prompt": ("Somewhere in this project parse_port() returns a string; it must return an int "
                   "(strip spaces first). Find it, fix it, run the tests."),
        "check": _check_port},
    "edit-heavy": {
        "setup": _edit_heavy,
        "prompt": "Rename the function calc_tax to compute_tax everywhere in the project (definition and every use). Run the tests.",
        "check": _check_rename},
    "qa-large": {
        "setup": _large,
        "prompt": "Which file defines DEFAULT_TIMEOUT and what is its value? Do not change any file.",
        "check": lambda r, a: "37" in a and "settings_net" in a},
}
