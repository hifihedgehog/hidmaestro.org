# -*- coding: utf-8 -*-
"""Write the product page's adoption list from _adopters.json.

The projects marked home go into index.html between <!-- ADOPT:BEGIN -->
and <!-- ADOPT:END -->, in the file's order, with the accent bars cycling
as the list always has. A last row links the rest, which
tools/build_specs.py lists in full on specs.html. Edit the data, then run
both. Hand edits inside the markers get overwritten.
"""
import html, io, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = json.load(io.open(os.path.join(ROOT, "_adopters.json"), encoding="utf-8-sig"))
BARS = ["ember", "brand-ps", "brand-xbox", "telemetry", "brand-steam", "brand-nin"]

home = [p for p in DATA["projects"] if p.get("home")]
rest = [p for p in DATA["projects"] if not p.get("home")]
rows = ['                <div class="mf" style="--mf: var(--%s)"><b><a href="%s" target="_blank" rel="noopener">%s</a></b><span>%s</span></div>'
        % (BARS[i % len(BARS)], html.escape(p["url"]), html.escape(p["name"], quote=False), html.escape(p["d"], quote=False))
        for i, p in enumerate(home)]
if rest:
    rows.append('                <div class="mf" style="--mf: var(--text-dim)"><b><a href="specs.html#adopters">%d more projects</a></b><span>%s</span></div>'
                % (len(rest), html.escape(DATA["rest"], quote=False)))
block = ("<!-- ADOPT:BEGIN, written by tools/build_adopters.py from _adopters.json -->\n"
         + "\n".join(rows) + "\n                <!-- ADOPT:END -->")

path = os.path.join(ROOT, "index.html")
s = io.open(path, encoding="utf-8").read()
a = s.index("<!-- ADOPT:BEGIN")
b = s.index("<!-- ADOPT:END -->") + len("<!-- ADOPT:END -->")
io.open(path, "w", encoding="utf-8", newline="\n").write(s[:a] + block + s[b:])
print("index.html adoption list: %d projects and a link to %d more" % (len(home), len(rest)))
