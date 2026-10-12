"""keelyard command line."""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

from . import __version__, config, session


def _cfg():
    return config.load()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="keelyard", description="Proof, rewind, helper swarm, usage saver and memory for AI coding agents.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create .keelyard/config.toml")
    p = sub.add_parser("install", help="wire hooks + MCP for an agent")
    p.add_argument("agent", choices=["claude", "codex", "opencode"])
    p = sub.add_parser("hook", help="hook entry point (called by agents)")
    p.add_argument("agent")
    p.add_argument("event")
    sub.add_parser("mcp", help="run the MCP stdio server")

    pr = sub.add_parser("proof", help="proof-of-work bundle").add_subparsers(dest="sub", required=True)
    pr.add_parser("status")
    x = pr.add_parser("req")
    x.add_argument("items", nargs="+")
    x = pr.add_parser("check")
    x.add_argument("id", type=int)
    x.add_argument("evidence")
    x = pr.add_parser("test")
    x.add_argument("phase", choices=["before", "after"])
    x.add_argument("--cmd", dest="test_cmd")
    x = pr.add_parser("shot")
    x.add_argument("url", nargs="?")
    pr.add_parser("report")

    p = sub.add_parser("timeline", help="list snapshots (-i for the interactive TUI)")
    p.add_argument("-i", action="store_true")
    sub.add_parser("snapshot", help="take a manual snapshot")
    p = sub.add_parser("diff")
    p.add_argument("step", type=int)
    p = sub.add_parser("rewind")
    p.add_argument("step", type=int)
    p = sub.add_parser("fork")
    p.add_argument("step", type=int)
    p.add_argument("dest", type=Path)

    p = sub.add_parser("swarm", help="run helper tasks from a JSON file ([{kind,prompt,files}])")
    p.add_argument("tasks", type=Path)
    p.add_argument("--model", help="[models.<key>] to use")

    sub.add_parser("compress", help="compress stdin like run_compact does")

    m = sub.add_parser("mem", help="unified memory").add_subparsers(dest="sub", required=True)
    m.add_parser("ingest")
    m.add_parser("stats")
    x = m.add_parser("search")
    x.add_argument("query")
    x.add_argument("--project")
    x.add_argument("--budget", type=int, default=2400)

    p = sub.add_parser("bench", help="measure savings on your own local data")
    p.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)

    if a.cmd == "init":
        print(config.init(config.find_root()))
    elif a.cmd == "install":
        from .adapters.install import install

        root = config.find_root()
        config.init(root)
        for line in install(a.agent, root):
            print("✓", line)
    elif a.cmd == "hook":
        from .hooks import main as hook_main

        return hook_main(a.agent, a.event)
    elif a.cmd == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main()
    elif a.cmd == "proof":
        from .proof import Proof
        from .report import render

        cfg = _cfg()
        pf = Proof(cfg, session.current(cfg))
        if a.sub == "status":
            gaps = pf.missing()
            print("PROVEN" if not gaps else "MISSING:\n- " + "\n- ".join(gaps))
            return 0 if not gaps else 1
        if a.sub == "req":
            print(json.dumps(pf.add_requirements(a.items), indent=1))
        elif a.sub == "check":
            print(json.dumps(pf.check(a.id, a.evidence)))
        elif a.sub == "test":
            r = pf.run_tests(a.phase, a.test_cmd)
            print(f"exit={r['exit']} {r['seconds']}s\n{r['tail'][-1500:]}")
            return 0 if r["exit"] == 0 else 1
        elif a.sub == "shot":
            print(json.dumps(pf.screenshot(a.url)))
        elif a.sub == "report":
            print(render(pf))
    elif a.cmd in ("timeline", "snapshot", "diff", "rewind", "fork"):
        from .snapshot import Shadow

        sh = Shadow(_cfg())
        if a.cmd == "timeline":
            if a.i:
                from .tui import run

                msg = run(sh)
                if msg:
                    print(msg)
            else:
                for s in sh.steps():
                    t = dt.datetime.fromtimestamp(s.ts).strftime("%H:%M:%S")
                    print(f"#{s.step:<4} {t} {s.tool:<12} {', '.join(s.files[:6])}")
        elif a.cmd == "snapshot":
            s = sh.snapshot("manual")
            print(f"#{s.step}" if s else "no changes")
        elif a.cmd == "diff":
            print(sh.diff(a.step))
        elif a.cmd == "rewind":
            print(json.dumps(sh.rewind(a.step)))
        elif a.cmd == "fork":
            print(sh.fork(a.step, a.dest))
    elif a.cmd == "swarm":
        from .swarm import Swarm, Task, format_results

        tasks = [Task(**t) for t in json.loads(a.tasks.read_text())]
        print(format_results(asyncio.run(Swarm(_cfg(), a.model).run(tasks))))
    elif a.cmd == "compress":
        from .saver import compress_output

        print(compress_output(sys.stdin.read(), _cfg().section("saver")["max_output_chars"]))
    elif a.cmd == "mem":
        from .memory import Memory, format_hits

        mem = Memory()
        if a.sub == "ingest":
            print(json.dumps(mem.ingest()))
        elif a.sub == "stats":
            print(json.dumps(mem.stats(), indent=1))
        else:
            print(format_hits(mem.search(a.query, a.project, a.budget)))
    elif a.cmd == "bench":
        from .bench import run_all

        res = run_all(_cfg())
        print(json.dumps(res, indent=2) if a.json else res["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
