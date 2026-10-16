"""Does the terse-output rule cut output tokens without dropping what matters? $0: local Ollama model only.

Runs each prompt with three system prompts: no rule, the old one-line "Be terse" rule, and the shipped rule
(src/keelyard/adapters/guides/terse.md). Counts output tokens as reported by Ollama (eval_count), and checks
every answer still contains the facts the prompt needs (an identifier, a fix, an error name).
Needs `ollama serve` with a local model; skips otherwise. Writes bench/terse.json.

    python bench/terse.py [model]
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULE = (ROOT / "src/keelyard/adapters/guides/terse.md").read_text(encoding="utf-8").strip()
OLD = "Be terse: no preamble, no restating the question, no summary of what you are about to do."
CART = (ROOT / "examples/arena/discount/repo/cart.py").read_text(encoding="utf-8")

# (prompt, words that must appear in a correct answer; any one of each tuple)
CASES = [
    (f"{CART}\nMake total() apply coupon SAVE10 as 10% off. Show the new function.", [("def total",), ("0.9", "10", "0.1")]),
    (f"{CART}\nWhat does total([5, 5]) return?", [("10",)]),
    (f"{CART}\nUnknown coupons should raise. Which exception type fits best?", [("ValueError", "KeyError")]),
    ("pytest says: ModuleNotFoundError: No module named 'cart'. Likely cause and fix?",
     [("path", "PYTHONPATH", "directory", "rootdir", "conftest")]),
    ("Write a Python function is_even(n).", [("def is_even",), ("% 2",)]),
    ("git: how do I undo my last commit but keep the changes?", [("reset",), ("--soft", "HEAD~1", "HEAD^")]),
    ("Explain in short what a Python list comprehension is, with one example.", [("[",), ("for",)]),
    ("TypeError: unsupported operand type(s) for +: 'int' and 'str'. What is wrong?", [("str", "int")]),
    ("Rename variable x to count in: x = 0\nfor i in range(3): x += i\nprint(x)", [("count = 0",), ("count +=",)]),
    ("How do I run only one pytest test called test_save10?", [("-k", "::test_save10")]),
]


def ask(model: str, system: str, prompt: str) -> tuple[int, str]:
    body = {"model": model, "prompt": prompt, "system": system, "stream": False,
            "options": {"temperature": 0, "seed": 1, "num_predict": 700}}
    req = urllib.request.Request("http://localhost:11434/api/generate", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return int(d.get("eval_count", 0)), d.get("response", "")


def correct(answer: str, need) -> bool:
    return all(any(w.lower() in answer.lower() for w in group) for group in need)


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen-coder-1.5b"
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
    except OSError:
        print("ollama is not running: skipped")
        return
    base = "You are a coding agent in the user's repository."
    variants = {"none": base, "old 'Be terse'": f"{base}\n{OLD}", "terse rule": f"{base}\n{RULE}"}
    res: dict = {"model": model, "rule_tokens": round(len(RULE) / 4), "old_rule_tokens": round(len(OLD) / 4), "variants": {}}
    for name, system in variants.items():
        out = [ask(model, system, p) for p, _ in CASES]
        res["variants"][name] = {"output_tokens": sum(n for n, _ in out),
                                 "correct": sum(correct(a, need) for (n, a), (_, need) in zip(out, CASES, strict=True)),
                                 "cases": len(CASES), "per_case": [n for n, _ in out]}
    (ROOT / "bench" / "terse.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    for name, v in res["variants"].items():
        print(f"{name:16} output tokens {v['output_tokens']:5}  correct {v['correct']}/{v['cases']}")
    print(f"rule costs ~{res['rule_tokens']} input tokens per request (old line ~{res['old_rule_tokens']})")


if __name__ == "__main__":
    main()
