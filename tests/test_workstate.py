"""Mechanism 5: compact work state where every conclusion links to checkable evidence."""
import pytest

from keelyard import brain
from keelyard.proof import Proof
from keelyard.snapshot import Shadow
from keelyard.workstate import WorkState


def test_decisions_need_valid_refs(cfg):
    ws = WorkState(cfg, "s1")
    ws.add("decision", "add stays pure", "app.py:2")
    ws.add("decision", "suite is the oracle", "cmd: python -m pytest -q")
    for bad in ["", "app.py:99", "nope.py", "../x.py", "#7"]:
        with pytest.raises(ValueError):
            ws.add("decision", "x", bad)
    ws.add("question", "is negative input allowed?", "")  # questions may be open without evidence
    out = ws.render()
    assert "add stays pure → app.py:2" in out and "cmd: python -m pytest -q" in out and "Open questions" in out


def test_stale_ref_is_flagged_and_resolve_hides_question(cfg, project):
    ws = WorkState(cfg, "s1")
    ws.add("decision", "line two matters", "app.py:2")
    q = ws.add("question", "why?", "")
    (project / "app.py").write_text("x = 1\n")
    out = ws.render()
    assert "STALE" in out and "1 lines" in out
    ws.resolve(q["id"])
    assert "why?" not in ws.render()


def test_requirements_and_changes_in_state_and_brief(cfg, project):
    pf = Proof(cfg, "s1")
    pf.add_requirements(["handle empty cart"])
    sh = Shadow(cfg)
    sh.snapshot("base", session="s1")
    (project / "app.py").write_text("def add(a, b):\n    return b + a\n")
    sh.snapshot("Edit", session="s1")
    ws = WorkState(cfg, "s1")
    ws.add("decision", "commutative is fine", "app.py:2")
    out = ws.render()
    assert "#1 [ ] handle empty cart" in out and "app.py (step" in out
    b = brain.brief(cfg, "s1", budget_tokens=600)
    assert "commutative is fine → app.py:2" in b and b.count("handle empty cart") == 1


def test_empty_state_costs_nothing(cfg):
    assert WorkState(cfg, "nobody").render() == ""


def test_render_respects_budget(cfg):
    ws = WorkState(cfg, "s1")
    for i in range(60):
        ws.add("decision", f"decision number {i} with a long explanation text", "app.py:1")
    out = ws.render(120)
    assert len(out) // 4 <= 130 and "more: keelyard state" in out


def test_brief_is_stable_for_prompt_caching(cfg, project):
    """Same state, same brief, byte for byte: a volatile brief would bust the provider's prompt cache every session."""
    import re

    ws = WorkState(cfg, "s9")
    ws.add("decision", "keep add pure", "app.py:1")
    a = brain.brief(cfg, "s9", budget_tokens=600)
    b = brain.brief(cfg, "s9", budget_tokens=600)
    assert a == b
    assert not re.search(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d|\b\d{10}\.\d+", a)  # no timestamps
