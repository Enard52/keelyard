"""Which terse-output rule saves the most tokens (input + output) without losing facts? $0: local Ollama models only.

Every prompt runs once per (model, rule, seed). Tokens are Ollama's own counts: prompt_eval_count (input, so the
rule's real cost is included) and eval_count (output). "Facts" = the answer contains what the prompt needs
(an identifier, a fix, an error name); one point per prompt. Needs `ollama serve`; skips otherwise.
Writes bench/terse.json.

    python bench/terse.py [--models a,b] [--seeds 1,2,3] [--rules none,old,shipped,...]
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = (ROOT / "src/keelyard/adapters/guides/terse.md").read_text(encoding="utf-8").strip()
CART = (ROOT / "examples/arena/discount/repo/cart.py").read_text(encoding="utf-8")
BASE = "You are a coding agent in the user's repository."

RULES = {
    "none": "",
    "old": "Be terse: no preamble, no restating the question, no summary of what you are about to do.",
    "long": ("Reply with results only: no preamble, filler, restating or recap. "
             "Keep code, commands, paths, numbers and errors exact and complete."),
    "v1": "Answer with results only. Keep code, commands and errors exact.",
    "v2": "Terse: results only, no recap. Code, paths, numbers, errors exact and complete.",
    "v3": "Results only, no filler. Never drop code, numbers or error names.",
    "v4": "Be terse: answer first, no preamble or recap; keep code and facts complete.",
    "v5": "Be terse, but keep every code line, command, number and error name.",
    "v6": "Be terse. Keep code and facts.",
    "v7": "Be terse: no preamble or recap. Keep code exact.",
    "s1": "Reply only as:\nAnswer: <one line>\nCode: <only if needed>\nNo explanation unless asked.",
    "s2": "No prose. Reply with only the code, command or fix. Example:\nQ: Python: square every x in xs?\nA: `[x * x for x in xs]`",
    "s3": "Telegraphic: fragments, no sentences. Code, command or fix first. No explanation unless asked.",
    "s4": "Max 2 lines or one code block. No explanation unless asked.",
    "s5": "Answer in at most 2 lines: the code, command or fix itself. No prose, no explanation unless asked.",
    "s6": "Output only the answer: code, command, value or fix. No explanation, no markdown headings.",
    "shipped": SHIPPED,
}

# (prompt, groups of words: the answer must contain one word of every group)
CASES = [
    (f"{CART}\nMake total() apply coupon SAVE10 as 10% off. Show the new function.", [("def total",), ("0.9", "10", "0.1")]),
    (f"{CART}\nWhat does total([5, 5]) return?", [("10",)]),
    (f"{CART}\nUnknown coupons should raise. Which exception type fits best?", [("ValueError", "KeyError")]),
    (f"{CART}\nWrite a pytest test for total([1, 2]).", [("def test",), ("assert",), ("3",)]),
    (f"{CART}\nAdd a type hint for prices. Show the signature line.", [("def total",), ("list", "List", "Iterable", "Sequence")]),
    ("pytest says: ModuleNotFoundError: No module named 'cart'. Likely cause and fix?",
     [("path", "PYTHONPATH", "directory", "rootdir", "conftest", "install")]),
    ("Write a Python function is_even(n).", [("def is_even",), ("% 2",)]),
    ("Write a Python function that reverses a string s.", [("def",), ("[::-1]", "reversed")]),
    ("Write a JavaScript function add(a, b).", [("function add", "add =", "const add"), ("a + b",)]),
    ("git: how do I undo my last commit but keep the changes?", [("reset",), ("--soft", "HEAD~1", "HEAD^")]),
    ("git: how do I create and switch to a new branch called fix?", [("checkout -b fix", "switch -c fix")]),
    ("git: show the files changed in the last commit.", [("git show", "git diff", "git log")]),
    ("How do I run only one pytest test called test_save10?", [("-k", "::test_save10")]),
    ("How do I install the requests package with pip?", [("pip install requests",)]),
    ("Shell: count lines in file a.txt.", [("wc -l",)]),
    ("Shell: find all .py files under src.", [("find", "glob", "**"), (".py",)]),
    ("TypeError: unsupported operand type(s) for +: 'int' and 'str'. What is wrong?", [("str", "int")]),
    ("KeyError: 'price' when reading item['price']. Fix?", [("get(", "in item", "'price' in", "try")]),
    ("IndexError: list index out of range in xs[3] when xs has 3 items. Why?", [("0", "zero"), ("2", "len")]),
    ("AttributeError: 'NoneType' object has no attribute 'split'. Likely cause?", [("None",)]),
    ("RecursionError: maximum recursion depth exceeded. Most common cause?", [("base case", "terminat", "stop")]),
    ("JSONDecodeError: Expecting value: line 1 column 1. What does it usually mean?", [("empty", "not json", "not valid", "invalid", "HTML")]),
    ("Rename variable x to count in: x = 0\nfor i in range(3): x += i\nprint(x)", [("count = 0",), ("count +=",)]),
    ("Fix the bug: def area(r): return 3.14 * r * 2", [("r * r", "r ** 2", "r**2", "pow(r")]),
    ("Fix the bug: def last(xs): return xs[len(xs)]", [("-1", "len(xs) - 1", "len(xs)-1")]),
    ("Fix the bug: if x = 5: print(x)", [("==",)]),
    ("What HTTP status code means Not Found?", [("404",)]),
    ("What does SQL 'SELECT COUNT(*) FROM users' return?", [("number", "count", "rows")]),
    ("Python: read a file notes.txt into a string.", [("open(", "read_text"), ("read",)]),
    ("Python: sort a list of dicts people by key 'age'.", [("sort", "sorted"), ("age",)]),
    ("Explain in short what a Python list comprehension is, with one example.", [("[",), ("for",)]),
    ("Regex to match a 4-digit year.", [("\\d{4}", "[0-9]{4}")]),
]


def ask(model: str, system: str, prompt: str, seed: int) -> tuple[int, int, str]:
    body = {"model": model, "prompt": prompt, "system": system, "stream": False,
            "options": {"temperature": 0.3, "seed": seed, "num_predict": 600}}
    req = urllib.request.Request("http://localhost:11434/api/generate", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return int(d.get("prompt_eval_count", 0)), int(d.get("eval_count", 0)), d.get("response", "")


def facts(answer: str, need) -> bool:
    return all(any(w.lower() in answer.lower() for w in group) for group in need)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen-coder-1.5b")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--rules", default=",".join(RULES))
    ap.add_argument("--out", default=str(ROOT / "bench" / "terse.json"))
    a = ap.parse_args()
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
    except OSError:
        print("ollama is not running: skipped")
        return
    models, seeds, rules = a.models.split(","), [int(s) for s in a.seeds.split(",")], a.rules.split(",")
    res: dict = {"cases": len(CASES), "seeds": seeds, "rules": {r: RULES[r] for r in rules}, "results": {}}
    for model in models:
        for rule in rules:
            system = f"{BASE}\n{RULES[rule]}".strip()
            jobs = [(p, need, s) for s in seeds for p, need in CASES]
            with ThreadPoolExecutor(2) as ex:
                outs = list(ex.map(lambda j, m=model, sy=system: ask(m, sy, j[0], j[2]), jobs))
            r = {"input": sum(o[0] for o in outs), "output": sum(o[1] for o in outs),
                 "facts": sum(facts(o[2], j[1]) for o, j in zip(outs, jobs, strict=True)), "of": len(jobs)}
            r["total"] = r["input"] + r["output"]
            res["results"].setdefault(model, {})[rule] = r
            print(f"{model:18} {rule:8} in {r['input']:6} out {r['output']:6} total {r['total']:6} facts {r['facts']}/{r['of']}",
                  flush=True)
            Path(a.out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
