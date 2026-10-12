"""Self-contained HTML proof report (fonts embedded, no network requests, safe to attach to a PR)."""

from __future__ import annotations

import base64
import datetime as dt
import html
from pathlib import Path

from . import __version__
from .proof import Proof
from .snapshot import Shadow
from .theme import page

QUIET = {"baseline", "pre-rewind", "rewind", "stop", "manual"}


def _t(ts: float, fmt: str = "%H:%M:%S") -> str:
    return dt.datetime.fromtimestamp(ts).strftime(fmt)


def _dur(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def render(proof: Proof) -> Path:
    b = proof.load()
    gaps = proof.missing()
    e = html.escape
    steps = [s for s in Shadow(proof.cfg).steps() if s.ts >= b.started - 1]
    edits = [s for s in steps if s.tool not in QUIET]
    done = sum(r["done"] for r in b.requirements)
    after = [t for t in b.test_runs if t["phase"] == "after"]
    last_ts = max([b.started] + [s.ts for s in steps] + [t["ts"] for t in b.test_runs])

    pill = ('<span class="pill ok">Proven</span>' if not gaps else
            f'<span class="pill warn">{len(gaps)} open item{"s" * (len(gaps) != 1)}</span>')
    h = ['<div class=brand><i></i>keelyard</div><h1>Proof of work</h1>',
         f'<p class=sub>{e(proof.cfg.root.name)} · session {e(b.session)} · {_t(b.started, "%d %b %Y, %H:%M")}</p>',
         f'<div style="margin-top:18px">{pill}</div>']
    files = sorted({f for s in edits for f in s.files})
    blocked = sum(g["blocked"] for g in b.gate)
    story = [f"The agent changed {len(files)} file{'s' * (len(files) != 1)}" if files else "The agent changed no files"]
    if blocked:
        story.append(f"was stopped {'once' if blocked == 1 else f'{blocked} times'} by the proof gate")
    story.append("finished with every requirement verified and tests passing" if not gaps else "has not proven the work yet")
    h.append(f"<p style='margin:22px 0 0;font-size:16px;color:var(--ink2);max-width:640px'>"
             f"{e(', '.join(story[:-1]) + (', and ' if len(story) > 1 else '') + story[-1])}.</p>")
    tests_state = "none" if not after else ("passing" if after[-1]["exit"] == 0 else f"exit {after[-1]['exit']}")
    h.append("<div class=stats>"
             f"<div class=stat><b>{done}/{len(b.requirements)}</b><span>requirements verified</span></div>"
             f"<div class=stat><b style='color:var(--{'green' if tests_state == 'passing' else ('ink' if tests_state == 'none' else 'red')})'>{e(tests_state)}</b><span>tests after last change</span></div>"
             f"<div class=stat><b>{len(edits)}</b><span>edits snapshotted</span></div>"
             f"<div class=stat><b>{_dur(last_ts - b.started)}</b><span>session length</span></div></div>")
    if b.task:
        h.append(f"<h2>Task</h2><div class=quote>{e(b.task)}</div>")
    if gaps:
        h.append("<h2>Still open</h2><div class=box>" + "".join(f"<div class=gap>{e(g)}</div>" for g in gaps) + "</div>")
    if b.requirements:
        h.append("<h2>Requirements</h2><div class=box>")
        for r in b.requirements:
            ev = f"<div class='e mono'>{e(r['evidence'])}</div>" if r.get("evidence") else "<div class=e>no evidence yet</div>"
            when = _t(r["ts"]) if r.get("ts") else ""
            h.append(f"<div class=row><span class='mark{' ok' if r['done'] else ''}'></span>"
                     f"<div><div class=t>{e(r['text'])}</div>{ev}</div><span class=r>{when}</span></div>")
        h.append("</div>")
    if b.test_runs:
        h.append("<h2>Test runs</h2><div class=box>")
        for i, t in enumerate(b.test_runs):
            ok = t["exit"] == 0
            label = f"{'Passed' if ok else 'Failed'}" if t["phase"] == "after" else f"Before · exit {t['exit']}"
            cls = "ok" if ok else ("bad" if t["phase"] == "after" else "warn")
            last = " open" if i == len(b.test_runs) - 1 and not ok else ""
            h.append(f"<details{last}><summary><span class='pill {cls}'>{e(label)}</span><code>{e(t['cmd'])}</code>"
                     f"<span class='r mono' style='color:var(--muted)'>{t['seconds']}s · {_t(t['ts'])}</span></summary>"
                     f"<pre>{e(t['tail'].strip())}</pre></details>")
        h.append("</div>")
    if b.screenshots:
        h.append("<h2>Screenshots</h2>")
        for s in b.screenshots:
            p = Path(s["path"])
            if p.exists():
                data = base64.b64encode(p.read_bytes()).decode()
                h.append(f"<div class=box style='margin-bottom:12px'><img class=shot src='data:image/png;base64,{data}' alt=''>"
                         f"<div class=gap style='border-top:1px solid var(--line)'>{e(s['url'])} · {_t(s['ts'])}</div></div>")
    events = [(s.ts, f"#{s.step}", s.tool + (f" → #{s.note.split()[-1]}" if s.tool == "rewind" and s.note else ""),
               ", ".join(s.files[:4]) + (f" +{len(s.files) - 4}" if len(s.files) > 4 else ""), s.tool in QUIET) for s in steps]
    events += [(t["ts"], "test", f"tests {t['phase']}", f"exit {t['exit']} · {t['cmd']}", True) for t in b.test_runs]
    events += [(g["ts"], "gate", "blocked" if g["blocked"] else ("finished" if not g["open"] else "let through"),
                f"{g['open']} open item{'s' * (g['open'] != 1)}" if g["open"] else "all proven", not g["blocked"]) for g in b.gate]
    if events:
        h.append("<h2>Timeline</h2><div class=box><ol class=tl>")
        for ts, n, what, detail, quiet in sorted(events, key=lambda x: x[0]):
            style = " style='color:var(--red)'" if what == "blocked" else (" style='color:var(--green)'" if what == "finished" else "")
            h.append(f"<li><span class=n>{e(n)}</span><span class='tm mono' style='color:var(--muted)'>{_t(ts)}</span>"
                     f"<span class='{'q' if quiet and not style else ''}'{style}>{e(what)}</span><span class=f>{e(detail)}</span></li>")
        h.append("</ol></div>")
    h.append(f"<footer><span>Evidence is what the agent ran on this machine. Read it before you trust it.</span>"
             f"<span class=mono>keelyard {__version__}</span></footer>")
    out = proof.dir / "report.html"
    out.write_text(page(f"Proof of work · {proof.cfg.root.name}", "".join(h)), encoding="utf-8")
    return out
