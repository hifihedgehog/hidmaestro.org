/* Hover, touch and keyboard readout for the performance charts.

   Each .perf-plot carries its points as JSON in data-points: the
   release, the value as text, and the step that produced it. The charts
   and their tables render without this script. It adds a crosshair and
   a tooltip that follow the nearest release, and arrow keys move it
   while a chart has focus. Text goes in with textContent only. */
(function () {
    "use strict";
    var plots = [].slice.call(document.querySelectorAll(".perf-plot[data-points]"));
    var active = null;

    plots.forEach(function (plot) {
        var pts;
        try { pts = JSON.parse(plot.getAttribute("data-points")); } catch (e) { return; }
        if (!pts || pts.length < 2) return;
        var marks = [].slice.call(plot.querySelectorAll(".perf-pt"));
        var hair = document.createElement("div");
        var tip = document.createElement("div");
        var rel = document.createElement("span");
        var val = document.createElement("span");
        var step = document.createElement("span");
        hair.className = "perf-xhair";
        tip.className = "perf-tip";
        rel.className = "perf-tip-r";
        val.className = "perf-tip-v";
        hair.hidden = tip.hidden = true;
        tip.appendChild(rel);
        tip.appendChild(val);
        tip.appendChild(step);
        plot.appendChild(hair);
        plot.appendChild(tip);
        var cur = -1;
        var last = pts.length - 1;

        function show(i) {
            if (active && active !== plot) active.perfHide();
            active = plot;
            cur = i;
            var p = pts[i];
            rel.textContent = p.r;
            val.textContent = p.v;
            step.textContent = p.s;
            step.hidden = !p.s;
            marks.forEach(function (m, n) { m.classList.toggle("on", n === i); });
            var w = plot.clientWidth, h = plot.clientHeight;
            var x = w * i / last;
            hair.style.left = x + "px";
            hair.hidden = tip.hidden = false;
            var tw = tip.offsetWidth, th = tip.offsetHeight;
            var y = (parseFloat(marks[i] && marks[i].style.top) || 0) / 100 * h;
            tip.style.left = Math.max(-28, Math.min(w - tw + 12, x - tw / 2)) + "px";
            tip.style.top = (y > h / 2 ? y - th - 14 : y + 14) + "px";
        }
        function hide() {
            cur = -1;
            hair.hidden = tip.hidden = true;
            marks.forEach(function (m) { m.classList.remove("on"); });
            if (active === plot) active = null;
        }
        plot.perfHide = hide;

        function nearest(clientX) {
            var b = plot.getBoundingClientRect();
            var f = b.width ? (clientX - b.left) / b.width : 1;
            return Math.max(0, Math.min(last, Math.round(f * last)));
        }
        plot.addEventListener("pointermove", function (e) { show(nearest(e.clientX)); });
        plot.addEventListener("pointerdown", function (e) { show(nearest(e.clientX)); });
        plot.addEventListener("pointerleave", function (e) { if (e.pointerType !== "touch") hide(); });
        plot.addEventListener("focus", function () { show(cur < 0 ? last : cur); });
        plot.addEventListener("blur", hide);
        plot.addEventListener("keydown", function (e) {
            var n = cur < 0 ? last : cur;
            if (e.key === "ArrowLeft" || e.key === "ArrowDown") n = Math.max(0, n - 1);
            else if (e.key === "ArrowRight" || e.key === "ArrowUp") n = Math.min(last, n + 1);
            else if (e.key === "Home") n = 0;
            else if (e.key === "End") n = last;
            else if (e.key === "Escape") { hide(); return; }
            else return;
            e.preventDefault();
            show(n);
        });
    });

    /* A tap outside every chart closes a tooltip a touch opened. */
    document.addEventListener("pointerdown", function (e) {
        if (active && !active.contains(e.target)) active.perfHide();
    });
})();
