"""Mechanism 1 + 4: find code by symbol, jump to imports/callers/tests, page results without silent cuts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from keelyard import codemap
from keelyard.memory import Memory


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    (tmp_path / "shop").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "shop" / "cart.py").write_text(
        "from .money import round_cents\n\nclass Cart:\n    def total(self):\n        return round_cents(1)\n", encoding="utf-8")
    (tmp_path / "shop" / "money.py").write_text("def round_cents(x):\n    return x\n\ndef round_cents_up(x):\n    return x\n",
                                                encoding="utf-8")
    (tmp_path / "shop" / "api.py").write_text("from shop.cart import Cart\n# Cart in a comment\nc = Cart()\n", encoding="utf-8")
    (tmp_path / "tests" / "test_cart.py").write_text("from shop.cart import Cart\n\ndef test_total():\n    assert Cart().total() == 1\n",
                                                     encoding="utf-8")
    (tmp_path / "web" / "a.js").write_text("import { b } from './b'\nconst c = require('./c.js')\n", encoding="utf-8")
    (tmp_path / "web" / "b.js").write_text("export function b() {}\n", encoding="utf-8")
    (tmp_path / "web" / "c.js").write_text("module.exports = 1\n", encoding="utf-8")
    return tmp_path


def test_ranked_exact_first_and_paged(proj):
    hits = codemap.find_symbol_ranked(proj, "round_cents")
    assert hits[0].startswith("shop/money.py:1:")
    assert "round_cents_up" in hits[-1]
    pg = codemap.page(hits, 0, 1)
    assert pg["remaining"] == len(hits) - 1 and pg["next_offset"] == 1
    last = codemap.page(hits, 1, 10)
    assert last["remaining"] == 0 and "next_offset" not in last
    assert pg["items"] + last["items"] == hits  # nothing lost between pages


def test_references_skip_defs_and_comments_source_first(proj):
    refs = codemap.references(proj, "Cart")
    assert not any("class Cart" in r or "# Cart" in r for r in refs)
    assert refs[0].startswith("shop/") and refs[-1].startswith("tests/")


def test_related_imports_importers_tests(proj):
    r = codemap.related(proj, "shop/cart.py")
    assert r["imports"] == ["shop/money.py"]
    assert r["imported_by"] == ["shop/api.py"]
    assert r["tests"] == ["tests/test_cart.py"]
    assert codemap.related(proj, "./web/a.js")["imports"] == ["web/b.js", "web/c.js"]
    with pytest.raises(FileNotFoundError):
        codemap.related(proj, "nope.py")


def test_cli_find_offset_and_related(proj, monkeypatch, capsys):
    from keelyard.cli import main

    monkeypatch.chdir(proj)

    def run(*a):
        capsys.readouterr()
        assert main([*a, "--json"]) == 0
        return json.loads(capsys.readouterr().out)
    first = run("code", "find", "round_cents", "--limit", "1")
    assert first["remaining"] == 1 and first["next_offset"] == 1
    second = run("code", "find", "round_cents", "--limit", "1", "--offset", "1")
    assert second["remaining"] == 0 and second["matches"] != first["matches"]
    assert any(m.startswith("use ") for m in run("code", "find", "Cart", "--refs")["matches"])
    assert run("code", "related", "shop/cart.py")["tests"] == ["tests/test_cart.py"]


def test_memory_search_pages(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.db.executemany("INSERT INTO chunks(hash, agent, session, project, ts, role, text) VALUES (?,?,?,?,?,?,?)",
                     [(f"h{i}", "claude", f"s{i}", "/p", "2026-01-01", "user", f"stripe webhook number {i}") for i in range(5)])
    a = m.search_page("stripe", limit=2)
    assert len(a["hits"]) == 2 and a["total"] == 5 and a["remaining"] == 3 and a["next_offset"] == 2
    b = m.search_page("stripe", limit=10, offset=a["next_offset"])
    assert b["remaining"] == 0 and len(b["hits"]) == 3
    assert {h["session"] for h in a["hits"]}.isdisjoint(h["session"] for h in b["hits"])
