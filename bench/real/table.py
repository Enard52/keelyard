"""Group OpenCode 2 session exports by run directory and print measured token totals.

Usage: python bench/real/table.py EXPORT_DIR > out.json
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from summarize import load  # noqa: E402

rows = {}
for f in sorted(pathlib.Path(sys.argv[1]).glob("*.json")):
    raw = f.read_text(encoding="utf-8-sig").strip()
    if not raw:
        continue
    d = json.loads(raw)
    name = d["info"].get("location", {}).get("directory", "").replace("\\", "/").rsplit("/", 1)[-1]
    rows[name] = load(str(f))
print(json.dumps(rows, indent=1, sort_keys=True))
