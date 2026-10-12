"""A deliberately minimal "agent": one request to an OpenAI-compatible endpoint, no tools, no retries.

It reads every .py file in the repo, asks the model for a new cart.py, writes it back, and prints a
Claude-Code-style result line so the arena can read token usage. Useful as a floor to compare real
agents against, and to try the arena without any agent CLI installed.

    python oneshot.py --model qwen-coder-1.5b --base-url http://localhost:11434/v1 "<prompt>"
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True)
ap.add_argument("--base-url", default="http://localhost:11434/v1")
ap.add_argument("prompt")
a = ap.parse_args()

files = "\n\n".join(f"# file: {p.name}\n{p.read_text()}" for p in sorted(Path(".").glob("*.py")))
msg = (f"{a.prompt}\n\nRepository:\n\n{files}\n\n"
       "Reply with the complete new contents of cart.py in one ```python code block and nothing else.")
req = urllib.request.Request(a.base_url.rstrip("/") + "/chat/completions", headers={"content-type": "application/json"},
                             data=json.dumps({"model": a.model, "temperature": 0.2,
                                              "messages": [{"role": "user", "content": msg}]}).encode())
with urllib.request.urlopen(req, timeout=600) as r:
    j = json.load(r)
text = j["choices"][0]["message"]["content"] or ""
m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
if m:
    Path("cart.py").write_text(m.group(1))
u = j.get("usage", {})
print(json.dumps({"type": "result", "usage": {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)},
                  "total_cost_usd": 0.0}))
sys.exit(0 if m else 1)
