# -*- coding: utf-8 -*-
"""Generate hidmaestro.org's performance charts from _perf.json.

Each release's notes compare it with the release before it, both builds
measured in one session on the development laptop. _perf.json keeps
those published values, one step per release. A chart multiplies a
path's steps from 1.12.0 on, so each ratio comes from one session and
values from different sessions never meet in one ratio.

Writes performance.html, press/performance.svg, and the blocks between
<!-- PERF:BEGIN --> and <!-- PERF:END --> in index.html and
press/index.html. Edit the data or this generator, then re-run. Hand
edits inside the markers get overwritten.
"""
import html, io, json, math, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = json.load(io.open(os.path.join(ROOT, "_perf.json"), encoding="utf-8-sig"))
REL = DATA["releases"]
STEPS = DATA["steps"]
METRICS = DATA["metrics"]
for i, s in enumerate(STEPS):
    assert (s["from"], s["to"]) == (REL[i], REL[i + 1]), s
for m in METRICS:
    assert len(m["steps"]) == len(STEPS), m["id"]
    assert m["better"] in ("lower", "higher"), m["id"]

HOME = ["start-ds4", "read-ds4", "submit-x360"]
PRESS = ["start-ds4", "create-x360", "dispose-ds-usbip", "read-ds4", "xinput-x360", "submit-x360"]
LAST = len(REL) - 1
W = 300           # SVG user units across the plot. The SVG stretches to the plot box.


def esc(s):
    return html.escape(s, quote=True)


def label_html(label):
    """`code` spans to <code>, the rest escaped."""
    return "".join(("<code>%s</code>" if i % 2 else "%s") % esc(p) for i, p in enumerate(label.split("`")))


def plain(label):
    return label.replace("`", "")


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fmt(x):
    return ("%.2f" % x).rstrip("0").rstrip(".")


def num(v, unit):
    return "{:,.0f}".format(v) if unit == "frames a second" else "{:,.1f}".format(v)


def pct(v):
    """A chart value as text: whole percent, one decimal under 10."""
    return ("%.0f%%" if round(v) >= 10 else "%.1f%%") % v


def chain(m):
    """Time relative to 1.12.0 at each release. A rate becomes time per
    frame, its inverse, so lower is faster on every chart."""
    idx = [100.0]
    for s in m["steps"]:
        b, a = s["before"][0], s["after"][0]
        idx.append(idx[-1] * (a / b if m["better"] == "lower" else b / a))
    return idx


def change(s):
    return (s["after"][0] / s["before"][0] - 1) * 100


# One y-axis for every chart: 0 to just above the largest value, never
# under 110, with 100 marking 1.12.0.
TOP = max(110, 10 * math.ceil(max(max(chain(m)) for m in METRICS) * 1.05 / 10))
TICKS = list(range(0, TOP + 1, 50))


def points(m, idx):
    out = [{"r": REL[0], "v": "100%, the baseline", "s": ""}]
    for i, s in enumerate(m["steps"]):
        out.append({"r": REL[i + 1], "v": "%s of %s's time" % (pct(idx[i + 1]), REL[0]),
                    "s": "From %s: %s to %s %s (%+.1f%%)" % (REL[i], num(s["before"][0], m["unit"]),
                                                          num(s["after"][0], m["unit"]), m["unit"], change(s))})
    return out


def plot(m, idx):
    top = lambda v: fmt((TOP - v) / TOP * 100)
    left = lambda i: fmt(i * 100 / LAST)
    lines = "".join('<line%s x1="0" y1="%s" x2="%d" y2="%s" vector-effect="non-scaling-stroke"/>'
                    % (' class="base"' if t == 100 else "", fmt(TOP - t), W, fmt(TOP - t)) for t in TICKS)
    poly = " ".join("%s,%s" % (fmt(i * W / LAST), fmt(TOP - v)) for i, v in enumerate(idx))
    svg = ('<svg viewBox="0 0 %d %d" preserveAspectRatio="none" aria-hidden="true" focusable="false">%s'
           '<polyline points="%s" vector-effect="non-scaling-stroke"/></svg>' % (W, TOP, lines, poly))
    ticks = "".join('<span class="perf-tick%s" style="top:%s%%">%d%%</span>'
                    % (" base" if t == 100 else "", top(t), t) for t in TICKS)
    rels = "".join('<span class="perf-rel" style="left:%s%%">%s</span>' % (left(i), esc(r)) for i, r in enumerate(REL))
    pts = "".join('<span class="perf-pt" style="left:%s%%;top:%s%%"></span>' % (left(i), top(v)) for i, v in enumerate(idx))
    aria = "%s, time relative to %s: %s." % (plain(m["label"]), REL[0], ", ".join(
        "%s at %s" % (r, pct(v)) for r, v in zip(REL, idx)))
    data = json.dumps(points(m, idx), separators=(",", ":"), ensure_ascii=False)
    return ('<div class="perf-plot" role="img" tabindex="0" aria-label="%s" data-points="%s">%s%s%s%s</div>'
            % (esc(aria), esc(data), svg, ticks, rels, pts))


def card(m):
    idx = chain(m)
    unit = m["unit"]

    def cell(v):
        return num(v[0], unit) + ("" if v[1] is None else "<span>%s</span>" % num(v[1], unit))
    rows = "".join(
        '<tr><td><a href="%s">%s to %s</a></td><td>%s</td><td>%s</td><td>%+.1f%%</td></tr>'
        % (esc(st["notes"]), esc(st["from"]), esc(st["to"]), cell(s["before"]), cell(s["after"]), change(s))
        for st, s in zip(STEPS, m["steps"]))
    p95 = any(v[1] is not None for s in m["steps"] for v in (s["before"], s["after"]))
    note = "Medians, with the 95th percentile under each." if p95 else "Medians."
    if m["better"] == "higher":
        note += " The chart plots time per frame, the inverse of this rate, so lower is faster there too."
    return '''<article class="perf-card" id="m-%s">
    <h3 class="perf-title">%s</h3>
    <p class="perf-now"><b>%s</b> of %s's time</p>
    %s
    <details class="perf-values">
        <summary>Measured values, in %s</summary>
        <table><thead><tr><th>Step</th><th>Before</th><th>After</th><th>Change</th></tr></thead><tbody>%s</tbody></table>
        <p>%s</p>
    </details>
</article>''' % (m["id"], label_html(m["label"]), pct(idx[-1]), REL[0], plot(m, idx), esc(unit), rows, note)


def by_id(i):
    for m in METRICS:
        if m["id"] == i:
            return m
    raise KeyError(i)


def groups():
    seen = []
    for m in METRICS:
        if m["group"] not in seen:
            seen.append(m["group"])
    return seen


def method_html():
    ratio = ", times ".join("%s's ratio to %s" % (s["to"], s["from"]) for s in STEPS)
    return ('''            <p class="perf-method reveal" data-d="1">Each release's notes compare it with the release before it on the
                development laptop, a Lenovo Legion Pro 7 16AFR10H, with diagnostic logging off and both builds
                measured in the same session. A chart multiplies those comparisons from %s on, so the %s point is
                %s. Each ratio compares medians.</p>
            <ul class="perf-steps reveal" data-d="1">
%s
            </ul>
            <p class="perf-method reveal" data-d="1">Values from different sessions never meet in one ratio. Between two
                sessions, the same release has measured up to 31 percent apart on a per-call <code>SubmitState</code>
                row and 86 percent apart on a few-millisecond USB/IP row. Within one session, rows measured in two
                passes have moved several percent from one pass to the next, so a step of a few percent is within
                that spread.</p>''' % (REL[0], REL[-1], ratio, "\n".join(
        '                <li><a href="%s">%s to %s</a>: %s.</li>' % (esc(s["notes"]), esc(s["from"]), esc(s["to"]), esc(s["method"]))
        for s in STEPS)))


def page():
    blocks, nav = [], ['                <a href="#method">How it is measured</a>']
    for g in groups():
        nav.append('                <a href="#%s">%s</a>' % (slug(g), esc(g)))
        blocks.append('''        <section class="spec-block" id="%s">
            <h2 class="display-s spec-h reveal">%s</h2>
            <div class="perf-grid reveal" data-d="1">
%s
            </div>
        </section>''' % (slug(g), esc(g), "\n".join(card(m) for m in METRICS if m["group"] == g)))
    return TEMPLATE % {"nav": "\n".join(nav), "method": method_html(), "groups": "\n\n".join(blocks),
                       "n": len(METRICS), "first": esc(REL[0]), "last": esc(REL[-1])}


TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HIDMaestro performance, release over release</title>
    <meta name="description" content="The %(n)d paths every HIDMaestro release since %(first)s has measured against the one before, charted to %(last)s: start, create, removal, input to the game, output and the cost of a submit.">
    <link rel="icon" type="image/png" href="assets/icon.png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800;900&family=Instrument+Sans:ital,wght@0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="style.css?v=12">
    <link rel="stylesheet" href="perf.css?v=1">
    <script>document.documentElement.classList.add('js');</script>
    <script src="perf.js?v=1" defer></script>
</head>
<body>

<nav class="nav" id="nav">
    <div class="container-wide nav-in">
        <a class="nav-brand" href="index.html"><img src="assets/logo-light.png" alt="" width="27" height="27">HIDMaestro</a>
        <div class="nav-links">
            <a href="index.html#identity">Identity</a>
            <a href="index.html#latency">Latency</a>
            <a href="index.html#compare">Compare</a>
            <a href="performance.html">Performance</a>
            <a href="specs.html">Specifications</a>
            <a href="/docs/">Docs</a>
        </div>
        <a href="https://github.com/hifihedgehog/HIDMaestro/releases/latest" class="btn btn-primary btn-sm" target="_blank" rel="noopener">Download</a>
    </div>
</nav>

<header class="spec-hero">
    <div class="container">
        <p class="kicker kicker-cy reveal">Performance</p>
        <h1 class="display-l reveal" data-d="1">Measured, release over release.</h1>
        <p class="lede reveal" data-d="2">
            These charts follow the %(n)d paths that every release's comparison has measured
            since %(first)s, as time relative to %(first)s. Lower is faster. Point at a chart,
            or tab to it, to read each release's value. The table under each chart lists every
            measured value.
        </p>
    </div>
</header>

<div class="container spec-wrap">
    <aside class="spec-nav">
        <div class="spec-nav-in">
            <p class="mono-tag">Contents</p>
%(nav)s
        </div>
    </aside>
    <main class="spec-main">
        <section class="spec-block" id="method">
            <h2 class="display-s spec-h reveal">How it is measured</h2>
%(method)s
        </section>

%(groups)s
    </main>
</div>

<footer class="footer">
    <div class="container">
        <div class="footer-grid">
            <a class="footer-brand" href="index.html"><img src="assets/logo-light.png" alt="" width="26" height="26">HIDMaestro</a>
            <div class="footer-links"><a href="/">Home</a><a href="/press/">Press</a><a href="/performance.html">Performance</a><a href="/specs.html">Specifications</a><a href="/docs/">Documentation</a><a href="https://github.com/hifihedgehog/HIDMaestro" target="_blank" rel="noopener">GitHub</a></div>
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
'''


def home_block():
    return '''<!-- PERF:BEGIN, written by tools/build_perf.py from _perf.json -->
<section class="section section-alt" id="performance">
    <div class="container">
        <div class="perf-head">
            <p class="kicker kicker-cy reveal">Performance</p>
            <h2 class="display-m reveal" data-d="1">Measured, release over release.</h2>
            <p class="lede reveal" data-d="2">
                Time relative to %s. Lower is faster. Each step is the side-by-side comparison
                published with that release. <a href="performance.html">All %d paths, slower steps included</a>.
            </p>
        </div>
        <div class="perf-grid perf-grid-3 reveal" data-d="2">
%s
        </div>
    </div>
</section>
<!-- PERF:END -->''' % (esc(REL[0]), len(METRICS), "\n".join(card(by_id(i)) for i in HOME))


def press_block():
    return '''<!-- PERF:BEGIN, written by tools/build_perf.py from _perf.json -->
<section class="perf-section press-width" id="performance" aria-labelledby="performance-title">
    <div class="section-heading"><div><p class="eyebrow">Performance</p><h2 id="performance-title">Release over release</h2></div><a class="text-link" href="/performance.html">All %d paths <span aria-hidden="true">&#8599;</span></a></div>
    <p class="perf-intro">Time relative to %s. Lower is faster. Each step is the side-by-side comparison published with that release, both builds measured in one session on the development laptop.</p>
    <div class="perf-grid">
%s
    </div>
    <p class="perf-download"><a class="text-link" href="performance.svg" download="HIDMaestro-performance.svg">Download these charts, 1600 &times; 960 SVG <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 4v13m-5-5 5 5 5-5M5 20h14"/></svg></a></p>
</section>
<!-- PERF:END -->''' % (len(METRICS), esc(REL[0]), "\n".join(card(by_id(i)) for i in PRESS))


def wrap(text, width):
    lines, line = [], ""
    for w in text.split():
        if line and len(line) + 1 + len(w) > width:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    lines.append(line)
    return lines


def press_svg():
    """The press kit's sheet: the press charts at 1600 x 960, in the
    architecture artwork's frame, fonts and colors."""
    sw, sh = 1600, 960
    x0, y0, gap = 90, 250, 30
    cw = (sw - 2 * x0 - 2 * gap) / 3.0
    ch = (900 - y0 - gap) / 2.0
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-labelledby="title description">' % (sw, sh, sw, sh),
         '<title id="title">HIDMaestro performance, release over release</title>',
         '<desc id="description">%s</desc>' % esc(" ".join(
             "%s: %s of %s's time at %s." % (plain(by_id(i)["label"]), pct(chain(by_id(i))[-1]), REL[0], REL[-1]) for i in PRESS)),
         '<rect width="%d" height="%d" rx="12" fill="#0d1117"/>' % (sw, sh),
         '<g font-family="Arial, Helvetica, sans-serif">',
         '<text x="90" y="95" fill="#6fc3d6" font-size="15" letter-spacing="4">HIDMAESTRO</text>',
         '<text x="90" y="162" fill="#f7f9fc" font-size="46" font-weight="600" letter-spacing="-1.5">Performance, release over release</text>',
         '<text x="90" y="206" fill="#929fb0" font-size="21">Time relative to %s. Lower is faster. Each step is the side-by-side comparison published with that release.</text>' % esc(REL[0])]
    for k, i in enumerate(PRESS):
        m = by_id(i)
        idx = chain(m)
        cx = x0 + (k % 3) * (cw + gap)
        cy = y0 + (k // 3) * (ch + gap)
        o.append('<rect x="%s" y="%s" width="%s" height="%s" rx="12" fill="#12171f" stroke="#212a36"/>' % (fmt(cx), fmt(cy), fmt(cw), fmt(ch)))
        for n, line in enumerate(wrap(plain(m["label"]), 40)[:2]):
            o.append('<text x="%s" y="%s" fill="#f7f9fc" font-size="19" font-weight="600">%s</text>' % (fmt(cx + 26), fmt(cy + 40 + n * 24), esc(line)))
        o.append('<text x="%s" y="%s" fill="#f7f9fc" font-size="34" font-weight="700" letter-spacing="-0.5">%s<tspan fill="#929fb0" font-size="16" font-weight="400" letter-spacing="0"> of %s\'s time</tspan></text>'
                 % (fmt(cx + 26), fmt(cy + 114), pct(idx[-1]), esc(REL[0])))
        px0, px1, py0, py1 = cx + 78, cx + cw - 40, cy + 138, cy + ch - 50
        X = lambda j: px0 + (px1 - px0) * j / LAST
        Y = lambda v: py0 + (py1 - py0) * (TOP - v) / TOP
        for t in TICKS:
            o.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="1"/>'
                     % (fmt(px0), fmt(Y(t)), fmt(px1), fmt(Y(t)), "#3b434e" if t == 100 else "#23272f"))
            o.append('<text x="%s" y="%s" fill="%s" font-family="Consolas, monospace" font-size="13" text-anchor="end">%d%%</text>'
                     % (fmt(px0 - 12), fmt(Y(t) + 4.5), "#929fb0" if t == 100 else "#5d6877", t))
        for j, r in enumerate(REL):
            o.append('<text x="%s" y="%s" fill="#929fb0" font-family="Consolas, monospace" font-size="13" text-anchor="middle">%s</text>'
                     % (fmt(X(j)), fmt(py1 + 28), esc(r)))
        o.append('<polyline points="%s" fill="none" stroke="#d9531c" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
                 % " ".join("%s,%s" % (fmt(X(j)), fmt(Y(v))) for j, v in enumerate(idx)))
        for j, v in enumerate(idx):
            o.append('<circle cx="%s" cy="%s" r="5.5" fill="#d9531c" stroke="#12171f" stroke-width="2.5"/>' % (fmt(X(j)), fmt(Y(v))))
    o.append('<text x="90" y="935" fill="#5d6877" font-family="Consolas, monospace" font-size="15">Method and every measured value: hidmaestro.org/performance.html</text>')
    o.append('</g>')
    o.append('</svg>')
    return "\n".join(o) + "\n"


def splice(path, block):
    s = io.open(path, encoding="utf-8").read()
    a = s.index("<!-- PERF:BEGIN")
    b = s.index("<!-- PERF:END -->") + len("<!-- PERF:END -->")
    io.open(path, "w", encoding="utf-8", newline="\n").write(s[:a] + block + s[b:])


io.open(os.path.join(ROOT, "performance.html"), "w", encoding="utf-8", newline="\n").write(page())
io.open(os.path.join(ROOT, "press", "performance.svg"), "w", encoding="utf-8", newline="\n").write(press_svg())
splice(os.path.join(ROOT, "index.html"), home_block())
splice(os.path.join(ROOT, "press", "index.html"), press_block())
print("performance.html, press/performance.svg, and the index.html and press/index.html sections: %d paths, %s, axis 0 to %d%%"
      % (len(METRICS), ", ".join(REL), TOP))
for m in METRICS:
    print("  %-18s %s" % (m["id"], " ".join("%6s" % pct(v) for v in chain(m))))
