"""Summarize two OpenCode 2 session exports (baseline vs keelyard) into measured numbers.

Usage: python bench/real/summarize.py base.export.json keelyard.export.json
"""
import json
import sys


def load(path):
    d = json.loads(open(path, encoding="utf-8-sig").read())
    t = d["info"]["tokens"]
    calls = sum(1 for m in d["messages"] if m.get("type") == "assistant")
    tool_chars = sum(
        len("".join(x.get("text", "") for x in p["state"].get("content", [])))
        for m in d["messages"] for p in (m.get("content") or []) if p.get("type") == "tool"
    )
    return {"model_calls": calls, "input_uncached": t["input"], "input_cache_read": t["cache"]["read"],
            "input_total": t["input"] + t["cache"]["read"], "output": t["output"],
            "reasoning": t["reasoning"], "cost_usd": d["info"]["cost"], "tool_result_chars": tool_chars}


if __name__ == "__main__":
    print(json.dumps({"baseline": load(sys.argv[1]), "keelyard": load(sys.argv[2])}, indent=2))
