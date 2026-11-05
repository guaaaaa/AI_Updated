/* AI Updated — Trends dashboard (#/trends): the monthly summary, the automatic Week in review, and field-wide
   charts (every new arXiv paper and reputable news story, not just our picks).
   Data: data/index.json (summaries, weeks, items), data/summaries/monthly/<id>.json, data/weeks/<id>.json,
   data/trends.json. Text is inserted with textContent; charts are inline SVG coloured by CSS variables, so the
   light/dark switch needs no re-render. */
(() => {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  // Stack/legend order is fixed (validated for adjacent-pair colour-blind separation); colour follows the group.
  const GROUPS = ["Generation & Embodiment", "Trust", "Capabilities", "Science & Theory", "Foundation Models", "Training"];
  const GVAR = { "Generation & Embodiment": "--viz-ge", "Trust": "--viz-trust", "Capabilities": "--viz-cap",
    "Science & Theory": "--viz-sci", "Foundation Models": "--viz-fm", "Training": "--viz-train" };
  const pct = (x, d = 1) => `${(x * 100).toFixed(d)}%`;
  const signed = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(0)}%`;
  let H = null;            // helpers from app.js
  let cache = { trends: null, sums: new Map(), files: new Map() };
  let resizeT = null, lastArgs = null, lastHash = null;

  function svg(tag, attrs, ...kids) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) n.setAttribute(k, v);
    for (const c of kids.flat(Infinity)) if (c != null) n.append(c instanceof Node ? c : document.createTextNode(c));
    return n;
  }
  const getSummary = (kind, id) => {
    const k = `${kind}/${id}`;
    if (!cache.sums.has(k)) cache.sums.set(k, H.getJSON(`data/summaries/${kind}/${id}.json`));
    return cache.sums.get(k);
  };
  const fmtRange = (a, b) => {
    const A = H.dObj(a), B = H.dObj(b);
    const m = (d) => d.toLocaleDateString("en-US", { month: "short" });
    return A.getMonth() === B.getMonth() ? `${m(A)} ${A.getDate()}–${B.getDate()}, ${B.getFullYear()}`
      : `${m(A)} ${A.getDate()} – ${m(B)} ${B.getDate()}, ${B.getFullYear()}`;
  };
  const monthLabel = (m) => new Date(m + "-15T12:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" });

  // ---------------------------------------------------------------- tooltip
  function tooltip(host) {
    const tip = H.el("div", { class: "viz-tip", role: "status" });
    tip.hidden = true;
    host.append(tip);
    return {
      show(x, y, rows) {
        tip.replaceChildren(...rows);
        tip.hidden = false;
        const hw = host.clientWidth, tw = tip.offsetWidth;
        tip.style.left = `${Math.max(4, Math.min(hw - tw - 4, x + 14))}px`;
        tip.style.top = `${Math.max(4, y - tip.offsetHeight - 10)}px`;
      },
      hide() { tip.hidden = true; },
    };
  }
  const tipRow = (value, label, colorVar) => H.el("div", { class: "tip-row" },
    colorVar ? H.el("span", { class: "tip-key", style: `background: var(${colorVar})` }) : null,
    H.el("strong", { text: value }), H.el("span", { text: label }));

  function table(caption, head, rows) {
    return H.el("details", { class: "viz-table" }, H.el("summary", { text: "Data table" }),
      H.el("div", { class: "table-wrap" }, H.el("table", {},
        H.el("caption", { class: "sr-only", text: caption }),
        H.el("thead", {}, H.el("tr", {}, head.map((h) => H.el("th", { text: h })))),
        H.el("tbody", {}, rows.map((r) => H.el("tr", {}, r.map((c, i) => H.el(i ? "td" : "th", { text: c }))))))));
  }

  const mLabel = (m) => `${new Date(m + "-15T12:00:00").toLocaleDateString("en-US", { month: "short" })} ’${m.slice(2, 4)}`;
  const span3 = (w) => `${new Date(w[0] + "-15T12:00:00").toLocaleDateString("en-US", { month: "short" })}–` +
    new Date(w[2] + "-15T12:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });
  const fit = (t, n) => (t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t);
  const significant = (z, rel) => z != null && rel != null && Math.abs(z) >= 3 && Math.abs(rel) >= 0.1;
  const pp = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(0)}%`);
  const STATUS = { new: ["★", "New"], rising: ["↑", "Rising"], fading: ["↓", "Fading"], steady: ["·", "Steady"] };

  // ---------------------------------------------------------------- small multiples (one line per panel, own scale)
  function linePanels(panels, xLabels) {
    const grid = H.el("div", { class: "sm-grid" });
    const n = xLabels.length;
    for (const P of panels) {
      const vals = P.values;
      const panel = H.el("div", { class: "sm-panel" });
      panel.append(H.el("div", { class: "sm-head" }, H.el("i", { style: `background: var(${P.color})` }), H.el("span", { text: P.title })),
        H.el("div", { class: "sm-figure" }, H.el("strong", { text: P.figure }),
          P.delta ? H.el("span", { class: "sm-delta " + (P.quiet ? "quiet" : P.up ? "up" : "down"), text: P.delta }) : null));
      const W = 260, Hh = 92, pl = 36, pr = 8, pt = 8, pb = 18;
      const lo = Math.min(...vals), hi = Math.max(...vals), padv = Math.max(1e-4, (hi - lo) * 0.15);
      const y0 = Math.max(0, lo - padv), y1 = hi + padv;
      const x = (i) => pl + (n === 1 ? (W - pl - pr) / 2 : (i * (W - pl - pr)) / (n - 1));
      const y = (v) => pt + (1 - (v - y0) / (y1 - y0 || 1)) * (Hh - pt - pb);
      const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
      const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", class: "sm-svg", role: "img",
        "aria-label": `${P.title}: from ${pct(vals[0], 2)} to ${pct(vals[n - 1], 2)}` },
        svg("line", { x1: pl, x2: W - pr, y1: Hh - pb, y2: Hh - pb, class: "zero" }),
        svg("text", { x: pl - 5, y: y(hi) + 4, class: "axis", "text-anchor": "end" }, pct(hi, hi < 0.01 ? 2 : 1)),
        svg("text", { x: pl - 5, y: y(lo) + 4, class: "axis", "text-anchor": "end" }, pct(lo, lo < 0.01 ? 2 : 1)),
        svg("text", { x: x(0), y: Hh - 4, class: "axis", "text-anchor": "start" }, xLabels[0]),
        svg("text", { x: x(n - 1), y: Hh - 4, class: "axis", "text-anchor": "end" }, xLabels[n - 1]),
        svg("path", { d: `${line} L${x(n - 1)},${Hh - pb} L${x(0)},${Hh - pb} Z`, class: "sm-area", style: `fill: var(${P.color})` }),
        svg("path", { d: line, class: "sm-line", style: `stroke: var(${P.color})` }),
        svg("circle", { cx: x(n - 1), cy: y(vals[n - 1]), r: 4, class: "sm-dot", style: `fill: var(${P.color})` }));
      const cross = svg("line", { y1: pt, y2: Hh - pb, class: "crosshair", visibility: "hidden" });
      s.append(cross);
      const tip = tooltip(panel);
      s.addEventListener("pointermove", (ev) => {
        const r = s.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
        const i = Math.max(0, Math.min(n - 1, Math.round(((px - pl) / (W - pl - pr)) * (n - 1))));
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
        const b = panel.getBoundingClientRect();
        tip.show(ev.clientX - b.left, ev.clientY - b.top, [H.el("div", { class: "tip-head", text: xLabels[i] }),
          tipRow(pct(vals[i], 2), P.unit || "of new papers", P.color)]);
      });
      s.addEventListener("pointerleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); });
      panel.append(s);
      grid.append(panel);
    }
    return grid;
  }

  // ---------------------------------------------------------------- heat grid (rows x months, deviation from own mean)
  function heatGrid(rows, xLabels, caption) {
    const box = H.el("div", { class: "viz-plot" });
    const W = Math.max(320, lastWidth()), labelW = Math.min(230, W * 0.4), n = xLabels.length;
    const cw = Math.max(6, (W - labelW - 8) / Math.max(1, n)), ch = 17, gap = 2, padT = 20;
    const Hh = padT + rows.length * ch + 6;
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img", "aria-label": caption });
    const step = Math.ceil(n / Math.max(1, Math.floor((W - labelW) / 52)));
    xLabels.forEach((l, i) => {
      if ((n - 1 - i) % step) return;
      s.append(svg("text", { x: labelW + i * cw + cw / 2, y: 12, class: "axis", "text-anchor": "middle" }, l));
    });
    const tip = tooltip(box);
    rows.forEach((r, ri) => {
      const yy = padT + ri * ch;
      const mean = r.values.reduce((a, b) => a + b, 0) / Math.max(1, n);
      s.append(svg("rect", { x: 0, y: yy + 4, width: 8, height: 8, rx: 2, style: `fill: var(${r.color})` }));
      const lab = svg("text", { x: 14, y: yy + 12, class: "row-label" }, fit(r.label, Math.floor((labelW - 20) / 6.4)), svg("title", {}, r.label));
      s.append(r.href ? svg("a", { href: r.href }, lab) : lab);
      r.values.forEach((v, i) => {
        const dev = mean ? v / mean - 1 : 0, k = Math.min(1, Math.abs(dev) / 0.6);
        const cell = svg("rect", { x: labelW + i * cw + gap / 2, y: yy + gap / 2, width: cw - gap, height: ch - gap, rx: 3,
          class: "cell", tabindex: 0, style: `fill: color-mix(in oklab, var(${dev >= 0 ? "--div-warm" : "--div-cool"}) ${Math.round(k * 100)}%, var(--div-mid))`,
          "aria-label": `${r.label}, ${xLabels[i]}: ${pct(v, 2)}, ${signed(dev)} vs its average` });
        const show = (ev) => {
          const b = box.getBoundingClientRect(), cr = cell.getBoundingClientRect();
          tip.show((ev && ev.clientX ? ev.clientX : cr.right) - b.left, (ev && ev.clientY ? ev.clientY : cr.top) - b.top, [
            H.el("div", { class: "tip-head", text: `${r.label} · ${xLabels[i]}` }),
            tipRow(pct(v, 2), r.unit || "of new papers"), tipRow(signed(dev), `vs its ${n}-month average`)]);
        };
        cell.addEventListener("pointermove", show);
        cell.addEventListener("focus", () => show(null));
        cell.addEventListener("pointerleave", () => tip.hide());
        cell.addEventListener("blur", () => tip.hide());
        s.append(cell);
      });
    });
    box.append(s, H.el("div", { class: "div-scale" }, H.el("span", { text: "below its usual level" }), H.el("i", { class: "div-bar" }),
      H.el("span", { text: "above its usual level" })));
    return box;
  }

  // ---------------------------------------------------------------- shared helpers for the direction views
  const roll3 = (a) => a.map((_, i) => { const w = a.slice(Math.max(0, i - 2), i + 1); return w.reduce((x, y) => x + y, 0) / w.length; });
  const compact = (v) => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}K` : String(Math.round(v)));
  const times = (r) => (r == null ? "–" : `×${(1 + r) >= 10 ? (1 + r).toFixed(0) : (1 + r).toFixed(1)}`);
  const short = (name) => name.replace(/\s*\(.*\)$/, "");
  const STCOL = { new: "--div-warm", rising: "--div-warm", fading: "--div-cool", steady: "--viz-context" };
  const dirHref = (id) => `#/trends/direction/${id}`;
  function niceTicks(max, n = 4) {
    const raw = max / n, mag = 10 ** Math.floor(Math.log10(raw || 1));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((x) => x >= raw) || raw;
    const out = [0];
    while (out[out.length - 1] < max - step * 1e-6) out.push(out[out.length - 1] + step);   // top tick >= max
    return out;
  }
  // end labels kept >= 13px apart within [lo, hi]
  function spread(ends, lo, hi, gap = 13) {
    ends.sort((a, b) => a.y0 - b.y0);
    ends.forEach((e, k) => { e.y = k ? Math.max(e.y0, ends[k - 1].y + gap) : Math.max(e.y0, lo); });
    const over = ends.length ? ends[ends.length - 1].y - hi : 0;
    if (over > 0) for (const e of ends) e.y -= over;
    for (let k = ends.length - 2; k >= 0; k--) ends[k].y = Math.min(ends[k].y, ends[k + 1].y - gap);
    return ends;
  }

  // One-sentence findings, written from the numbers, that title each chart.
  function findings(T) {
    const D = T.directions;
    const up = D.filter((d) => d.status === "rising" || d.status === "new").sort((a, b) => (b.rel_year ?? -9) - (a.rel_year ?? -9));
    const down = D.filter((d) => d.status === "fading").sort((a, b) => (a.rel_prev ?? 9) - (b.rel_prev ?? 9));
    const win = span3(T.window);
    const list = (arr, k, f) => arr.slice(0, k).map((d) => `${short(d.name)} (${f(d)})`).join(", ");
    const med = D.map((d) => d.share).sort((a, b) => a - b)[Math.floor(D.length / 2)];
    const quad = (pred) => D.filter((d) => d.rel_year != null && pred(d)).sort((a, b) => Math.abs(b.rel_year) - Math.abs(a.rel_year));
    const emerging = quad((d) => d.share < med && d.rel_year >= 0.5);
    const mainstream = quad((d) => d.share >= med && d.rel_year >= 0.25);
    const maturing = quad((d) => d.share >= med && d.rel_year <= -0.15);
    const hot = D.map((d) => { const s = d.series, k = s.length, avg = s.reduce((a, b) => a + b, 0) / k;
      return { d, r: avg ? (s[k - 1] + s[k - 2] + s[k - 3]) / 3 / avg - 1 : 0 }; }).sort((a, b) => b.r - a.r);
    const t0 = (T.terms_up || [])[0];
    const sigCats = T.news ? T.news.categories.filter((c) => significant(c.z_prev, c.share_prev ? c.share / c.share_prev - 1 : null)) : [];
    return {
      board: up.length || down.length
        ? `${up.length} of ${D.length} directions are rising and ${down.length} fading in ${win}. Fastest growth over a year: ${list(up, 2, (d) => times(d.rel_year))}` +
          (down.length ? `; fading: ${list(down, 2, (d) => pp(d.rel_prev) + " in 3 months")}.` : ".")
        : `No direction moved beyond noise level in ${win}.`,
      growth: up.length
        ? `Relative to all new papers, ${list(up, 3, (d) => times(d.rel_year))} grew fastest over the past year` +
          (down.length ? `, while ${short(down[0].name)} fell to ${times(down[0].rel_year)}.` : ".")
        : "No direction grew beyond noise level over the past year.",
      map: [emerging.length ? `Emerging: ${emerging.slice(0, 3).map((d) => short(d.name)).join(", ")}` : "",
        mainstream.length ? `growing mainstream: ${mainstream.slice(0, 2).map((d) => short(d.name)).join(", ")}` : "",
        maturing.length ? `maturing: ${maturing.slice(0, 2).map((d) => short(d.name)).join(", ")}` : ""].filter(Boolean).join("; ") + ".",
      heat: `In the last 3 months ${short(hot[0].d.name)} and ${short(hot[1].d.name)} ran furthest above their usual level; ` +
        `${short(hot[hot.length - 1].d.name)} ran furthest below.`,
      terms: t0 ? `'${t0.term}' appeared in ${t0.now} titles in ${win}, ${((t0.now + 5) / (t0.prev + 5)).toFixed(1)}× the previous 3 months, from ${t0.teams} teams.`
        : "No title phrase moved beyond noise level.",
      industry: !T.news ? "" : sigCats.length
        ? `${sigCats.map((c) => `${c.name} (${pp(c.share / c.share_prev - 1)})`).join(", ")} ${sigCats.length > 1 ? "are the only significant shifts" : "is the only significant shift"} in news coverage; every other category moved within noise.`
        : "No news category moved beyond noise level.",
    };
  }

  // ---------------------------------------------------------------- leaderboard: every direction, ticker-style
  function sparkline(values, color, w = 96, h = 22) {
    const v = roll3(values), lo = Math.min(...v), hi = Math.max(...v), n = v.length;
    const x = (i) => 2 + (i * (w - 6)) / Math.max(1, n - 1), y = (p) => 2 + (1 - (p - lo) / ((hi - lo) || 1)) * (h - 4);
    return svg("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, class: "spark", "aria-hidden": "true" },
      svg("path", { d: v.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" "), style: `stroke: var(${color})` }),
      svg("circle", { cx: x(n - 1), cy: y(v[n - 1]), r: 2.5, style: `fill: var(${color})` }));
  }
  function statusTag(d) {
    return H.el("span", { class: `st ${d.status}`, title: STATUS[d.status][1] }, STATUS[d.status][0],
      H.el("span", { class: "sr-only", text: STATUS[d.status][1] }));
  }
  function leaderboard(T) {
    const root = H.el("div"), body = H.el("div");
    const D = T.directions;
    const n = (s) => D.filter((d) => (s === "rising" ? d.status === "rising" || d.status === "new" : d.status === s)).length;
    const st = { show: "moving", sort: "momentum" };
    const sorts = { momentum: (a, b) => b.z_prev - a.z_prev, year: (a, b) => (b.rel_year ?? -9) - (a.rel_year ?? -9), size: (a, b) => b.share - a.share };
    const draw = () => {
      const rows = D.filter((d) => st.show === "all" || (st.show === "moving" ? d.status !== "steady"
        : st.show === "rising" ? d.status === "rising" || d.status === "new" : d.status === st.show))
        .sort(sorts[st.sort]);
      body.replaceChildren(H.el("div", { class: "table-wrap" }, H.el("table", { class: "board" },
        H.el("thead", {}, H.el("tr", {}, ["Direction", "24 months", "Share now", "3 months", "1 year", "Attention"].map((h, i) =>
          H.el("th", { class: ["", "c-spark", "num", "num c-3m", "num", "num c-att"][i], text: h })))),
        H.el("tbody", {}, rows.map((d) => H.el("tr", { class: d.status, onclick: (e) => { if (!e.target.closest("a")) location.hash = dirHref(d.id); } },
          H.el("td", { class: "c-name" }, statusTag(d), H.el("a", { href: dirHref(d.id), text: d.name }), H.el("a", { class: "c-field", href: fieldHref(d.group), text: d.group })),
          H.el("td", { class: "c-spark" }, sparkline(d.series, STCOL[d.status])),
          H.el("td", { class: "num", text: pct(d.share, 2) }),
          H.el("td", { class: "num c-3m", text: pp(d.rel_prev) }),
          H.el("td", { class: "num", text: times(d.rel_year) }),
          H.el("td", { class: "num c-att", text: d.attention == null ? "–" : `${pct(d.attention, 1)} ${d.attention_prev == null ? "" : d.attention > d.attention_prev * 1.15 ? "↑" : d.attention < d.attention_prev / 1.15 ? "↓" : "·"}` })))))));
    };
    root.append(H.el("div", { class: "line-controls" },
      segmented([["moving", `Moving ${n("rising") + n("fading")}`], ["rising", `Rising ${n("rising")}`], ["fading", `Fading ${n("fading")}`],
        ["all", `All ${D.length}`]], "moving", (k) => { st.show = k; draw(); }, "Show"),
      segmented([["momentum", "Momentum"], ["year", "1-year growth"], ["size", "Size"]], "momentum", (k) => { st.sort = k; draw(); }, "Sort by")),
      body,
      H.el("p", { class: "board-key", text: "Share now = share of all new papers in the last 3 months. 3 months = change against the 3 months before. " +
        "1 year = share now as a multiple of a year earlier. Attention = share of Hugging Face upvotes (↑/↓ = moved over 15%). " +
        "↑ rising, ↓ fading and ★ new passed the noise filters; · is noise-level movement. Select a row for its page." }));
    draw();
    return root;
  }

  // ---------------------------------------------------------------- growth since a year ago (indexed, log scale)
  function growthChart(T) {
    const root = H.el("div"), chartBox = H.el("div");
    const D = T.directions, n = T.series_months.length, b = Math.max(0, n - 13);
    const labels = T.series_months.slice(b).map(mLabel);
    const up = D.filter((d) => (d.status === "rising" || d.status === "new") && d.rel_year != null).sort((a, c) => c.rel_year - a.rel_year).slice(0, 6);
    const down = D.filter((d) => d.status === "fading" && d.rel_year != null).sort((a, c) => a.rel_year - c.rel_year).slice(0, 3);
    const chosen = new Set([...up, ...down].map((d) => d.id));
    const index = (d) => { const r = roll3(d.series).slice(b), base = r[0] || 1e-9; return r.map((v) => Math.min(16, Math.max(1 / 8, v / base))); };
    const draw = () => {
      const list = D.filter((d) => chosen.has(d.id));
      const W = Math.max(320, lastWidth()), Hh = 340, padL = 44, labW = Math.min(190, W * 0.3), padT = 12, padB = 28, x1 = W - labW - 8;
      const series = list.map((d) => ({ d, v: index(d) }));
      const all = series.flatMap((s) => s.v);
      const lo = Math.log2(Math.min(0.5, ...all)), hi = Math.log2(Math.max(2, ...all));
      const x = (i) => padL + (i * (x1 - padL)) / Math.max(1, labels.length - 1);
      const y = (v) => padT + (1 - (Math.log2(v) - lo) / (hi - lo)) * (Hh - padT - padB);
      const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img",
        "aria-label": "Each direction's share of new papers as a multiple of its share a year earlier (log scale)" });
      for (let e = Math.ceil(lo); e <= Math.floor(hi); e++) {
        const v = 2 ** e;
        s.append(svg("line", { x1: padL, x2: x1, y1: y(v), y2: y(v), class: e === 0 ? "base" : "zero" }));
        s.append(svg("text", { x: padL - 6, y: y(v) + 4, class: "axis", "text-anchor": "end" }, v >= 1 ? `${v}×` : `${v}×`));
      }
      labels.forEach((l, i) => { if (!((labels.length - 1 - i) % 3)) s.append(svg("text", { x: x(i), y: Hh - 8, class: "axis", "text-anchor": "middle" }, l)); });
      const col = (d) => ((d.rel_year || 0) >= 0 ? "--div-warm" : "--div-cool");
      for (const { d, v } of series) {
        s.append(svg("path", { d: v.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" "), class: "ln hi", style: `stroke: var(${col(d)})` }));
        s.append(svg("circle", { cx: x(v.length - 1), cy: y(v[v.length - 1]), r: 4, class: "sm-dot", style: `fill: var(${col(d)})` }));
      }
      const ends = spread(series.map((sr, i) => ({ i, y0: y(sr.v[sr.v.length - 1]) })), padT + 4, Hh - padB);
      for (const e of ends) {
        const { d, v } = series[e.i], lx = x1 + 10;
        if (Math.abs(e.y - e.y0) > 2) s.append(svg("path", { d: `M${x1 + 3},${e.y0} L${lx - 3},${e.y}`, class: "leader" }));
        const a = svg("a", { href: dirHref(d.id) }, svg("text", { x: lx, y: e.y + 4, class: "end-label hi" },
          `${fit(short(d.name), Math.floor((labW - 40) / 6.2))} ${times(v[v.length - 1] - 1)}`, svg("title", {}, d.name)));
        s.append(a);
      }
      const cross = svg("line", { y1: padT, y2: Hh - padB, class: "crosshair", visibility: "hidden" });
      s.append(cross);
      const box = H.el("div", { class: "viz-plot" }, s);
      const tip = tooltip(box);
      s.addEventListener("pointermove", (ev) => {
        const r = s.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
        const i = Math.max(0, Math.min(labels.length - 1, Math.round(((px - padL) / (x1 - padL)) * (labels.length - 1))));
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
        const bb = box.getBoundingClientRect();
        tip.show(ev.clientX - bb.left, ev.clientY - bb.top, [H.el("div", { class: "tip-head", text: `${labels[i]} · vs ${labels[0]}` }),
          ...series.map((sr) => ({ sr, v: sr.v[i] })).sort((p, q) => q.v - p.v).map(({ sr, v }) => tipRow(times(v - 1), short(sr.d.name), col(sr.d)))]);
      });
      s.addEventListener("pointerleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); });
      chartBox.replaceChildren(box);
    };
    const pick = H.el("select", { class: "period-select", "aria-label": "Add or remove a direction",
      onchange: (e) => { const id = e.target.value; if (id) { chosen.has(id) ? chosen.delete(id) : chosen.add(id); draw(); } e.target.value = ""; } },
      H.el("option", { value: "", text: "Add or remove a direction…" }),
      D.slice().sort((a, c) => a.name.localeCompare(c.name)).map((d) => H.el("option", { value: d.id, text: d.name })));
    root.append(H.el("div", { class: "line-controls" }, pick), chartBox,
      table("Share of new papers as a multiple of a year earlier", ["Direction", ...labels],
        D.filter((d) => chosen.has(d.id)).map((d) => [d.name, ...index(d).map((v) => times(v - 1))])));
    draw();
    return root;
  }

  // ---------------------------------------------------------------- momentum map: size vs growth, four quadrants
  function momentumMap(T) {
    const D = T.directions.filter((d) => d.rel_year != null && d.share > 0);
    const W = Math.max(320, lastWidth()), Hh = Math.min(460, Math.max(340, W * 0.55)), padL = 48, padR = 16, padT = 16, padB = 40;
    const xs = D.map((d) => Math.log10(d.share)), ys = D.map((d) => Math.log2(Math.max(1 / 8, Math.min(16, 1 + d.rel_year))));
    const x0 = Math.min(...xs) - 0.1, x1 = Math.max(...xs) + 0.1, y0 = Math.min(-1, ...ys) - 0.2, y1 = Math.max(2, ...ys) + 0.3;
    const X = (v) => padL + ((v - x0) / (x1 - x0)) * (W - padL - padR), Y = (v) => padT + (1 - (v - y0) / (y1 - y0)) * (Hh - padT - padB);
    const med = D.map((d) => d.share).sort((a, b) => a - b)[Math.floor(D.length / 2)];
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img",
      "aria-label": "Each direction's size (share of new papers) against its growth over a year" });
    for (const t of [0.0005, 0.001, 0.003, 0.01, 0.03, 0.1]) {
      const v = Math.log10(t);
      if (v < x0 || v > x1) continue;
      s.append(svg("line", { x1: X(v), x2: X(v), y1: padT, y2: Hh - padB, class: "zero" }));
      s.append(svg("text", { x: X(v), y: Hh - padB + 16, class: "axis", "text-anchor": "middle" }, pct(t, t < 0.01 ? 1 : 0)));
    }
    for (let e = Math.ceil(y0); e <= Math.floor(y1); e++) {
      s.append(svg("line", { x1: padL, x2: W - padR, y1: Y(e), y2: Y(e), class: e === 0 ? "base" : "zero" }));
      s.append(svg("text", { x: padL - 6, y: Y(e) + 4, class: "axis", "text-anchor": "end" }, `${2 ** e}×`));
    }
    s.append(svg("line", { x1: X(Math.log10(med)), x2: X(Math.log10(med)), y1: padT, y2: Hh - padB, class: "base" }));
    s.append(svg("text", { x: (padL + W - padR) / 2, y: Hh - 6, class: "axis", "text-anchor": "middle" }, "size: share of all new papers, last 3 months (log scale) →"));
    const q = [["Emerging", padL + 6, padT + 14, "start"], ["Growing mainstream", W - padR - 6, padT + 14, "end"],
      ["Fading niche", padL + 6, Hh - padB - 8, "start"], ["Maturing", W - padR - 6, Hh - padB - 8, "end"]];
    for (const [t, qx, qy, anchor] of q) s.append(svg("text", { x: qx, y: qy, class: "quad", "text-anchor": anchor }, t));
    const box = H.el("div", { class: "viz-plot" });
    const tip = tooltip(box);
    const placed = [];
    const order = D.slice().sort((a, b) => (a.status === "steady") - (b.status === "steady"));
    for (const d of order.slice().reverse()) {    // flagged dots drawn last (on top)
      const cx = X(Math.log10(d.share)), cy = Y(Math.log2(Math.max(1 / 8, Math.min(16, 1 + d.rel_year))));
      const g = svg("a", { href: dirHref(d.id), class: "dot", "aria-label": `${d.name}: ${pct(d.share, 2)}, ${times(d.rel_year)} vs a year ago` },
        svg("circle", { cx, cy, r: 11, class: "hit" }),
        svg("circle", { cx, cy, r: d.status === "steady" ? 4 : 5.5, class: "mark", style: `fill: var(${STCOL[d.status]})` }));
      const show = (ev) => { const bb = box.getBoundingClientRect(), cr = g.getBoundingClientRect();
        tip.show((ev && ev.clientX ? ev.clientX : cr.right) - bb.left, (ev && ev.clientY ? ev.clientY : cr.top) - bb.top, [
          H.el("div", { class: "tip-head", text: `${d.name} · ${STATUS[d.status][1]}` }),
          tipRow(pct(d.share, 2), "of new papers (last 3 months)"), tipRow(times(d.rel_year), "vs a year earlier"),
          tipRow(pp(d.rel_prev), "vs the previous 3 months")]); };
      g.addEventListener("pointermove", show);
      g.addEventListener("focus", () => show(null));
      g.addEventListener("pointerleave", () => tip.hide());
      g.addEventListener("blur", () => tip.hide());
      s.append(g);
    }
    // labels: flagged directions and the largest ones, skipped when they would overlap
    for (const d of order) {
      if (d.status === "steady" && d.share < 0.025) continue;
      const cx = X(Math.log10(d.share)), cy = Y(Math.log2(Math.max(1 / 8, Math.min(16, 1 + d.rel_year))));
      const label = fit(short(d.name), 26), w = label.length * 6.1, right = cx + 8 + w < W - padR;
      const bx = right ? cx + 8 : cx - 8 - w, by = cy - 6;
      if (placed.some((p) => bx < p.x + p.w && bx + w > p.x && by < p.y + 13 && by + 13 > p.y)) continue;
      placed.push({ x: bx, y: by, w });
      s.append(svg("text", { x: right ? cx + 8 : cx - 8, y: cy + 4, class: "map-label" + (d.status === "steady" ? "" : " hi"),
        "text-anchor": right ? "start" : "end" }, label));
    }
    box.prepend(s);
    return box;
  }

  // ---------------------------------------------------------------- direction page (#/trends/direction/<id>)
  // ---------------------------------------------------------------- stock-style pages: one direction or one field
  // Data: data/daily.json (every arXiv announcement day: all new papers, all upvotes, each field) and
  // data/fields/<slug>.json (each direction of a field, day by day). A range picks how far back to look and how many
  // announcement days each point averages (arXiv announces 5 days a week), so longer ranges draw smoother lines.
  const RANGES = [
    { key: "1W", days: 7, k: 1, words: "past week" }, { key: "1M", months: 1, k: 5, words: "past month" },
    { key: "3M", months: 3, k: 10, words: "past 3 months" }, { key: "6M", months: 6, k: 21, words: "past 6 months" },
    { key: "1Y", months: 12, k: 42, words: "past year" }, { key: "2Y", months: 24, k: 63, words: "past 2 years" }];
  const METRICS = {
    share: { label: "Share", unit: "of new papers", fmt: (v) => pct(v, 2), d: (x) => `${Math.abs(x * 100).toFixed(2)} pts`,
      about: "share of all new arXiv papers in our categories" },
    perday: { label: "Papers a day", unit: "papers a day", fmt: (v) => (v >= 100 ? v.toFixed(0) : v.toFixed(1)), d: (x) => Math.abs(x).toFixed(1),
      about: "new arXiv papers per announcement day" },
    att: { label: "Upvotes", unit: "of Hugging Face upvotes", fmt: (v) => pct(v, 1), d: (x) => `${Math.abs(x * 100).toFixed(1)} pts`,
      about: "share of all Hugging Face Daily Papers upvotes" },
  };
  const view = { range: "1Y", metric: "share" };   // kept while moving between pages
  const fieldSlug = (g) => g.toLowerCase().replace(/[^a-z]+/g, "-").replace(/^-|-$/g, "");
  const fieldHref = (g) => `#/trends/field/${fieldSlug(g)}`;
  const memo = (key, url) => { if (!cache.files.has(key)) cache.files.set(key, H.getJSON(url).catch((e) => { cache.files.delete(key); throw e; })); return cache.files.get(key); };
  const getDaily = () => memo("daily", "data/daily.json");
  const getField = (slug) => memo(`field/${slug}`, `data/fields/${slug}.json`);
  const cum = (a) => { const p = new Float64Array(a.length + 1); a.forEach((v, i) => { p[i + 1] = p[i] + (v || 0); }); return p; };
  const wsum = (P, i, k) => P[i + 1] - P[Math.max(0, i - k + 1)];
  const longDate = (iso) => H.dObj(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  const series = (daily, c, up) => ({ days: daily.days, n: daily.n, c, up, Pn: cum(daily.n), Pc: cum(c), Pa: cum(daily.hf_up), Pu: cum(up) });

  function startIndex(days, r) {
    if (r.all) return 0;
    const s = H.dObj(days[days.length - 1]);
    if (r.days) s.setDate(s.getDate() - r.days); else s.setMonth(s.getMonth() - r.months);
    const iso = H.isoOf(s), i = days.findIndex((d) => d >= iso);
    return i < 0 ? 0 : i;
  }
  function valueAt(m, S, i, k) {
    if (m === "share") { const t = wsum(S.Pn, i, k); return t ? wsum(S.Pc, i, k) / t : null; }
    if (m === "perday") return wsum(S.Pc, i, k) / Math.min(k, i + 1);
    const t = wsum(S.Pa, i, k); return t ? wsum(S.Pu, i, k) / t : null;
  }
  function curve(m, S, r) {
    const from = startIndex(S.days, r), vals = [];
    for (let i = from; i < S.days.length; i++) vals.push(valueAt(m, S, i, r.k));
    return { from, vals };
  }
  // z of the change from the first point's window to the last one's (share: two proportions; papers: Poisson counts)
  function changeZ(m, S, from, k) {
    const L = S.days.length - 1, c1 = wsum(S.Pc, from, k), c2 = wsum(S.Pc, L, k);
    if (m === "share") {
      const n1 = wsum(S.Pn, from, k), n2 = wsum(S.Pn, L, k), p = (c1 + c2) / (n1 + n2);
      const se = Math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2));
      return se ? (c2 / n2 - c1 / n1) / se : 0;
    }
    if (m === "perday") return c1 + c2 ? (c2 - c1) / Math.sqrt(c1 + c2) : 0;
    return null;
  }
  const ends = (vals) => {
    let a = 0, b = vals.length - 1;
    while (a < b && vals[a] == null) a++;
    while (b > a && vals[b] == null) b--;
    return [a, b];
  };

  function miniLine(vals, color, w = 88, h = 26) {
    const fin = vals.filter((v) => v != null), lo = Math.min(...fin), hi = Math.max(...fin), n = vals.length;
    const x = (i) => 2 + (i * (w - 6)) / Math.max(1, n - 1), y = (v) => 2 + (1 - (v - lo) / ((hi - lo) || 1)) * (h - 4);
    let d = "", pen = false;
    vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
    return svg("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, class: "spark", "aria-hidden": "true" },
      svg("path", { d, style: `stroke: var(${color})` }));
  }

  // The chart: no grid, a dotted line at the range's first value, the period's high and low on the right, and
  // the raw daily counts as faint bars underneath. Hover or drag to read any day.
  function stockChart(days, cv, bars, r, M, color, onScrub) {
    const W = Math.max(300, lastWidth()), Hh = W < 520 ? 230 : 290;
    const padL = 2, padR = 58, padT = 26, volH = 34, padB = 22, gap = 10, lineB = Hh - padB - volH - gap;
    const vals = cv.vals, n = vals.length, [a, b] = ends(vals), base = vals[a];
    const fin = vals.filter((v) => v != null);
    let lo = Math.min(...fin), hi = Math.max(...fin);
    const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.1 || 0.001;
    lo = Math.max(0, lo - pad); hi += pad;
    const x = (i) => padL + (n > 1 ? (i * (W - padL - padR)) / (n - 1) : (W - padL - padR) / 2);
    const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (lineB - padT);
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, class: "stock-svg", role: "img",
      "aria-label": `${M.label}, ${r.words}: from ${M.fmt(base)} to ${M.fmt(vals[b])}` });
    s.append(svg("line", { x1: padL, x2: W - padR, y1: y(base), y2: y(base), class: "base-line" }));
    const iHi = vals.indexOf(Math.max(...fin)), iLo = vals.indexOf(Math.min(...fin));
    const lab = [[iHi, "high"], [iLo, "low"]].filter(([i], j, arr) => !j || Math.abs(y(vals[i]) - y(vals[arr[0][0]])) >= 14);
    for (const [i] of lab) s.append(svg("text", { x: W - padR + 8, y: y(vals[i]) + 4, class: "axis" }, M.fmt(vals[i])));
    const bmax = Math.max(1, ...bars), bw = Math.max(1, Math.min(10, ((W - padL - padR) / Math.max(1, n)) * 0.7));
    const barEls = bars.map((v, i) => {
      const hgt = (v / bmax) * volH;
      return v ? svg("rect", { x: x(i) - bw / 2, y: Hh - padB - hgt, width: bw, height: hgt, class: "vol" }) : null;
    });
    s.append(...barEls.filter(Boolean));
    let d = "", pen = false;
    vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true; });
    s.append(svg("path", { d, class: "stock-line", style: `stroke: var(${color})` }));
    s.append(svg("circle", { cx: x(b), cy: y(vals[b]), r: 3.5, style: `fill: var(${color})` }));
    const long = (r.months || 0) >= 6 || r.all;
    const fmtD = (iso) => H.dObj(iso).toLocaleDateString("en-US", long ? { month: "short", year: "numeric" } : { month: "short", day: "numeric" });
    const ticks = n <= 3 ? [0, n - 1] : W < 520 ? [0, Math.round((n - 1) / 2), n - 1]
      : [0, Math.round((n - 1) / 3), Math.round((2 * (n - 1)) / 3), n - 1];
    ticks.forEach((i, j) => s.append(svg("text", { x: x(i), y: Hh - 5, class: "axis",
      "text-anchor": j === 0 ? "start" : j === ticks.length - 1 ? "end" : "middle" }, fmtD(days[cv.from + i]))));
    const cross = svg("line", { y1: padT - 6, y2: Hh - padB, class: "crosshair", visibility: "hidden" });
    const dot = svg("circle", { r: 5, class: "stock-dot", style: `fill: var(${color})`, visibility: "hidden" });
    const when = svg("text", { y: 12, class: "axis scrub-date", "text-anchor": "middle", visibility: "hidden" });
    s.append(cross, dot, when);
    let lit = null;
    const show = (on) => [cross, dot, when].forEach((e) => e.setAttribute("visibility", on ? "visible" : "hidden"));
    const move = (ev) => {
      const rr = s.getBoundingClientRect(), px = ((ev.clientX - rr.left) / rr.width) * W;
      let i = Math.max(a, Math.min(b, Math.round(((px - padL) / (W - padL - padR)) * (n - 1))));
      while (i > a && vals[i] == null) i--;
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i));
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(vals[i]));
      when.textContent = (M.dateFmt || longDate)(days[cv.from + i]);
      when.setAttribute("x", Math.max(56, Math.min(W - padR - 56, x(i))));
      if (lit) lit.classList.remove("on");
      lit = barEls[i]; if (lit) lit.classList.add("on");
      show(true);
      onScrub(i);
    };
    s.addEventListener("pointermove", move);
    s.addEventListener("pointerdown", move);
    s.addEventListener("pointerleave", () => { show(false); if (lit) lit.classList.remove("on"); onScrub(null); });
    return s;
  }

  // The quote block + chart + range and metric switches. onChange lets lists below follow the same range.
  function stockCard(S, onChange) {
    const big = H.el("strong", { class: "stock-big" }), unit = H.el("span", { class: "stock-unit" });
    const chg = H.el("div", { class: "stock-change", "aria-live": "polite" }), note = H.el("div", { class: "stock-note" });
    const plot = H.el("div", { class: "stock-plot" }), how = H.el("p", { class: "viz-sub stock-how" });
    const draw = () => {
      const r = RANGES.find((x) => x.key === view.range), m = view.metric, M = METRICS[m];
      const cv = curve(m, S, r), vals = cv.vals, [a, b] = ends(vals), base = vals[a];
      const z = changeZ(m, S, cv.from, r.k), up = vals[b] >= base, color = up ? "--div-warm" : "--div-cool";
      const quote = (i) => {
        const v = vals[i], dv = v - base, rel = base ? dv / base : null, atEnd = i === b;
        big.textContent = M.fmt(v);
        unit.textContent = M.unit;
        chg.replaceChildren(...[
          H.el("span", { class: dv >= 0 ? "up" : "down", text: `${dv >= 0 ? "▲" : "▼"} ${M.d(dv)}${rel == null ? "" : ` (${Math.abs(rel * 100).toFixed(rel && Math.abs(rel) < 0.1 ? 1 : 0)}%)`}` }),
          H.el("span", { class: "when", text: atEnd ? r.words : `since ${longDate(S.days[cv.from + a])}` }),
          atEnd && z != null && Math.abs(z) < 2 ? H.el("span", { class: "noise", title: `z = ${z.toFixed(1)}`, text: "within noise" }) : null].filter(Boolean));
        note.textContent = `${r.k === 1 ? "Single announcement day" : `${r.k}-day average`} · ${longDate(S.days[cv.from + i])}`;
      };
      quote(b);
      const bars = (m === "att" ? S.up : S.c).slice(cv.from);
      plot.replaceChildren(stockChart(S.days, cv, bars, r, M, color, (i) => quote(i == null ? b : i)));
      how.textContent = `Line: ${M.about}, ${r.k === 1 ? "one announcement day per point" : `each point averaging the ${r.k} announcement days up to it`}` +
        ` (longer ranges average more days, so the line smooths out). Dotted line: the value at the start of the range. ` +
        `Bars: ${m === "att" ? "upvotes" : "papers"} per day. "Within noise" means the change is smaller than chance variation would explain (|z| < 2).`;
      if (onChange) onChange();
    };
    const card = H.el("section", { class: "card stock-card" },
      H.el("div", { class: "stock-top" },
        H.el("div", { class: "stock-quote" }, H.el("div", {}, big, unit), chg, note),
        segmented(Object.entries(METRICS).map(([k, x]) => [k, x.label]), view.metric, (k) => { view.metric = k; draw(); }, "Measure")),
      plot,
      H.el("div", { class: "stock-ranges" },
        segmented(RANGES.map((r) => [r.key, r.key]), view.range, (k) => { view.range = k; draw(); }, "Time range")),
      how);
    draw();
    return card;
  }

  // Ticker-style rows (a field's directions) that follow the chosen range and measure.
  function holdings(daily, members, selfId) {
    const list = H.el("div", { class: "holdings" });
    const draw = () => {
      const r = RANGES.find((x) => x.key === view.range), m = view.metric, M = METRICS[m];
      const rows = members.map((x) => {
        const S = series(daily, x.n, x.up), cv = curve(m, S, r), [a, b] = ends(cv.vals);
        return { x, cv, a: cv.vals[a], b: cv.vals[b], z: changeZ(m, S, cv.from, r.k) };
      }).sort((p, q) => (q.b ?? -1) - (p.b ?? -1));
      list.replaceChildren(...rows.map(({ x, cv, a, b, z }) => {
        const up = b >= a, rel = a ? b / a - 1 : null, quiet = z != null && Math.abs(z) < 2;
        return H.el("a", { class: "hold" + (x.id === selfId ? " self" : ""), href: dirHref(x.id), "aria-current": x.id === selfId ? "page" : null },
          H.el("span", { class: `st ${x.status}`, title: STATUS[x.status][1], text: STATUS[x.status][0] }),
          H.el("span", { class: "hold-name", text: x.name }),
          miniLine(cv.vals, quiet ? "--viz-context" : up ? "--div-warm" : "--div-cool"),
          H.el("span", { class: "hold-val", text: b == null ? "–" : M.fmt(b) }),
          H.el("span", { class: `hold-chg ${up ? "up" : "down"}${quiet ? " quiet" : ""}`, title: quiet ? "within noise" : "", text: rel == null ? "–" : pp(rel) }));
      }));
    };
    return { node: list, draw };
  }

  function keyStats(S, extra) {
    const L = S.days.length - 1, y1 = startIndex(S.days, { months: 12 });
    let lo = Infinity, hi = -Infinity;
    for (let i = y1; i <= L; i++) { const v = valueAt("share", S, i, 21); if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }
    const att = valueAt("att", S, L, 63);
    const rows = [
      ["Papers, latest day", S.c[L].toLocaleString(), `${H.fmtShort(S.days[L])}, of ${S.n[L].toLocaleString()} new`],
      ["Average a day", (wsum(S.Pc, L, 21) / Math.min(21, L + 1)).toFixed(1), "last 21 announcement days"],
      ["Share of new papers", pct(valueAt("share", S, L, 21), 2), "last 21 announcement days"],
      ["52-week range", `${pct(lo, 2)} – ${pct(hi, 2)}`, "21-day share"],
      ["Papers, past year", (S.Pc[L + 1] - S.Pc[y1]).toLocaleString(), `since ${longDate(S.days[y1])}`],
      ["Upvote share", att == null ? "–" : pct(att, 1), "last 63 days, Hugging Face"],
      ...extra];
    return H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Key statistics" })),
      H.el("dl", { class: "kstats" }, rows.map(([k, v, sub]) => H.el("div", {}, H.el("dt", { text: k }),
        H.el("dd", {}, H.el("strong", { text: v }), sub ? H.el("span", { text: sub }) : null)))));
  }

  const paperList = (title, rows, empty) => H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: title })),
    rows.length ? H.el("ol", { class: "rank" }, rows) : H.el("p", { class: "note", text: empty }));
  const topPapers = (top, win) => paperList(`Most-upvoted papers, ${win}`, top.map(([pid, title, up, date]) => H.el("li", {},
    H.el("a", { href: `https://arxiv.org/abs/${pid}`, target: "_blank", rel: "noopener", text: title }),
    H.el("span", { class: "rank-meta", text: `${up} upvotes · ${H.fmtShort(date)}` }))), "No Hugging Face papers in this window.");
  const ourPapers = (featured, empty) => paperList("In our digests", featured.map((f) => H.el("li", {},
    H.el("a", { href: `#/day/${f.date}/${f.id}`, text: f.title }), H.el("span", { class: "rank-meta", text: H.fmtShort(f.date) }))), empty);

  async function stockPage(main, kind, id, T) {
    let daily, field, d = null;
    try {
      daily = await getDaily();
      if (kind === "direction") { d = await H.getJSON(`data/directions/${id}.json`); field = await getField(fieldSlug(d.group)); }
      else field = await getField(id);
    } catch (e) {
      main.replaceChildren(H.el("p", { class: "note" }, `That ${kind} does not exist. `, H.el("a", { href: "#/trends", text: "Back to Trends" })));
      return;
    }
    const win = span3(field.window), G = daily.groups[field.name];
    const self = d ? field.members.find((x) => x.id === d.id) : null;
    const S = self ? series(daily, self.n, self.up) : series(daily, G.n, G.up);
    const hold = holdings(daily, field.members, d ? d.id : null);
    const stock = stockCard(S, hold.draw);
    hold.draw();
    const out = [];
    if (d) {
      const verdict = { rising: "Rising", new: "New and rising", fading: "Fading", steady: "Steady (movement within noise)" }[d.status];
      const rank = T ? T.directions.slice().sort((p, q) => q.share - p.share).findIndex((x) => x.id === d.id) + 1 : 0;
      out.push(H.el("div", { class: "day-head" }, H.el("div", {},
          H.el("a", { class: "back", href: "#/trends", text: "← Trends" }),
          H.el("h1", { text: d.name }),
          H.el("div", { class: "day-meta" }, H.el("span", { class: `st ${d.status}`, text: `${STATUS[d.status][0]} ${STATUS[d.status][1]}` }),
            H.el("span", { text: "·" }), H.el("a", { href: fieldHref(d.group), text: d.group })))),
        stock,
        keyStats(S, [
          ["Teams", d.teams.toLocaleString(), `distinct last authors, ${win}`],
          ["vs a year earlier", times(d.rel_year), `share in ${win} vs the same months a year before`],
          ["Rank by share", rank ? `#${rank} of ${T.directions.length}` : "–", `among research directions, ${win}`]]),
        H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Trend signal" })),
          H.el("p", { class: "signal", text: `${verdict}: ${pct(d.share, 2)} of all new arXiv papers in ${win} (${d.n.toLocaleString()} papers from ` +
            `${d.teams.toLocaleString()} teams), ${pp(d.rel_prev)} against the previous 3 months (z ${d.z_prev}, above that level in ${d.months_above} of 3 months) ` +
            `and ${times(d.rel_year)} its share a year earlier. This is the monthly model behind the leaderboard: a direction counts as rising or fading only ` +
            "when the change is large, statistically clear, spread across many teams and consistent with the year before." })),
        H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Directions in this field" }),
          H.el("a", { class: "card-date", href: fieldHref(d.group), text: `${d.group} →` })), hold.node),
        topPapers(d.hf_top, win),
        ourPapers(d.featured, "We have not featured a paper in this direction yet."));
    } else {
      const shares = Object.entries(daily.groups).map(([g, x]) => [g, valueAt("share", series(daily, x.n, x.up), daily.days.length - 1, 63)]).sort((p, q) => q[1] - p[1]);
      const nUp = field.members.filter((x) => x.status === "rising" || x.status === "new").length, nDown = field.members.filter((x) => x.status === "fading").length;
      out.push(H.el("div", { class: "day-head" }, H.el("div", {},
          H.el("a", { class: "back", href: "#/trends", text: "← Trends" }),
          H.el("h1", { text: field.name }),
          H.el("div", { class: "day-meta", text: `Field · ${field.members.length} research directions · papers matching any of them` }))),
        stock,
        keyStats(S, [
          ["Directions", String(field.members.length), `${nUp} rising, ${nDown} fading in ${win}`],
          ["Rank by share", `#${shares.findIndex(([g]) => g === field.name) + 1} of ${shares.length}`, "among fields, last 63 days"]]),
        H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Directions in this field" })), hold.node),
        topPapers(field.hf_top, win),
        ourPapers(field.featured, "We have not featured a paper in this field yet."));
    }
    main.replaceChildren(...out);
  }

  // Trends page: the six fields as index tiles (past year, 21-day average share).
  function fieldTiles(daily) {
    const r = { months: 12, k: 21 };
    return H.el("section", { class: "card", id: "fields" },
      H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Fields" }), H.el("span", { class: "card-date", text: "share of new papers · past year" })),
      H.el("div", { class: "field-tiles" }, GROUPS.filter((g) => daily.groups[g]).map((g) => {
        const x = daily.groups[g], S = series(daily, x.n, x.up), cv = curve("share", S, r), [a, b] = ends(cv.vals);
        const v0 = cv.vals[a], v1 = cv.vals[b], up = v1 >= v0, z = changeZ("share", S, cv.from, r.k), quiet = Math.abs(z) < 2;
        return H.el("a", { class: "field-tile", href: fieldHref(g) },
          H.el("span", { class: "ft-name", text: g }),
          H.el("span", { class: "ft-row" }, H.el("strong", { text: pct(v1, 1) }),
            H.el("span", { class: `hold-chg ${up ? "up" : "down"}${quiet ? " quiet" : ""}`, text: `${up ? "▲" : "▼"} ${Math.abs((v1 / v0 - 1) * 100).toFixed(0)}%` })),
          (() => { const l = miniLine(cv.vals, quiet ? "--viz-context" : up ? "--div-warm" : "--div-cool", 140, 30); l.setAttribute("preserveAspectRatio", "none"); return l; })());
      })));
  }

  function termBars(up, down) {
    const box = H.el("div", { class: "viz-plot movers" });
    const groups = [["Emerging", up, true], ["Fading", down, false]].filter((g) => g[1].length);
    if (!groups.length) { box.append(H.el("p", { class: "note", text: "No title term moved beyond noise level." })); return box; }
    const W = Math.max(320, lastWidth()), labelW = Math.min(220, W * 0.4), rh = 22, headH = 22, valW = 110;
    const change = (m) => (m.now + 5) / (m.prev + 5) - 1;
    const maxAbs = Math.max(0.5, ...groups.flatMap((g) => g[1].map((m) => Math.abs(change(m)))));
    const span = W - labelW - valW;
    const Hh = groups.reduce((h, g) => h + headH + g[1].length * rh + 8, 0);
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img", "aria-label": "Emerging and fading title terms" });
    let yy = 0;
    for (const [name, rows, isUp] of groups) {
      s.append(svg("text", { x: 0, y: yy + 14, class: "group-label" }, `${isUp ? "▲" : "▼"} ${name}`));
      yy += headH;
      for (const m of rows) {
        const len = Math.max(4, (Math.abs(change(m)) / maxAbs) * span);
        s.append(svg("text", { x: labelW - 8, y: yy + 13, class: "row-label", "text-anchor": "end" }, m.term));
        s.append(svg("path", { d: `M${labelW},${yy + 2} h${len - 4} a4,4 0 0 1 4,4 v6 a4,4 0 0 1 -4,4 h${-(len - 4)} z`,
          style: `fill: var(${isUp ? "--div-warm" : "--div-cool"})` }));
        s.append(svg("text", { x: labelW + len + 6, y: yy + 13, class: "val" }, `${m.now} vs ${m.prev}${m.teams ? ` · ${m.teams} teams` : ""}`));
        yy += rh;
      }
      yy += 8;
    }
    box.append(s);
    return box;
  }

  // ---------------------------------------------------------------- chart 4: constellation of our picks
  function constellation(items, groupOf) {
    const box = H.el("div", { class: "viz-plot" });
    const lanes = [...GROUPS, "News"];
    const W = Math.max(320, lastWidth()), labelW = Math.min(178, W * 0.34), lh = 34, padT = 8, Hh = padT + lanes.length * lh + 24;
    const dates = items.map((i) => i.date).sort();
    if (!dates.length) return box;
    const t0 = H.dObj(dates[0]).getTime(), t1 = H.dObj(dates[dates.length - 1]).getTime() || t0 + 1;
    const x = (iso) => labelW + 14 + ((H.dObj(iso).getTime() - t0) / Math.max(1, t1 - t0)) * (W - labelW - 30);
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img",
      "aria-label": "Every featured paper and news story by date and topic group" });
    lanes.forEach((l, li) => {
      const yy = padT + li * lh + lh / 2;
      s.append(svg("line", { x1: labelW, x2: W - 6, y1: yy, y2: yy, class: "lane" }));
      s.append(svg("circle", { cx: 6, cy: yy, r: 4, style: `fill: var(${l === "News" ? "--viz-news" : GVAR[l]})` }));
      s.append(svg("text", { x: 16, y: yy + 4, class: "row-label" }, l));
    });
    // month / week ticks: Mondays
    const seen = new Set();
    for (const d of dates) {
      const D = H.dObj(d), mon = new Date(D); mon.setDate(D.getDate() - ((D.getDay() + 6) % 7));
      const iso = H.isoOf(mon);
      if (seen.has(iso) || iso < dates[0]) continue;
      seen.add(iso);
      s.append(svg("text", { x: x(iso), y: Hh - 6, class: "axis", "text-anchor": "middle" },
        mon.toLocaleDateString("en-US", { month: "short", day: "numeric" })));
    }
    const tip = tooltip(box);
    const jitter = {};
    for (const it of items) {
      const lane = it.type === "news" ? "News" : groupOf[it.primary_tag];
      const li = lanes.indexOf(lane);
      if (li < 0) continue;
      const key = `${lane}|${it.date}`, k = (jitter[key] = (jitter[key] || 0) + 1) - 1;
      const yy = padT + li * lh + lh / 2 + ((k % 3) - 1) * 8, xx = x(it.date) + Math.floor(k / 3) * 7;
      const r = it.type === "news" ? 5 : Math.min(9, 4 + Math.sqrt(it.hf || 0) / 2.2);
      const g = svg("g", { class: "dot", tabindex: 0, role: "link", "aria-label": `${it.title} (${it.date})` },
        svg("circle", { cx: xx, cy: yy, r: 12, class: "hit" }),
        svg("circle", { cx: xx, cy: yy, r, style: `fill: var(${lane === "News" ? "--viz-news" : GVAR[lane]})`, class: "mark" }));
      const show = (ev) => {
        const b = box.getBoundingClientRect(), cr = g.getBoundingClientRect();
        tip.show((ev && ev.clientX ? ev.clientX : cr.right) - b.left, (ev && ev.clientY ? ev.clientY : cr.top) - b.top, [
          H.el("div", { class: "tip-head", text: `${it.type === "news" ? "News · " + it.category : "Paper · " + it.primary_tag} · ${H.fmtShort(it.date)}` }),
          H.el("div", { class: "tip-title", text: it.title }),
          H.el("div", { class: "tip-foot", text: it.tldr })]);
      };
      const open = () => { location.hash = `#/day/${it.date}/${it.id}`; };
      g.addEventListener("pointermove", show);
      g.addEventListener("focus", () => show(null));
      g.addEventListener("pointerleave", () => tip.hide());
      g.addEventListener("blur", () => tip.hide());
      g.addEventListener("click", open);
      g.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      s.append(g);
    }
    box.append(s);
    return box;
  }

  // ---------------------------------------------------------------- summaries
  function refLinker(s) {
    const order = new Map();
    const number = (tok) => { if (!order.has(tok)) order.set(tok, order.size + 1); return order.get(tok); };
    const target = (tok) => {
      const r = s.refs[tok];
      if (/^S\d+$/.test(tok)) { const src = s.sources.find((x) => x.id === tok); return src && H.safeUrl(src.url); }
      if (r && r.date) return `#/day/${r.date}/${tok}`;
      if (/^\d{4}\.\d{4,5}$/.test(tok)) return `https://arxiv.org/abs/${tok}`;
      return null;
    };
    const label = (tok) => {
      if (/stats$/.test(tok)) return tok === "news stats" ? "Industry story statistics (charts below)" : "Field-wide statistics across all new papers (charts below)";
      if (/^S\d+$/.test(tok)) { const src = s.sources.find((x) => x.id === tok); return src ? src.name : tok; }
      const r = s.refs[tok];
      return r ? `${r.type === "news" ? "News" : "Paper"}${r.date ? "" : " (not featured)"}: ${r.title}` : tok;
    };
    const marker = (tok) => {
      if (/stats$/.test(tok)) return H.el("a", { class: "ref stats", href: "javascript:void 0", title: label(tok),
        onclick: (e) => { e.preventDefault(); const c = document.getElementById("field-charts"); if (c) c.scrollIntoView({ behavior: "smooth" }); },
        text: tok === "news stats" ? "news" : "field" });
      const u = target(tok), n = number(tok);
      const ext = u && /^https:/.test(u);
      return H.el("a", { class: "ref", href: u || "javascript:void 0", title: label(tok), target: ext ? "_blank" : null,
        rel: ext ? "noopener" : null, text: String(n) });
    };
    const rich = (text) => {
      const out = [];
      let last = 0;
      for (const m of text.matchAll(/\[([^\[\]]+)\]/g)) {
        out.push(text.slice(last, m.index).replace(/\s+$/, ""));
        out.push(H.el("span", { class: "refs" }, m[1].split(",").map((t) => marker(t.trim()))));
        last = m.index + m[0].length;
      }
      out.push(text.slice(last));
      return out;
    };
    const evidence = () => [...order.entries()].map(([tok, n]) => {
      const u = target(tok), ext = u && /^https:/.test(u);
      return H.el("li", {}, H.el("span", { class: "ev-n", text: String(n) }),
        u ? H.el("a", { href: u, target: ext ? "_blank" : null, rel: ext ? "noopener" : null, text: label(tok) }) : label(tok));
    });
    return { rich, evidence, reset: () => order.clear() };
  }

  function trendChips(list, up) {
    return list.map((h) => H.el("span", { class: `trend-chip ${up ? "up" : "down"}`, title: up ? "Heating up" : "Cooling down" },
      H.el("b", { "aria-hidden": "true", text: up ? "↑" : "↓" }), H.el("span", { class: "sr-only", text: up ? "Heating up: " : "Cooling down: " }), h.label));
  }

  // A small segmented switch; calls onPick(key) and marks the chosen button.
  function segmented(options, current, onPick, label) {
    const seg = H.el("div", { class: "seg", role: "tablist", "aria-label": label });
    for (const [key, text] of options) {
      const b = H.el("button", { role: "tab", class: key === current ? "on" : null, "aria-selected": String(key === current), text });
      b.addEventListener("click", () => {
        for (const x of seg.children) { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", String(x === b)); }
        onPick(key);
      });
      seg.append(b);
    }
    return seg;
  }

  function summaryCard(s) {
    const L = refLinker(s);
    const part = (key) => {
      L.reset();
      const p = s[key];
      const themes = p.themes.map((t) => H.el("div", { class: "theme" }, H.el("h4", { text: t.title }),
        t.body.split(/\n\s*\n/).map((para) => H.el("p", {}, L.rich(para.trim())))));
      const ev = L.evidence();
      return H.el("section", { class: `sum-part ${key}` },
        H.el("div", { class: "trend-chips" }, trendChips(p.heating, true), trendChips(p.cooling, false)),
        themes,
        ev.length ? H.el("details", { class: "evidence" }, H.el("summary", { text: `Evidence (${ev.length})` }), H.el("ol", {}, ev)) : null);
    };
    const holder = H.el("div", {}, part("research"));
    const period = monthLabel(s.id);
    return H.el("article", { class: "card summary", id: `sum-${s.kind}-${s.id}` },
      H.el("div", { class: "card-top" },
        H.el("span", { class: "kind", text: "Monthly summary" }),
        H.el("a", { class: "card-date", href: `#/trends/month/${s.id}`, text: period })),
      H.el("h2", { class: "sum-headline", text: s.headline }),
      segmented([["research", "Research"], ["industry", "Industry"]], "research", (k) => holder.replaceChildren(part(k)), "Summary part"),
      holder);
  }

  // ---------------------------------------------------------------- page
  function lastWidth() { const m = document.querySelector("#main"); return Math.min(1180, (m && m.clientWidth) || 900) - 48; }

  async function glance(S) {
    const date = S.dates[0];
    if (!date) return null;
    const j = await H.getDay(date);
    return H.el("section", { class: "card glance-card" },
      H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Latest digest" }),
        H.el("a", { class: "card-date", href: `#/day/${date}`, text: H.fmtLong(date) })), H.glanceList(j, date));
  }

  // Week in review: automatic lists (most-upvoted papers, most-covered stories), no trend claims.
  // opt (other tabs): base = the tab's data folder, link(date, id) = digest link, paperWord = the tab's word for papers
  async function weekCard(weeks, wantId, opt = {}) {
    if (!weeks.length) return null;
    const base = opt.base || "data/", link = opt.link || ((date, id) => `#/day/${date}/${id}`);
    // default: the latest complete week (the current one is still filling up); arrows reach the rest
    let i = wantId ? weeks.findIndex((w) => w.id === wantId) : weeks.findIndex((w) => w.complete);
    if (i < 0) i = 0;
    const card = H.el("section", { class: "card week-card", id: "week-review" });
    const draw = async () => {
      const w = weeks[i];
      let j;
      try { j = await H.getJSON(`${base}weeks/${w.id}.json`); } catch (e) { card.replaceChildren(H.el("p", { class: "note", text: "Could not load this week." })); return; }
      const nav = H.el("div", { class: "week-nav" },
        H.el("button", { class: "icon-btn small", "aria-label": "Previous week", disabled: i >= weeks.length - 1, onclick: () => { i++; draw(); }, text: "‹" }),
        H.el("span", { text: fmtRange(j.start, j.end) + (j.complete ? "" : " (so far)") }),
        H.el("button", { class: "icon-btn small", "aria-label": "Next week", disabled: i <= 0, onclick: () => { i--; draw(); }, text: "›" }));
      const papers = H.el("ol", { class: "rank" }, j.papers.map((p) => H.el("li", {},
        H.el("a", { href: p.featured ? link(p.featured, p.id) : `https://arxiv.org/abs/${p.id}`,
          target: p.featured ? null : "_blank", rel: p.featured ? null : "noopener", text: p.title }),
        H.el("span", { class: "rank-meta", text: `${p.hf} upvotes${p.featured ? " · in digest" : ""}` }))));
      const storiesL = H.el("ol", { class: "rank" }, j.stories.map((x) => H.el("li", {},
        x.covered ? H.el("a", { href: link(x.covered.slice(0, 10), x.covered), text: x.title }) : H.el("span", { text: x.title }),
        H.el("span", { class: "rank-meta", text: `${x.outlets} outlets${x.covered ? " · in digest" : ""}` }))));
      const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
      const items = j.items && H.el("ol", { class: "rank" }, j.items.map((x) => H.el("li", {},
        H.el("a", { href: link(x.date, x.id), text: x.title }),
        H.el("span", { class: "rank-meta", text: `${x.type === "news" ? "News" : (opt.paperWord || "Paper")} · ${day(x.date)}` }))));
      card.replaceChildren(
        H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Week in review" }), nav),
        H.el("div", { class: "week-cols" },
          items ? H.el("div", {}, H.el("h4", { text: "Featured this week" }), j.items.length ? items : H.el("p", { class: "note", text: "Nothing yet." }))
            : H.el("div", {}, H.el("h4", { text: "Most-upvoted papers" }), j.papers.length ? papers : H.el("p", { class: "note", text: "No data." })),
          H.el("div", {}, H.el("h4", { text: "Most-covered stories" }), j.stories.length ? storiesL : H.el("p", { class: "note", text: "No data." }))),
        H.el("p", { class: "week-foot", text: `Automatic lists from the week's ${j.digests} digests and their candidate pools: no trend claims. ` +
          `We featured ${j.featured.news} news stories and ${j.featured.papers} ${opt.paperWord === "Research" ? "research items" : (opt.paperWord || "papers").toLowerCase()}.` }));
    };
    await draw();
    return card;
  }

  function chartsCard(T, idx, S) {
    const months = T.series_months.map(mLabel);
    const dirs = T.directions, F = findings(T);
    const lead = H.el("p", { class: "finding" }), sub = H.el("p", { class: "viz-sub" }), body = H.el("div");
    const winTxt = span3(T.window);
    const set = (finding, how, ...nodes) => { lead.textContent = finding; sub.textContent = how; body.replaceChildren(...nodes); };
    const views = {
      board: () => set(F.board, `${dirs.length} research directions, measured over every new arXiv paper in our categories ` +
        `(${T.n_papers.toLocaleString()} in ${winTxt}). Each row's line is its share of new papers over 24 months; "All" lists the steady ones too.`, leaderboard(T)),
      growth: () => set(F.growth, "Each line is a direction's share of new papers divided by its share a year ago: above 1× it is gaining " +
        "ground relative to the whole field, below 1× losing it. Log scale, so 2× and 0.5× are equally far from 1×. Warm lines are rising directions, cool lines fading ones.",
        growthChart(T)),
      map: () => set(F.map, "Each dot is a direction: further right = a bigger share of new papers, higher up = faster growth over a year. " +
        "Coloured dots passed the noise filters (warm rising, cool fading). Select a dot for its page.", momentumMap(T)),
      heat: () => {
        const rows = GROUPS.flatMap((g) => dirs.filter((d) => d.group === g)).map((d) => ({ label: d.name, color: GVAR[d.group], values: d.series, href: dirHref(d.id) }));
        set(F.heat, "Every direction's monthly share of new papers against its own 24-month average: warm months ran above its usual level, cool months below.",
          heatGrid(rows, months, "Research directions by month"),
          table("Monthly share of new papers per direction", ["Direction", ...months], rows.map((r) => [r.label, ...r.values.map((v) => pct(v, 2))])));
      },
      terms: () => set(F.terms, `Title phrases whose use changed most in ${winTxt} against the 3 months before, used by many separate teams.`,
        termBars(T.terms_up, T.terms_down)),
      industry: () => {
        const N = T.news;
        if (!N) return set("", "Industry statistics are not available yet.");
        const ml = N.series_months.map(mLabel), cats = N.categories.slice().sort((a, b) => b.n - a.n);
        set(F.industry, `Share of reputable-outlet AI stories by category, per month (${N.stories.toLocaleString()} stories in ${winTxt}). ` +
          "The pool comes from fixed news searches, so read the movement, not the level.",
          linePanels(cats.map((c) => {
            const rel = c.share_prev ? c.share / c.share_prev - 1 : null, sig = significant(c.z_prev, rel);
            return { title: c.name, color: "--viz-news", values: N.category_series[c.name] || [], figure: pct(c.share, 1), unit: "of stories",
              delta: rel == null ? "" : `${pp(rel)} vs prev 3 mo · ${sig ? "significant" : "within noise"}`, up: (rel || 0) >= 0, quiet: !sig };
          }).filter((p) => p.values.length), ml),
          table("Share of stories per category", ["Category", ...ml], cats.map((c) => [c.name, ...(N.category_series[c.name] || []).map((v) => pct(v, 1))])));
      },
      featured: () => set("What our daily digests featured: a curated sample, not the field.",
        "Each dot is a paper or news story from the digests, by date and topic group; bigger dots had more Hugging Face upvotes. Select one to open it.",
        constellation(idx.items, S.groupOf)),
    };
    views.board();
    return H.el("section", { class: "card viz-card", id: "field-charts" },
      H.el("div", { class: "viz-head" }, H.el("h3", { text: "The field in numbers" }),
        segmented([["board", "Leaderboard"], ["growth", "Growth"], ["map", "Momentum map"], ["heat", "Heat map"], ["terms", "Terms"],
          ["industry", "Industry"], ["featured", "Our picks"]], "board", (k) => views[k](), "Chart")),
      lead, sub, body);
  }

  async function render(main, route, S) {
    lastArgs = [main, route, S];
    const idx = S.index, sums = (idx.summaries || []).filter((x) => x.kind === "monthly"), weeks = idx.weeks || [];
    let T = null;
    try { T = cache.trends || (cache.trends = await H.getJSON("data/trends.json")); } catch (e) { T = null; }
    const fresh = lastHash !== location.hash;   // a resize re-render keeps the scroll position
    lastHash = location.hash;
    if (route.kind === "direction" || route.kind === "field") return stockPage(main, route.kind, route.id, T).then(() => { if (fresh) window.scrollTo({ top: 0 }); });
    const out = [H.el("div", { class: "day-head" }, H.el("div", {},
      H.el("h1", { text: "Trends" }),
      H.el("div", { class: "day-meta", text: "Where AI research and the industry are heading, measured across the whole field and summarized monthly." })))];
    let focus = route.kind === "monthly" ? sums.find((x) => x.id === route.id) : null;
    if (route.kind === "monthly" && !focus) out.push(H.el("p", { class: "note", text: "That monthly summary does not exist (yet). Showing the latest." }));
    const first = focus || sums[0];
    if (first) out.push(summaryCard(await getSummary("monthly", first.id)));
    else out.push(H.el("p", { class: "note", text: "The first monthly summary is published on the 1st." }));
    const wk = await weekCard(weeks, route.kind === "weekly" ? route.id : null).catch(() => null);
    if (wk) out.push(wk);
    const daily = await getDaily().catch(() => null);
    if (daily && daily.groups) out.push(fieldTiles(daily));
    if (T && T.directions) out.push(chartsCard(T, idx, S));
    const g = await glance(S).catch(() => null);
    if (g) out.push(g);
    if (sums.length > 1) {
      const row = (x) => H.el("a", { class: "arch-row" + (first && first.id === x.id ? " on" : ""), href: `#/trends/month/${x.id}` },
        H.el("span", { class: "arch-when", text: monthLabel(x.id) }), H.el("span", { class: "arch-head", text: x.headline }));
      out.push(H.el("section", { class: "card archive" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "All monthly summaries" })),
        sums.map(row)));
    }
    main.replaceChildren(...out);
    if (!fresh) return;
    if (route.kind === "weekly" && wk) wk.scrollIntoView({ block: "start" }); else window.scrollTo({ top: 0 });
  }

  // Re-render charts only when the width really changes (a scrollbar appearing must not reset the open tab).
  let lastW = window.innerWidth;
  window.addEventListener("resize", () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => {
      if (Math.abs(window.innerWidth - lastW) < 40) return;
      lastW = window.innerWidth;
      if (lastArgs && /^#\/trends/.test(location.hash)) render(...lastArgs);
    }, 250);
  });

  window.AIUTrends = { init(helpers) { H = helpers; }, render, weekCard,
    kit: { svg, stockChart, segmented, miniLine, ends, longDate, startIndex, cum, wsum, pct, pp, times, STATUS, dirHref, fieldHref, lastWidth, table } };
})();
