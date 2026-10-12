"""Render bench/vs_rtk_results.json as docs/img/vs-rtk.png (needs matplotlib)."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

rows = [r for r in json.loads(Path("bench/vs_rtk_results.json").read_text()) if r["facts"]]
names = [r["command"] for r in rows]
fig, (a, b) = plt.subplots(1, 2, figsize=(11, 0.55 * len(rows) + 1.6), sharey=True)
y = range(len(rows))
h = 0.38
a.barh([i - h / 2 for i in y], [r["keelyard_tokens"] / r["raw_tokens"] * 100 for r in rows], h, label="keelyard", color="#2f6f4f")
a.barh([i + h / 2 for i in y], [r["rtk_tokens"] / r["raw_tokens"] * 100 for r in rows], h, label="rtk 0.51.0", color="#b08a3e")
a.set_yticks(list(y), names)
a.invert_yaxis()
a.set_xlabel("% of raw tokens the agent reads (lower is better)")
a.legend(loc="lower right", frameon=False)
b.barh([i - h / 2 for i in y], [r["keelyard_retention"] * 100 for r in rows], h, color="#2f6f4f")
b.barh([i + h / 2 for i in y], [r["rtk_retention"] * 100 for r in rows], h, color="#b08a3e")
b.set_xlabel("% of facts kept (higher is better)")
b.set_xlim(0, 105)
for ax in (a, b):
    ax.spines[["top", "right"]].set_visible(False)
fig.suptitle("Same commands, same outputs: tokens vs. information kept", x=0.02, ha="left", fontsize=12)
fig.tight_layout()
fig.savefig("docs/img/vs-rtk.png", dpi=160)
