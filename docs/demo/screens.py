"""Render every terminal surface to docs/img/cli-*.png from real command output.

    python docs/demo/screens.py      # needs google-chrome (or chromium) for SVG -> PNG
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import TerminalTheme
from rich.text import Text

ROOT = Path(__file__).resolve().parents[2]
IMG = ROOT / "docs" / "img"
THEME = TerminalTheme((17, 17, 16), (237, 237, 234), [
    (28, 28, 26), (240, 119, 107), (92, 184, 138), (224, 164, 78), (108, 143, 179), (180, 142, 173), (127, 180, 180), (201, 201, 196),
    (107, 107, 102), (240, 119, 107), (92, 184, 138), (224, 164, 78), (108, 143, 179), (180, 142, 173), (127, 180, 180), (237, 237, 234)])


def fix_svg(svg: str) -> str:
    """Use the installed Geist Mono instead of rich's Fira Code web font, and give the SVG a real size."""
    import re

    svg = re.sub(r"@font-face\s*\{.*?\}", "", svg, flags=re.S)
    svg = svg.replace("Fira Code", "Geist Mono")
    svg = re.sub(r"<circle[^>]*/>", "", svg)  # no fake macOS window buttons
    w = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    return svg.replace('<svg class="rich-terminal"', f'<svg width="{w.group(1)}" height="{w.group(2)}" class="rich-terminal"', 1)


def sh(cmd: str, cwd: Path, env: dict) -> str:
    p = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True)
    return p.stdout + p.stderr


def render(name: str, title: str, transcript: list[tuple[str, str]]) -> Path:
    con = Console(record=True, width=96, force_terminal=True, color_system="truecolor", file=open(os.devnull, "w"))
    for cmd, out in transcript:
        con.print(Text.assemble(("$ ", "#6B6B66"), (cmd, "bold #EDEDEA")))
        con.print(Text.from_ansi(out.rstrip("\n")))
        con.print()
    svg = con.export_svg(title=title, theme=THEME, font_aspect_ratio=0.6)
    return to_png(name, fix_svg(svg))


def to_png(name: str, svg: str) -> Path:
    (IMG / f"{name}.svg").write_text(svg)
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    png = IMG / f"{name}.png"
    if chrome:
        html = Path(tempfile.mkdtemp()) / "s.html"
        html.write_text(f"<html><body style='margin:0;padding:24px;background:#FAFAF9;display:inline-block'>{svg}</body></html>")
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=2",
                        "--window-size=1900,1600", f"--screenshot={png}", html.as_uri()], capture_output=True)
        try:
            from PIL import Image, ImageChops

            im = Image.open(png).convert("RGB")
            box = ImageChops.difference(im, Image.new("RGB", im.size, im.getpixel((2, 2)))).getbbox()
            if box:
                im.crop((0, 0, min(im.width, box[2] + 48), box[3] + 48)).save(png, optimize=True)
        except ImportError:
            pass
    return png


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    home = tmp / "home"
    proj = home / "shop"  # shown as ~/shop: no build-machine paths in public screenshots
    proj.mkdir(parents=True)
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    exe = Path(sys.executable).parent / ("keelyard.exe" if os.name == "nt" else "keelyard")
    (bindir / exe.name).symlink_to(exe)
    for f in (ROOT / "examples/arena/discount/repo").glob("*.py"):
        shutil.copy(f, proj)
    env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR",)}
    env["PATH"] = str(bindir) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.update(FORCE_COLOR="1", COLUMNS="96", TERM="xterm-256color", HOME=str(home), XDG_DATA_HOME=str(tmp / "xdg"))
    env.pop("KEELYARD_ROOT", None)
    subprocess.run(["git", "init", "-q"], cwd=proj, env=env, check=True)
    ky = "keelyard"
    hook = lambda ev, extra="": subprocess.run(  # noqa: E731
        f"{ky} hook claude {ev}", shell=True, cwd=proj, env=env, capture_output=True,
        input=f'{{"session_id":"s1","cwd":"{proj}"{extra}}}', text=True)
    c = lambda cmd: (cmd, sh(cmd, proj, env))  # noqa: E731

    init = c("keelyard init --agent claude")
    hook("SessionStart", ',"source":"startup"')
    hook("UserPromptSubmit", ',"prompt":"Support coupon SAVE10 (10% off) in cart.total(). Keep the tests green."')
    sh(f'{ky} proof add "SAVE10 takes 10% off" "unknown coupons raise ValueError"', proj, env)
    (proj / "cart.py").write_text("def total(prices, coupon=None):\n    return sum(prices) * (0.9 if coupon else 1)\n")
    hook("PostToolUse", ',"tool_name":"Edit","tool_input":{"file_path":"cart.py"}')
    (proj / "test_cart.py").write_text("from cart import total\n\n\ndef test_plain():\n    assert total([10, 5]) == 15\n")
    hook("PostToolUse", ',"tool_name":"Write","tool_input":{"file_path":"test_cart.py"}')
    hook("Stop")
    status = c("keelyard status")
    lst = c("keelyard rewind")
    show = c("keelyard rewind show 3")
    to = c("keelyard rewind to 2")
    render("cli-init", "keelyard init", [init])
    render("cli-status", "keelyard status", [status])
    render("cli-rewind", "keelyard rewind", [lst, to])
    render("cli-rewind-show", "keelyard rewind show", [show])
    render("cli-doctor", "keelyard doctor", [c("keelyard doctor")])
    render("cli-help", "keelyard --help", [c("keelyard --help")])
    render("cli-error", "errors", [c("keelyard rewind to 42"), c("keelyard run")])
    render("cli-json", "--json", [c("keelyard proof status --json")])
    render("cli-selftest", "keelyard selftest", [c("keelyard selftest")])
    timeline_shots(proj)
    print(f"wrote {IMG}/cli-*.png and timeline*.png")


def timeline_shots(proj: Path) -> None:
    """The full-screen timeline, driven by textual's test pilot."""
    import asyncio

    from keelyard import config
    from keelyard.snapshot import Shadow
    from keelyard.tui import Timeline

    async def shoot(name: str, confirm: bool) -> None:
        app = Timeline(Shadow(config.load(proj)))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("down", "down")
            await pilot.pause()
            if confirm:
                await pilot.press("r")
                await pilot.pause()
            to_png(name, fix_svg(app.export_screenshot(title="keelyard rewind list -i")))

    asyncio.run(shoot("timeline", False))
    asyncio.run(shoot("timeline-confirm", True))


if __name__ == "__main__":
    main()
