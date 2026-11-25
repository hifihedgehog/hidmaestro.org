# -*- coding: utf-8 -*-
"""Write the product page's adoption list from _adopters.json.

The projects marked home go into index.html between <!-- ADOPT:BEGIN -->
and <!-- ADOPT:END -->, in the file's order, each row a card with no
colored bar (padforge.org/DESIGN.md). A last row links the rest, which
tools/build_specs.py lists in full on specs.html. Edit the data, then run
both. Hand edits inside the markers get overwritten.
"""
import html, io, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = json.load(io.open(os.path.join(ROOT, "_adopters.json"), encoding="utf-8-sig"))

home = [p for p in DATA["projects"] if p.get("home")]
rest = [p for p in DATA["projects"] if not p.get("home")]
rows = ['                <div class="mf"><b><a href="%s" target="_blank" rel="noopener">%s</a></b><span>%s</span></div>'
        % (html.escape(p["url"]), html.escape(p["name"], quote=False), html.escape(p["d"], quote=False))
        for p in home]
if rest:
    rows.append('                <div class="mf"><b><a href="specs.html#adopters">%d more projects</a></b><span>%s</span></div>'
                % (len(rest), html.escape(DATA["rest"], quote=False)))
block = ("<!-- ADOPT:BEGIN, written by tools/build_adopters.py from _adopters.json -->\n"
         + "\n".join(rows) + "\n                <!-- ADOPT:END -->")

path = os.path.join(ROOT, "index.html")
s = io.open(path, encoding="utf-8").read()
a = s.index("<!-- ADOPT:BEGIN")
b = s.index("<!-- ADOPT:END -->") + len("<!-- ADOPT:END -->")
io.open(path, "w", encoding="utf-8", newline="\n").write(s[:a] + block + s[b:])
print("index.html adoption list: %d projects and a link to %d more" % (len(home), len(rest)))
