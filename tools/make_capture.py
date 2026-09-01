# -*- coding: utf-8 -*-
"""Write _capture.html: a copy of index.html for full-page screenshots.

A 100svh hero fills a tall capture window and photographs as an empty
page, so the harness neutralises the viewport-height rule and forces the
reveal state. Never ship _capture.html; it exists only to be looked at.
"""
import io, os.path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INJECT = """<style id="cap">
.hero{min-height:auto !important; padding-top:11rem !important; padding-bottom:5rem !important;}
.js .reveal{opacity:1 !important; transform:none !important;}
/* Freeze every transition and animation. Headless virtual time can
   photograph a transition mid-flight, which prints as ghosted text and
   reads like a layout bug that is not in the page. */
*,*::before,*::after{transition:none !important; animation:none !important; will-change:auto !important;}
</style></head>"""

src = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
out = src.replace("</head>", INJECT, 1)
io.open(os.path.join(ROOT, "_capture.html"), "w", encoding="utf-8", newline="\n").write(out)
print("_capture.html written")
