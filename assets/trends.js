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
  let cache = { trends: null, sums: new Map() };
  let resizeT = null, lastArgs = null;

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
      s.append(svg("text", { x: 14, y: yy + 12, class: "row-label" }, fit(r.label, Math.floor((labelW - 20) / 6.4)),
        svg("title", {}, r.label)));
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

  // ---------------------------------------------------------------- direction movers (3 months vs previous 3)
  function directionBars(dirs, all) {
    const box = H.el("div", { class: "viz-plot" });
    const flagged = dirs.filter((d) => d.status !== "steady");
    const rows = (all ? dirs : flagged).slice().sort((a, b) => (b.rel_prev || 0) - (a.rel_prev || 0));
    if (!rows.length) { box.append(H.el("p", { class: "note", text: "No direction moved beyond noise level in this window." })); return box; }
    const W = Math.max(320, lastWidth()), labelW = Math.min(270, W * 0.42), rh = 24, valW = Math.min(175, W * 0.3);
    const maxAbs = Math.max(0.25, ...rows.map((d) => Math.abs(d.rel_prev || 0)));
    const half = (W - labelW - valW) / 2, mid = labelW + half;
    const Hh = rows.length * rh + 22;
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img",
      "aria-label": "Change in each direction's share of new papers, last 3 months vs the 3 before" });
    s.append(svg("line", { x1: mid, x2: mid, y1: 0, y2: Hh - 18, class: "zero" }));
    const tip = tooltip(box);
    rows.forEach((d, i) => {
      const yy = 2 + i * rh, r = d.rel_prev || 0, len = Math.max(3, (Math.abs(r) / maxAbs) * (half - 6));
      const col = d.status === "steady" ? "--viz-grid-strong" : r >= 0 ? "--div-warm" : "--div-cool";
      const d0 = r >= 0 ? `M${mid},${yy + 4} h${len - 4} a4,4 0 0 1 4,4 v6 a4,4 0 0 1 -4,4 h${-(len - 4)} z`
        : `M${mid},${yy + 4} h${-(len - 4)} a4,4 0 0 0 -4,4 v6 a4,4 0 0 0 4,4 h${len - 4} z`;
      const g = svg("g", { class: "bar-row", tabindex: 0 },
        svg("rect", { x: 0, y: yy, width: W, height: rh, class: "hit" }),
        svg("circle", { cx: 5, cy: yy + 11, r: 4, style: `fill: var(${GVAR[d.group] || "--viz-news"})` }),
        svg("text", { x: 14, y: yy + 15, class: "row-label" }, `${STATUS[d.status][0]} ${fit(d.name, Math.floor((labelW - 22) / 6.4))}`),
        svg("path", { d: d0, style: `fill: var(${col})` }),
        svg("text", { x: W - 2, y: yy + 15, class: "val", "text-anchor": "end" },
          W < 560 ? pp(d.rel_prev) : `${pct(d.share, 2)} · ${pp(d.rel_prev)} · yr ${pp(d.rel_year)}`));
      const show = (ev) => {
        const b = box.getBoundingClientRect(), cr = g.getBoundingClientRect();
        tip.show((ev && ev.clientX ? ev.clientX : cr.left + 40) - b.left, (ev && ev.clientY ? ev.clientY : cr.top) - b.top, [
          H.el("div", { class: "tip-head", text: `${d.name} · ${STATUS[d.status][1]}` }),
          tipRow(pct(d.share, 2), `of new papers (${d.n.toLocaleString()} papers, ${d.teams.toLocaleString()} teams)`),
          tipRow(pp(d.rel_prev), `vs previous 3 months (${pct(d.share_prev, 2)}; z ${d.z_prev})`),
          tipRow(pp(d.rel_year), `vs a year earlier (${d.share_year_ago == null ? "–" : pct(d.share_year_ago, 2)})`),
          tipRow(`${d.months_above}/3`, "months above the earlier level"),
          d.attention != null ? tipRow(pct(d.attention, 1), `of Hugging Face upvotes (was ${d.attention_prev == null ? "–" : pct(d.attention_prev, 1)})`) : null]);
      };
      g.addEventListener("pointermove", show);
      g.addEventListener("focus", () => show(null));
      g.addEventListener("pointerleave", () => tip.hide());
      g.addEventListener("blur", () => tip.hide());
      s.append(g);
    });
    s.append(svg("text", { x: mid, y: Hh - 4, class: "axis", "text-anchor": "middle" }, "change in share of new papers, last 3 months vs the 3 before"));
    box.append(s);
    return box;
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
  async function weekCard(weeks, wantId) {
    if (!weeks.length) return null;
    // default: the latest complete week (the current one is still filling up); arrows reach the rest
    let i = wantId ? weeks.findIndex((w) => w.id === wantId) : weeks.findIndex((w) => w.complete);
    if (i < 0) i = 0;
    const card = H.el("section", { class: "card week-card", id: "week-review" });
    const draw = async () => {
      const w = weeks[i];
      let j;
      try { j = await H.getJSON(`data/weeks/${w.id}.json`); } catch (e) { card.replaceChildren(H.el("p", { class: "note", text: "Could not load this week." })); return; }
      const nav = H.el("div", { class: "week-nav" },
        H.el("button", { class: "icon-btn small", "aria-label": "Previous week", disabled: i >= weeks.length - 1, onclick: () => { i++; draw(); }, text: "‹" }),
        H.el("span", { text: fmtRange(j.start, j.end) + (j.complete ? "" : " (so far)") }),
        H.el("button", { class: "icon-btn small", "aria-label": "Next week", disabled: i <= 0, onclick: () => { i--; draw(); }, text: "›" }));
      const papers = H.el("ol", { class: "rank" }, j.papers.map((p) => H.el("li", {},
        H.el("a", { href: p.featured ? `#/day/${p.featured}/${p.id}` : `https://arxiv.org/abs/${p.id}`,
          target: p.featured ? null : "_blank", rel: p.featured ? null : "noopener", text: p.title }),
        H.el("span", { class: "rank-meta", text: `${p.hf} upvotes${p.featured ? " · in digest" : ""}` }))));
      const storiesL = H.el("ol", { class: "rank" }, j.stories.map((x) => H.el("li", {},
        x.covered ? H.el("a", { href: `#/day/${x.covered.slice(0, 10)}/${x.covered}`, text: x.title }) : H.el("span", { text: x.title }),
        H.el("span", { class: "rank-meta", text: `${x.outlets} outlets${x.covered ? " · in digest" : ""}` }))));
      card.replaceChildren(
        H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Week in review" }), nav),
        H.el("div", { class: "week-cols" },
          H.el("div", {}, H.el("h4", { text: "Most-upvoted papers" }), j.papers.length ? papers : H.el("p", { class: "note", text: "No data." })),
          H.el("div", {}, H.el("h4", { text: "Most-covered stories" }), j.stories.length ? storiesL : H.el("p", { class: "note", text: "No data." }))),
        H.el("p", { class: "week-foot", text: `Automatic lists from the week's ${j.digests} digests and their candidate pools: no trend claims. ` +
          `We featured ${j.featured.papers} papers and ${j.featured.news} news stories.` }));
    };
    await draw();
    return card;
  }

  function chartsCard(T, idx, S) {
    const months = T.series_months.map(mLabel);
    const dirs = T.directions;
    const flagged = dirs.filter((d) => d.status !== "steady");
    const sub = H.el("p", { class: "viz-sub" }), body = H.el("div"), extra = H.el("div", { class: "viz-extra" });
    const winTxt = span3(T.window);
    let showAll = false;
    const views = {
      directions: () => {
        sub.textContent = `${dirs.length} research directions across all ${T.n_papers.toLocaleString()} new arXiv papers of ${winTxt}, ` +
          `compared with the 3 months before and a year earlier. Coloured bars passed the noise filters (significant, held for 2+ months, ` +
          `15+ teams, not contradicted a year on); grey bars are noise-level movement.`;
        const draw = () => body.replaceChildren(directionBars(dirs, showAll));
        extra.replaceChildren(segmented([["flagged", `Moving (${flagged.length})`], ["all", `All ${dirs.length}`]], showAll ? "all" : "flagged",
          (k) => { showAll = k === "all"; draw(); }, "Directions shown"));
        draw();
      },
      lines: () => {
        const pick = (flagged.length ? flagged : dirs.slice().sort((a, b) => Math.abs(b.rel_prev || 0) - Math.abs(a.rel_prev || 0))).slice(0, 9);
        sub.textContent = `Monthly share of new papers for the directions that are moving, over ${months.length} months; each panel has its own scale.`;
        body.replaceChildren(linePanels(pick.map((d) => ({ title: d.name, color: GVAR[d.group] || "--viz-news", values: d.series,
          figure: pct(d.share, 2), delta: `${STATUS[d.status][0]} ${pp(d.rel_prev)} vs prev 3 mo · ${pp(d.rel_year)} vs year ago`,
          up: (d.rel_prev || 0) >= 0 })), months),
          table("Monthly share of new papers per direction", ["Direction", ...months], pick.map((d) => [d.name, ...d.series.map((v) => pct(v, 2))])));
        extra.replaceChildren();
      },
      heat: () => {
        sub.textContent = "Every direction's monthly share of new papers against its own average: warm months ran above its usual level, cool months below.";
        const rows = GROUPS.flatMap((g) => dirs.filter((d) => d.group === g)).map((d) => ({ label: d.name, color: GVAR[d.group], values: d.series }));
        body.replaceChildren(heatGrid(rows, months, "Research directions by month"),
          table("Monthly share of new papers per direction", ["Direction", ...months], rows.map((r) => [r.label, ...r.values.map((v) => pct(v, 2))])));
        extra.replaceChildren();
      },
      terms: () => {
        sub.textContent = `Title words and phrases whose use changed most in ${winTxt} against the 3 months before, used by many separate teams.`;
        body.replaceChildren(termBars(T.terms_up, T.terms_down));
        extra.replaceChildren();
      },
      industry: () => {
        const N = T.news;
        if (!N) { body.replaceChildren(H.el("p", { class: "note", text: "Industry statistics are not available yet." })); extra.replaceChildren(); return; }
        const ml = N.series_months.map(mLabel);
        sub.textContent = `Share of reputable-outlet AI stories by category, per month (${N.stories.toLocaleString()} stories in ${winTxt}). ` +
          "The pool comes from fixed news searches, so read the movement, not the level.";
        const cats = N.categories.slice().sort((a, b) => b.n - a.n);
        body.replaceChildren(linePanels(cats.map((c) => {
          const rel = c.share_prev ? c.share / c.share_prev - 1 : null, sig = significant(c.z_prev, rel);
          return { title: c.name, color: "--viz-news", values: N.category_series[c.name] || [], figure: pct(c.share, 1), unit: "of stories",
            delta: rel == null ? "" : `${pp(rel)} vs prev 3 mo · ${sig ? "significant" : "within noise"}`, up: (rel || 0) >= 0, quiet: !sig };
        }).filter((p) => p.values.length), ml),
          table("Share of stories per category", ["Category", ...ml], cats.map((c) => [c.name, ...(N.category_series[c.name] || []).map((v) => pct(v, 1))])));
        extra.replaceChildren();
      },
      featured: () => {
        sub.textContent = "What our daily digests featured, by date and topic group (our picks, not the field). Select a dot to open it.";
        body.replaceChildren(constellation(idx.items, S.groupOf));
        extra.replaceChildren();
      },
    };
    views.directions();
    return H.el("section", { class: "card viz-card", id: "field-charts" },
      H.el("div", { class: "viz-head" }, H.el("h3", { text: "The field in numbers" }),
        segmented([["directions", "Directions"], ["lines", "Over time"], ["heat", "Heat map"], ["terms", "Terms"],
          ["industry", "Industry"], ["featured", "Our picks"]], "directions", (k) => views[k](), "Chart")),
      H.el("div", { class: "viz-head sub" }, sub, extra), body);
  }

  async function render(main, route, S) {
    lastArgs = [main, route, S];
    const idx = S.index, sums = (idx.summaries || []).filter((x) => x.kind === "monthly"), weeks = idx.weeks || [];
    let T = null;
    try { T = cache.trends || (cache.trends = await H.getJSON("data/trends.json")); } catch (e) { T = null; }
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
    if (route.kind === "weekly" && wk) wk.scrollIntoView({ block: "start" }); else window.scrollTo({ top: 0 });
  }

  window.addEventListener("resize", () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => { if (lastArgs && /^#\/trends/.test(location.hash)) render(...lastArgs); }, 250);
  });

  window.AIUTrends = { init(helpers) { H = helpers; }, render };
})();
