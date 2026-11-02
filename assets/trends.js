/* AI Updated — Trends dashboard (#/trends). Weekly/monthly syntheses + field-wide arXiv charts.
   Data: data/index.json (summaries list, items), data/summaries/<kind>/<id>.json, data/trends.json.
   Text is always inserted with textContent; charts are inline SVG whose colors are CSS variables, so the
   light/dark theme switch needs no re-render. */
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
  const weekLabel = (w) => H.dObj(w.start).toLocaleDateString("en-US", { month: "short", day: "numeric" });
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

  // ---------------------------------------------------------------- chart 1: topic-group small multiples
  // One panel per group (each with its own y-range, labelled), so week-to-week movement is visible even when
  // the overall mix barely changes. Headline number = latest week; delta = vs the average of the 4 weeks before.
  function groupPanels(weeks, focusWeek) {
    const grid = H.el("div", { class: "sm-grid" });
    const n = weeks.length, fi = Math.max(0, weeks.findIndex((w) => w.week === focusWeek));
    const at = focusWeek && weeks.some((w) => w.week === focusWeek) ? fi : n - 1;
    for (const g of GROUPS) {
      const vals = weeks.map((w) => w.groups[g] || 0);
      const prev = vals.slice(Math.max(0, at - 4), at);
      const avg = prev.length ? prev.reduce((x, y) => x + y, 0) / prev.length : null;
      const d = avg == null ? null : vals[at] - avg;
      const panel = H.el("div", { class: "sm-panel" });
      panel.append(H.el("div", { class: "sm-head" }, H.el("i", { style: `background: var(${GVAR[g]})` }), H.el("span", { text: g })),
        H.el("div", { class: "sm-figure" }, H.el("strong", { text: pct(vals[at]) }),
          d == null ? null : H.el("span", { class: "sm-delta " + (d >= 0 ? "up" : "down"),
            text: `${d >= 0 ? "▲" : "▼"} ${Math.abs(d * 100).toFixed(1)} pts vs prior 4 wks` })));
      const W = 260, Hh = 92, pl = 34, pr = 8, pt = 8, pb = 18;
      const lo = Math.min(...vals), hi = Math.max(...vals), padv = Math.max(0.004, (hi - lo) * 0.15);
      const y0 = lo - padv, y1 = hi + padv;
      const x = (i) => pl + (n === 1 ? (W - pl - pr) / 2 : (i * (W - pl - pr)) / (n - 1));
      const y = (v) => pt + (1 - (v - y0) / (y1 - y0)) * (Hh - pt - pb);
      const line = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
      const area = `${line} L${x(n - 1)},${Hh - pb} L${x(0)},${Hh - pb} Z`;
      const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", class: "sm-svg", role: "img",
        "aria-label": `${g}: share of new paper titles by week, from ${pct(vals[0])} to ${pct(vals[n - 1])}` },
        svg("line", { x1: pl, x2: W - pr, y1: Hh - pb, y2: Hh - pb, class: "zero" }),
        svg("text", { x: pl - 5, y: y(hi) + 4, class: "axis", "text-anchor": "end" }, pct(hi)),
        svg("text", { x: pl - 5, y: y(lo) + 4, class: "axis", "text-anchor": "end" }, pct(lo)),
        svg("text", { x: x(0), y: Hh - 4, class: "axis", "text-anchor": "start" }, weekLabel(weeks[0])),
        svg("text", { x: x(n - 1), y: Hh - 4, class: "axis", "text-anchor": "end" }, weekLabel(weeks[n - 1])),
        svg("path", { d: area, class: "sm-area", style: `fill: var(${GVAR[g]})` }),
        svg("path", { d: line, class: "sm-line", style: `stroke: var(${GVAR[g]})` }),
        svg("circle", { cx: x(at), cy: y(vals[at]), r: 4, class: "sm-dot", style: `fill: var(${GVAR[g]})` }));
      const cross = svg("line", { y1: pt, y2: Hh - pb, class: "crosshair", visibility: "hidden" });
      s.append(cross);
      const tip = tooltip(panel);
      s.addEventListener("pointermove", (ev) => {
        const r = s.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
        const i = Math.max(0, Math.min(n - 1, Math.round(((px - pl) / (W - pl - pr)) * (n - 1))));
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
        const b = panel.getBoundingClientRect();
        tip.show(ev.clientX - b.left, ev.clientY - b.top, [
          H.el("div", { class: "tip-head", text: `Week of ${weekLabel(weeks[i])} · ${weeks[i].n_papers.toLocaleString()} papers` }),
          tipRow(pct(vals[i]), g, GVAR[g])]);
      });
      s.addEventListener("pointerleave", () => { tip.hide(); cross.setAttribute("visibility", "hidden"); });
      panel.append(s);
      grid.append(panel);
    }
    return grid;
  }

  // ---------------------------------------------------------------- chart 2: topic heat map
  function heatmap(weeks, tagGroups, focusWeek) {
    const box = H.el("div", { class: "viz-plot" });
    const W = Math.max(320, lastWidth()), labelW = Math.min(170, W * 0.36), n = weeks.length;
    const rows = GROUPS.flatMap((g) => (tagGroups[g] || []).map((t) => ({ g, t })));
    const cw = Math.max(10, (W - labelW - 8) / Math.max(1, n)), ch = 18, gap = 2, padT = 22;
    const Hh = padT + rows.length * ch + 8;
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img",
      "aria-label": "Topic heat map: each tag's weekly share of new papers versus its average" });
    const step = Math.ceil(n / Math.max(1, Math.floor((W - labelW) / 56)));
    weeks.forEach((w, i) => {
      if (i % step && i !== n - 1) return;
      s.append(svg("text", { x: labelW + i * cw + cw / 2, y: 13, class: "axis", "text-anchor": "middle" }, weekLabel(w)));
    });
    const tip = tooltip(box);
    rows.forEach((r, ri) => {
      const yy = padT + ri * ch;
      const vals = weeks.map((w) => w.tags[r.t] || 0);
      const mean = vals.reduce((a, b) => a + b, 0) / Math.max(1, n);
      s.append(svg("rect", { x: 0, y: yy + 5, width: 8, height: 8, rx: 2, style: `fill: var(${GVAR[r.g]})` }));
      s.append(svg("text", { x: 14, y: yy + 13, class: "row-label" }, r.t));
      vals.forEach((v, i) => {
        const dev = mean ? v / mean - 1 : 0, k = Math.min(1, Math.abs(dev) / 0.4);
        const fill = `color-mix(in oklab, var(${dev >= 0 ? "--div-warm" : "--div-cool"}) ${Math.round(k * 100)}%, var(--div-mid))`;
        const cell = svg("rect", { x: labelW + i * cw + gap / 2, y: yy + gap / 2, width: cw - gap, height: ch - gap, rx: 3,
          class: "cell" + (weeks[i].week === focusWeek ? " focus" : ""), style: `fill: ${fill}`, tabindex: 0,
          "aria-label": `${r.t}, week of ${weekLabel(weeks[i])}: ${pct(v)} of titles, ${signed(dev)} vs average` });
        const show = (ev) => {
          const b = box.getBoundingClientRect(), cr = cell.getBoundingClientRect();
          tip.show((ev && ev.clientX ? ev.clientX : cr.right) - b.left, (ev && ev.clientY ? ev.clientY : cr.top) - b.top, [
            H.el("div", { class: "tip-head", text: `${r.t} · week of ${weekLabel(weeks[i])}` }),
            tipRow(pct(v), "of new paper titles"), tipRow(signed(dev), `vs its ${n}-week average (${pct(mean)})`)]);
        };
        cell.addEventListener("pointermove", show);
        cell.addEventListener("focus", () => show(null));
        cell.addEventListener("pointerleave", () => tip.hide());
        cell.addEventListener("blur", () => tip.hide());
        s.append(cell);
      });
    });
    box.append(s);
    const scale = H.el("div", { class: "div-scale" }, H.el("span", { text: "cooler than usual" }),
      H.el("i", { class: "div-bar" }), H.el("span", { text: "hotter than usual" }));
    return [box, scale];
  }

  // ---------------------------------------------------------------- chart 3: rising / fading terms
  function movers(period) {
    const box = H.el("div", { class: "viz-plot movers" });
    const groups = [["Rising", (period.rising || []), true], ["Fading", (period.fading || []), false]].filter((g) => g[1].length);
    if (!groups.length) { box.append(H.el("p", { class: "note", text: "Not enough baseline data for this period yet." })); return box; }
    const W = Math.max(320, lastWidth()), labelW = Math.min(200, W * 0.4), rh = 22, headH = 22, valW = 92;
    const change = (m) => (m.now + 2) / (m.base + 2) - 1;          // smoothed relative change
    const maxAbs = Math.max(0.5, ...groups.flatMap((g) => g[1].map((m) => Math.abs(change(m)))));
    const span = W - labelW - valW;
    const Hh = groups.reduce((h, g) => h + headH + g[1].length * rh + 8, 0);
    const s = svg("svg", { viewBox: `0 0 ${W} ${Hh}`, width: "100%", height: Hh, role: "img",
      "aria-label": "Title terms rising and fading versus the baseline period" });
    let yy = 0;
    for (const [name, rows, up] of groups) {
      s.append(svg("text", { x: 0, y: yy + 14, class: "group-label" }, `${up ? "▲" : "▼"} ${name}`));
      s.append(svg("line", { x1: labelW, x2: labelW, y1: yy + headH - 2, y2: yy + headH + rows.length * rh - 4, class: "zero" }));
      yy += headH;
      for (const m of rows) {
        const len = Math.max(4, (Math.abs(change(m)) / maxAbs) * span);
        // 4px rounded data end, square at the baseline; 14px thick
        const d = `M${labelW},${yy + 2} h${len - 4} a4,4 0 0 1 4,4 v6 a4,4 0 0 1 -4,4 h${-(len - 4)} z`;
        s.append(svg("text", { x: labelW - 8, y: yy + 13, class: "row-label", "text-anchor": "end" }, m.term));
        s.append(svg("path", { d, style: `fill: var(${up ? "--div-warm" : "--div-cool"})` },
          svg("title", {}, `${m.term}: ${m.now} papers vs ${m.base} expected (${signed(change(m))})`)));
        s.append(svg("text", { x: labelW + len + 6, y: yy + 13, class: "val" }, `${signed(change(m))} · ${m.now} vs ${m.base}`));
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
      if (tok === "arXiv stats") return "Field-wide arXiv statistics (charts below)";
      if (/^S\d+$/.test(tok)) { const src = s.sources.find((x) => x.id === tok); return src ? src.name : tok; }
      const r = s.refs[tok];
      return r ? `${r.type === "news" ? "News" : "Paper"}${r.date ? "" : " (not featured)"}: ${r.title}` : tok;
    };
    const marker = (tok) => {
      if (tok === "arXiv stats") return H.el("a", { class: "ref stats", href: "javascript:void 0", title: label(tok),
        onclick: (e) => { e.preventDefault(); const c = document.getElementById("field-charts"); if (c) c.scrollIntoView({ behavior: "smooth" }); },
        text: "arXiv" });
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

  function summaryCard(s, big) {
    const L = refLinker(s);
    const part = (key, title) => {
      L.reset();
      const p = s[key];
      const themes = p.themes.map((t) => H.el("div", { class: "theme" }, H.el("h4", { text: t.title }),
        t.body.split(/\n\s*\n/).map((para) => H.el("p", {}, L.rich(para.trim())))));
      const ev = L.evidence();
      return H.el("section", { class: `sum-part ${key}` },
        H.el("h3", { text: title }),
        H.el("div", { class: "trend-chips" }, trendChips(p.heating, true), trendChips(p.cooling, false)),
        themes,
        ev.length ? H.el("details", { class: "evidence" }, H.el("summary", { text: `Evidence (${ev.length})` }), H.el("ol", {}, ev)) : null);
    };
    const kindLabel = s.kind === "weekly" ? `Week of ${fmtRange(s.period.start, s.period.end)}` : monthLabel(s.id);
    return H.el("article", { class: "card summary" + (big ? " big" : ""), id: `sum-${s.kind}-${s.id}` },
      H.el("div", { class: "card-top" },
        H.el("span", { class: `kind ${s.kind}`, text: s.kind === "weekly" ? "Weekly summary" : "Monthly summary" }),
        H.el("a", { class: "card-date", href: `#/trends/${s.kind === "weekly" ? "week" : "month"}/${s.id}`, text: kindLabel })),
      H.el("h2", { class: "sum-headline", text: s.headline }),
      H.el("div", { class: "sum-grid" }, part("research", "Where research is going"), part("industry", "Where the industry is going")));
  }

  // ---------------------------------------------------------------- page
  function lastWidth() { const m = document.querySelector("#main"); return Math.min(1180, (m && m.clientWidth) || 900) - 56; }

  async function glance(S) {
    const date = S.dates[0];
    if (!date) return null;
    const j = await H.getDay(date);
    const list = H.glanceList(j, date);
    return H.el("section", { class: "card glance-card" },
      H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Day at a glance" }),
        H.el("a", { class: "card-date", href: `#/day/${date}`, text: H.fmtLong(date) })), list);
  }

  async function render(main, route, S) {
    lastArgs = [main, route, S];
    const idx = S.index, sums = idx.summaries || [];
    const weekly = sums.filter((x) => x.kind === "weekly"), monthly = sums.filter((x) => x.kind === "monthly");
    let trends = null;
    try { trends = cache.trends || (cache.trends = await H.getJSON("data/trends.json")); } catch (e) { trends = null; }
    const out = [H.el("div", { class: "day-head" }, H.el("div", {},
      H.el("h1", { text: "Trends" }),
      H.el("div", { class: "day-meta", text: "Where AI research and the industry are heading: weekly and monthly syntheses of the digest, checked against every new arXiv paper." })))];

    // the summary in focus
    let focus = null;
    if (route.kind) focus = sums.find((x) => x.kind === route.kind && x.id === route.id);
    if (route.kind && !focus) out.push(H.el("p", { class: "note", text: "That summary does not exist (yet). Showing the latest." }));
    const g = await glance(S).catch(() => null);
    if (focus) {
      out.push(summaryCard(await getSummary(focus.kind, focus.id), true));
      if (g) out.push(g);
    } else {
      if (g) out.push(g);
      if (weekly[0]) out.push(H.el("h2", { class: "section-title", text: "This week" }), summaryCard(await getSummary("weekly", weekly[0].id), true));
      if (monthly[0]) out.push(H.el("h2", { class: "section-title", text: "This month" }), summaryCard(await getSummary("monthly", monthly[0].id), true));
      if (!weekly.length && !monthly.length) out.push(H.el("p", { class: "note", text: "The first weekly summary is published on Sunday." }));
    }

    // field-wide charts
    const weeks = trends ? trends.weeks.slice(-16) : [];
    const focusWeek = focus && focus.kind === "weekly" ? focus.id : (weekly[0] && weekly[0].id);
    const charts = H.el("section", { id: "field-charts" });
    out.push(H.el("h2", { class: "section-title", text: "The field in numbers" }), charts);
    if (weeks.length) {
      const periods = [...trends.weeks.slice().reverse().map((w) => ({ key: `w:${w.week}`, label: `Week of ${weekLabel(w)}`, data: w })),
        ...trends.months.slice().reverse().map((m) => ({ key: `m:${m.month}`, label: monthLabel(m.month), data: m }))]
        .filter((p) => (p.data.rising || []).length);
      const want = focus ? (focus.kind === "weekly" ? `w:${focus.id}` : `m:${focus.id}`) : (periods[0] && periods[0].key);
      let cur = periods.find((p) => p.key === want) || periods[0];
      const moverBox = H.el("div");
      const drawMovers = () => moverBox.replaceChildren(cur ? movers(cur.data) : H.el("p", { class: "note", text: "Not enough data yet." }));
      const sel = H.el("select", { class: "period-select", "aria-label": "Period for rising and fading terms",
        onchange: (e) => { cur = periods.find((p) => p.key === e.target.value); drawMovers(); } },
        periods.map((p) => H.el("option", { value: p.key, selected: cur && p.key === cur.key, text: p.label })));
      charts.append(
        H.el("div", { class: "card viz-card" },
          H.el("h3", { text: "What new papers are about" }),
          H.el("p", { class: "viz-sub", text: `Share of all new arXiv papers in our categories whose titles touch each topic group, by week (${weeks[weeks.length - 1].n_papers.toLocaleString()} papers in the latest week). Titles are matched by keywords and can count toward several groups, so read the movement, not the exact level. Each panel has its own scale.` }),
          groupPanels(weeks, focusWeek),
          table("Share of new paper titles per topic group", ["Week", ...GROUPS], weeks.map((w) => [weekLabel(w), ...GROUPS.map((x) => pct(w.groups[x] || 0))]))),
        H.el("div", { class: "card viz-card" },
          H.el("h3", { text: "Topic heat" }),
          H.el("p", { class: "viz-sub", text: "Each tag's weekly share of new paper titles compared with its own average over these weeks: warm cells are weeks it ran hot, cool cells weeks it cooled off." }),
          heatmap(weeks, idx.tag_groups, focusWeek),
          table("Weekly share of new paper titles per tag", ["Tag", ...weeks.map(weekLabel)],
            GROUPS.flatMap((x) => idx.tag_groups[x] || []).map((t) => [t, ...weeks.map((w) => pct(w.tags[t] || 0))]))),
        H.el("div", { class: "card viz-card" },
          H.el("div", { class: "viz-head" }, H.el("h3", { text: "Rising and fading terms" }), periods.length ? sel : null),
          H.el("p", { class: "viz-sub", text: "Title words and phrases whose use changed most against the previous four weeks (or the previous month), with the number of papers using them." }),
          moverBox));
      drawMovers();
    } else {
      charts.append(H.el("p", { class: "note", text: "Field statistics appear after the first weekly run." }));
    }
    charts.append(H.el("div", { class: "card viz-card" },
      H.el("h3", { text: "Everything we featured" }),
      H.el("p", { class: "viz-sub", text: "Each dot is a paper or news story from the daily digests, placed by date and topic group; bigger dots had more Hugging Face upvotes. Select one to open it." }),
      constellation(idx.items, S.groupOf)));

    // archive
    if (sums.length) {
      const row = (x) => H.el("a", { class: "arch-row" + (focus && focus.id === x.id && focus.kind === x.kind ? " on" : ""),
        href: `#/trends/${x.kind === "weekly" ? "week" : "month"}/${x.id}` },
        H.el("span", { class: "arch-when", text: x.kind === "weekly" ? fmtRange(x.start, x.end) : monthLabel(x.id) }),
        H.el("span", { class: "arch-head", text: x.headline }),
        H.el("span", { class: "trend-chips" }, trendChips(x.heating.map((l) => ({ label: l })), true), trendChips(x.cooling.map((l) => ({ label: l })), false)));
      out.push(H.el("h2", { class: "section-title", text: "All summaries" }),
        H.el("div", { class: "card archive" },
          monthly.length ? [H.el("h3", { text: "Monthly" }), monthly.map(row)] : null,
          weekly.length ? [H.el("h3", { text: "Weekly" }), weekly.map(row)] : null));
    }
    main.replaceChildren(...out);
    window.scrollTo({ top: 0 });
  }

  window.addEventListener("resize", () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => { if (lastArgs && /^#\/trends/.test(location.hash)) render(...lastArgs); }, 250);
  });

  window.AIUTrends = { init(helpers) { H = helpers; }, render };
})();
