"""Shared look for every HTML surface: Geist + Geist Mono (OFL, embedded), a paper palette,
one green for "proven", one red for "not". Reports are single files with no network requests."""

from __future__ import annotations

import base64
from functools import cache
from importlib import resources

PAPER, INK, MUTED, LINE, GREEN, RED, AMBER = "#FAFAF9", "#111111", "#6B6B66", "#E7E5E4", "#1F6F4A", "#B42318", "#A15C07"


@cache
def font_css() -> str:
    out = []
    for family, file in (("Geist", "geist.woff2"), ("Geist Mono", "geist-mono.woff2")):
        data = base64.b64encode(resources.files("keelyard.assets").joinpath(file).read_bytes()).decode()
        out.append(f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{data}) format('woff2');"
                   "font-weight:100 900;font-display:block}")
    return "".join(out)


BASE_CSS = """
:root{--paper:#FAFAF9;--card:#FFFFFF;--ink:#111111;--ink2:#3F3F3B;--muted:#6B6B66;--line:#E7E5E4;--soft:#F3F2EF;
--green:#1F6F4A;--green-bg:#E8F2EC;--red:#B42318;--red-bg:#FBEAE8;--amber:#A15C07;--amber-bg:#FBF1E2}
@media (prefers-color-scheme:dark){:root{--paper:#0F0F0E;--card:#161615;--ink:#EDEDEA;--ink2:#C9C9C4;--muted:#8F8F89;
--line:#2A2A28;--soft:#1C1C1A;--green:#5CB88A;--green-bg:#15261D;--red:#F0776B;--red-bg:#2C1714;--amber:#E0A44E;--amber-bg:#2A2012}}
*{box-sizing:border-box}
html{background:var(--paper);color:var(--ink);-webkit-font-smoothing:antialiased}
body{margin:0;font:15px/1.55 'Geist',ui-sans-serif,system-ui,sans-serif;font-feature-settings:'tnum'}
main{max-width:860px;margin:0 auto;padding:56px 32px 80px}
code,pre,.mono{font-family:'Geist Mono',ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
a{color:inherit}
.brand{display:flex;align-items:center;gap:8px;font:500 13px 'Geist Mono',monospace;color:var(--muted);letter-spacing:-.01em}
.brand i{width:9px;height:9px;border-radius:2px;background:var(--ink);display:inline-block}
h1{font-size:30px;line-height:1.15;letter-spacing:-.025em;font-weight:600;margin:20px 0 8px}
h2{font-size:13px;font-weight:500;color:var(--muted);margin:44px 0 12px;letter-spacing:0}
.sub{color:var(--muted);font-size:14px;margin:0}
.pill{display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;border-radius:999px;font-size:12.5px;font-weight:500}
.pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.pill.ok{color:var(--green);background:var(--green-bg)}.pill.bad{color:var(--red);background:var(--red-bg)}
.pill.warn{color:var(--amber);background:var(--amber-bg)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:10px;background:var(--card);margin-top:32px}
.stat{padding:16px 18px;border-left:1px solid var(--line)}.stat:first-child{border-left:0}
.stat b{display:block;font-size:22px;font-weight:600;letter-spacing:-.02em}.stat span{font-size:12.5px;color:var(--muted)}
.box{border:1px solid var(--line);border-radius:10px;background:var(--card);overflow:hidden}
.row{display:grid;grid-template-columns:22px 1fr auto;gap:12px;padding:14px 18px;border-top:1px solid var(--line);align-items:start}
.row:first-child{border-top:0}
.mark{width:16px;height:16px;border-radius:50%;margin-top:3px;border:1.5px solid var(--line);display:grid;place-items:center}
.mark.ok{background:var(--green);border-color:var(--green)}
.mark.ok::after{content:"";width:6px;height:3px;border:solid #fff;border-width:0 0 1.6px 1.6px;transform:rotate(-45deg) translate(1px,-1px)}
.mark.bad{border-color:var(--red)}
.row .t{font-weight:500}.row .e{color:var(--muted);font-size:13px;margin-top:2px}
.row .r{color:var(--muted);font-size:12.5px;white-space:nowrap}
.quote{border-left:2px solid var(--ink);padding:2px 0 2px 16px;color:var(--ink2);white-space:pre-wrap}
.gap{display:flex;gap:10px;padding:12px 18px;border-top:1px solid var(--line);font-size:14px}.gap:first-child{border-top:0}
.gap::before{content:"";flex:none;width:6px;height:6px;border-radius:50%;background:var(--amber);margin-top:8px}
details{border-top:1px solid var(--line)}details:first-child{border-top:0}
summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding:13px 18px}
summary::-webkit-details-marker{display:none}
summary code{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
pre{margin:0;padding:14px 18px;background:var(--soft);border-top:1px solid var(--line);color:var(--ink2);overflow:auto;max-height:320px;line-height:1.6}
.tl{list-style:none;margin:0;padding:0}
.tl li{display:grid;grid-template-columns:52px 70px 120px 1fr;gap:12px;padding:9px 18px;border-top:1px solid var(--line);font-size:13.5px}
.tl li:first-child{border-top:0}.tl .n{font-family:'Geist Mono',monospace;color:var(--muted)}
.tl .q{color:var(--muted)}
.tl .f{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:'Geist Mono',monospace;font-size:12.5px}
footer{margin-top:56px;white-space:normal;padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;display:flex;justify-content:space-between;gap:24px}footer .mono{white-space:nowrap}
img.shot{width:100%;display:block}
table{width:100%;border-collapse:collapse;font-size:14px}
th{font-weight:500;color:var(--muted);font-size:12.5px;text-align:left;padding:10px 14px;border-bottom:1px solid var(--line)}
td{padding:12px 14px;border-bottom:1px solid var(--line)}tr:last-child td{border-bottom:0}
td.n{text-align:right;font-family:'Geist Mono',monospace;font-size:13px}th.n{text-align:right}
@media (max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}.stat:nth-child(3){border-left:0}
.stat:nth-child(n+3){border-top:1px solid var(--line)}.tl li{grid-template-columns:44px 1fr}.tl .q,.tl .tm{display:none}}
"""


def page(title: str, body: str) -> str:
    import html

    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{font_css()}{BASE_CSS}</style><main>{body}</main></html>")
