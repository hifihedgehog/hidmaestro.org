# -*- coding: utf-8 -*-
"""Generate hidmaestro.org/specs.html.

The padforge.org split, applied here: the product page sells, the
specifications page proves. Every capability lives in _features.json and
is emitted here by construction, so the landing page can stay bold and
simple without a single capability going missing. Edit the data or this
generator, then re-run. Hand edits to specs.html get overwritten.
"""
import io, json, html, os
from html import unescape

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
feats = json.load(io.open(os.path.join(ROOT, "_features.json"), encoding="utf-8"))

pool = {f["t"]: f["d"] for f in feats}

CATS = [
 ("identity", "Identity and fidelity", [
   "Exact hardware identity", "Valve personas Steam recognizes",
   "A Switch Pro that answers back", "Controller audio and haptics",
   "Capture a controller you own"]),
 ("catalog", "The catalog", [
   "234 device profiles", "Devices are JSON"]),
 ("latency", "Latency and transport", [
   "~35 µs measured input latency", "Event-driven output at 0.15 ms",
   "No socket, no batching cap", "The comparison, honestly",
   "Networking at the right layer", "Fast to start, fast to recover"]),
 ("apis", "APIs and consumers", [
   "Every gaming API at once", "Multi-controller", "Hot-plug",
   "Force feedback answered"]),
 ("vr", "VR", [
   "Virtual VR controllers"]),
 ("sdk", "The SDK", [
   "One DLL", "Self-bootstrapping install", "A UI instead of code"]),
 ("validation", "Validation", [
   "Validated across the stack", "Judged by the real consumers"]),
 ("platform", "Platform and licensing", [
   "No kernel driver, no test-signing", "The composite exception, stated",
   "Windows 10 and 11", "MIT licensed"]),
]

used = set()
sections = []
for cid, title, keys in CATS:
    items = []
    for k in keys:
        assert k in pool, "unknown feature key: " + k
        used.add(k)
        items.append((k, pool[k]))
    sections.append((cid, title, items))

leftovers = [(t, d) for t, d in pool.items() if t not in used]
if leftovers:
    sections.append(("more", "Also included", leftovers))


def esc(x):
    return html.escape(unescape(x), quote=False)


rows = []
for cid, title, items in sections:
    body = "\n".join(
        '                <div class="spec-row">\n'
        '                    <dt>%s</dt>\n'
        '                    <dd>%s</dd>\n'
        '                </div>' % (esc(t), esc(d)) for t, d in items)
    rows.append(
'''        <section class="spec-block" id="%s">
            <h2 class="display-s spec-h reveal">%s</h2>
            <dl class="spec-list reveal" data-d="1">
%s
            </dl>
        </section>''' % (cid, esc(title), body))

CMP = io.open(os.path.join(ROOT, "_cmp_full.html"), encoding="utf-8").read().strip()
rows.append(
'        <section class="spec-block" id="comparison">\n'
'            <h2 class="display-s spec-h reveal">Full comparison</h2>\n'
'            <p class="spec-note reveal">Every capability, against the tools people '
'usually reach for. The product page carries a shortened version of this table.</p>\n'
'            <div class="cmp-wrap reveal" data-d="1">\n'
'                <div class="cmp-scroll">\n'
'                    ' + CMP + '\n'
'                </div>\n'
'            </div>\n'
'        </section>')

faq = json.load(io.open(os.path.join(ROOT, "_faq.json"), encoding="utf-8"))
faq_rows = "\n".join(
    '                <details class="detail">\n'
    '                    <summary>%s</summary>\n'
    '                    <div class="detail-body">%s</div>\n'
    '                </details>' % (esc(f["q"]), esc(f["a"])) for f in faq)
rows.append(
'        <section class="spec-block" id="faq">\n'
'            <h2 class="display-s spec-h reveal">Questions, answered plainly</h2>\n'
'            <div class="details reveal" data-d="1">\n'
+ faq_rows + '\n'
'            </div>\n'
'        </section>')

nav_links = "\n".join(
    '                <a href="#%s">%s</a>' % (cid, esc(title)) for cid, title, _ in sections)
nav_links += '\n                <a href="#comparison">Full comparison</a>'
nav_links += '\n                <a href="#faq">Questions</a>'

page = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HIDMaestro specifications: every capability, in full</title>
    <meta name="description" content="The complete HIDMaestro capability list: identity, the profile catalog, latency, APIs, VR, the SDK surface, validation, and platform details.">
    <link rel="icon" type="image/png" href="assets/icon.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800;900&family=Instrument+Sans:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="style.css?v=9">
    <script>document.documentElement.classList.add('js');</script>
</head>
<body>

<nav class="nav" id="nav">
    <div class="container-wide nav-in">
        <a class="nav-brand" href="index.html"><img src="assets/logo-light.png" alt="" width="27" height="27">HIDMaestro</a>
        <div class="nav-links">
            <a href="index.html#identity">Identity</a>
            <a href="index.html#latency">Latency</a>
            <a href="index.html#compare">Compare</a>
            <a href="specs.html">Specifications</a>
            <a href="/docs/">Docs</a>
        </div>
        <a href="https://github.com/hifihedgehog/HIDMaestro/releases/latest" class="btn btn-primary btn-sm" target="_blank" rel="noopener">Download</a>
    </div>
</nav>

<header class="spec-hero">
    <div class="container">
        <p class="kicker reveal">Specifications</p>
        <h1 class="display-l reveal" data-d="1">Everything, in full.</h1>
        <p class="lede reveal" data-d="2">
            The complete capability list. The <a href="index.html">product page</a> shows
            what HIDMaestro is; this page proves what it does. Each entry is covered at
            length in the <a href="/docs/">documentation</a>.
        </p>
    </div>
</header>

<div class="container spec-wrap">
    <aside class="spec-nav">
        <div class="spec-nav-in">
            <p class="mono-tag">Contents</p>
%s
        </div>
    </aside>
    <main class="spec-main">
%s
    </main>
</div>

<footer class="footer">
    <div class="container">
        <div class="footer-grid">
            <a class="footer-brand" href="index.html"><img src="assets/logo-light.png" alt="" width="26" height="26">HIDMaestro</a>
            <div class="footer-links">
                <a href="index.html">Overview</a>
                <a href="specs.html">Specifications</a>
                <a href="/docs/">Docs</a>
                <a href="https://github.com/hifihedgehog/HIDMaestro" target="_blank" rel="noopener">GitHub</a>
            </div>
        </div>
        <div class="footer-note">
            <span>Licensed under <a href="https://opensource.org/licenses/MIT" target="_blank" rel="noopener" style="color:var(--text-muted)">MIT License</a></span>
            <span>The engine inside PadForge</span>
        </div>
    </div>
</footer>

<script>
(function () {
    "use strict";
    var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -8%% 0px", threshold: 0.04 });
    document.querySelectorAll(".reveal").forEach(function (el) { io.observe(el); });

    var nav = document.getElementById("nav");
    addEventListener("scroll", function () { nav.classList.toggle("stuck", scrollY > 40); }, { passive: true });

    /* Mark the section currently in view in the contents rail. */
    var links = [].slice.call(document.querySelectorAll(".spec-nav a"));
    var blocks = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
    blocks.forEach(function (b) {
        new IntersectionObserver(function (es) {
            es.forEach(function (e) {
                if (!e.isIntersecting) return;
                var i = blocks.indexOf(e.target);
                links.forEach(function (l, n) { l.classList.toggle("on", n === i); });
            });
        }, { rootMargin: "-20%% 0px -70%% 0px" }).observe(b);
    });
})();
</script>
</body>
</html>
''' % (nav_links, "\n\n".join(rows))

io.open(os.path.join(ROOT, "specs.html"), "w", encoding="utf-8", newline="\n").write(page)
total = sum(len(i) for _, _, i in sections)
print("specs.html written: %d entries across %d sections" % (total, len(sections)))
for cid, title, items in sections:
    print("  %-26s %d" % (title, len(items)))
