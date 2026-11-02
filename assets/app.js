/* AI Updated — static front end. Data: data/index.json + data/days/<date>.json.
   All content is rendered with textContent (never innerHTML) so digest text can't inject markup. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const S = {
    index: null, dayFiles: new Map(), groupOf: {}, dates: [], dateSet: new Set(),
    calMonth: null, calMode: "day", rangeStart: null,
    f: { type: "all", tags: new Set(), cats: new Set(), q: "", from: null, to: null },
  };

  // ---------- helpers
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(n.dataset, v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) if (c != null && c !== false) n.append(c instanceof Node ? c : document.createTextNode(c));
    return n;
  }
  const dObj = (iso) => new Date(iso + "T12:00:00");
  const fmtLong = (iso) => dObj(iso).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  const fmtShort = (iso) => dObj(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const safeUrl = (u) => (typeof u === "string" && /^https:\/\//.test(u) ? u : null);

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  }
  async function getDay(date) {
    if (!S.dayFiles.has(date)) S.dayFiles.set(date, getJSON(`data/days/${date}.json`));
    return S.dayFiles.get(date);
  }

  // ---------- routing
  function filtersActive() {
    const f = S.f;
    return f.type !== "all" || f.tags.size || f.cats.size || f.q || f.from;
  }
  function browseHash() {
    const f = S.f, p = new URLSearchParams();
    if (f.type !== "all") p.set("type", f.type);
    if (f.tags.size) p.set("tags", [...f.tags].join("|"));
    if (f.cats.size) p.set("cats", [...f.cats].join("|"));
    if (f.q) p.set("q", f.q);
    if (f.from) p.set("from", f.from);
    if (f.to) p.set("to", f.to);
    return "#/browse" + (p.toString() ? "?" + p : "");
  }
  function applyFilters() { location.hash = filtersActive() ? browseHash() : "#/"; }

  function parseRoute() {
    const h = location.hash.replace(/^#/, "");
    const m = h.match(/^\/day\/(\d{4}-\d{2}-\d{2})/);
    if (m) return { view: "day", date: m[1] };
    if (h.startsWith("/browse")) {
      const p = new URLSearchParams(h.split("?")[1] || "");
      S.f.type = ["paper", "news"].includes(p.get("type")) ? p.get("type") : "all";
      S.f.tags = new Set((p.get("tags") || "").split("|").filter(Boolean));
      S.f.cats = new Set((p.get("cats") || "").split("|").filter(Boolean));
      S.f.q = p.get("q") || "";
      S.f.from = p.get("from"); S.f.to = p.get("to") || p.get("from");
      return { view: "browse" };
    }
    return { view: "day", date: S.dates[0] };
  }

  async function route() {
    const r = parseRoute();
    if (r.view === "day") {
      S.f = { type: "all", tags: new Set(), cats: new Set(), q: "", from: null, to: null };
      if (r.date) S.calMonth = new Date(dObj(r.date).getFullYear(), dObj(r.date).getMonth(), 1);
    }
    syncSidebar(r);
    const main = $("#main");
    main.replaceChildren(el("div", { class: "loading", text: "Loading…" }));
    try {
      if (r.view === "day") await renderDay(r.date);
      else renderBrowse();
    } catch (e) {
      main.replaceChildren(el("div", { class: "empty", text: `Could not load this view (${e.message}).` }));
    }
    if (window.innerWidth <= 900) $("#sidebar").classList.remove("open");
  }

  // ---------- sidebar
  function syncSidebar(r) {
    S.current = r;
    $("#search").value = S.f.q;
    for (const b of $("#typeSeg").children) b.classList.toggle("on", b.dataset.type === S.f.type);
    renderCalendar();
    renderTags();
  }

  function renderCalendar() {
    const box = $("#calendar");
    const m = S.calMonth;
    const first = new Date(m.getFullYear(), m.getMonth(), 1);
    const nDays = new Date(m.getFullYear(), m.getMonth() + 1, 0).getDate();
    const minD = S.dates.length ? dObj(S.dates[S.dates.length - 1]) : new Date();
    const maxD = S.dates.length ? dObj(S.dates[0]) : new Date();
    const prevOk = new Date(m.getFullYear(), m.getMonth(), 0) >= new Date(minD.getFullYear(), minD.getMonth(), 1);
    const nextOk = new Date(m.getFullYear(), m.getMonth() + 1, 1) <= maxD;
    const grid = el("div", { class: "cal-grid" }, ..."SMTWTFS".split("").map((c) => el("div", { class: "cal-dow", text: c })));
    for (let i = 0; i < first.getDay(); i++) grid.append(el("div"));
    const today = isoOf(new Date());
    const sel = S.current && S.current.view === "day" ? S.current.date : null;
    const from = S.rangeStart || S.f.from, to = S.rangeStart ? S.rangeStart : S.f.to;
    for (let d = 1; d <= nDays; d++) {
      const iso = isoOf(new Date(m.getFullYear(), m.getMonth(), d));
      const has = S.dateSet.has(iso);
      const ranged = S.calMode === "range";
      const cls = ["cal-day", has && "has", ranged && "pickable", iso === today && "today",
        (iso === sel || iso === from || iso === to) && "sel",
        from && to && iso > from && iso < to && "inrange"].filter(Boolean).join(" ");
      grid.append(el("button", {
        class: cls, text: String(d), disabled: !has && !ranged, "aria-label": fmtLong(iso) + (has ? " (digest available)" : ""),
        onclick: () => pickDate(iso),
      }));
    }
    const head = el("div", { class: "cal-head" },
      el("button", { class: "cal-nav", "aria-label": "Previous month", disabled: !prevOk, onclick: () => shiftMonth(-1), text: "‹" }),
      el("strong", { text: m.toLocaleDateString("en-US", { month: "long", year: "numeric" }) }),
      el("button", { class: "cal-nav", "aria-label": "Next month", disabled: !nextOk, onclick: () => shiftMonth(1), text: "›" }));
    box.replaceChildren(head, grid);
    $("#calHint").textContent = S.calMode === "range"
      ? (S.rangeStart ? "Now pick the end date." : (S.f.from ? `Showing ${fmtShort(S.f.from)} – ${fmtShort(S.f.to)}` : "Pick a start date."))
      : "Dots mark days with a digest.";
  }
  function shiftMonth(k) { S.calMonth = new Date(S.calMonth.getFullYear(), S.calMonth.getMonth() + k, 1); renderCalendar(); }

  function pickDate(iso) {
    if (S.calMode === "day") { location.hash = `#/day/${iso}`; return; }
    if (!S.rangeStart) { S.rangeStart = iso; renderCalendar(); return; }
    const [a, b] = [S.rangeStart, iso].sort();
    S.rangeStart = null; S.f.from = a; S.f.to = b;
    applyFilters();
  }

  function renderTags() {
    const ix = S.index;
    const groups = Object.entries(ix.tag_groups).map(([g, tags]) =>
      el("div", { class: "tag-group" }, el("p", { class: "tag-group-name", text: g }),
        el("div", { class: "chips" }, tags.map((t) => chip(t, ix.tag_counts[t] || 0, S.f.tags, g)))));
    $("#tags").replaceChildren(...groups);
    $("#cats").replaceChildren(...ix.news_categories.map((c) => chip(c, ix.category_counts[c] || 0, S.f.cats, "news")));
  }
  function chip(label, n, set, group) {
    return el("button", {
      class: "chip" + (set.has(label) ? " on" : ""), dataset: { g: group }, disabled: !n && !set.has(label),
      "aria-pressed": set.has(label) ? "true" : "false",
      onclick: () => { set.has(label) ? set.delete(label) : set.add(label); applyFilters(); },
    }, label, el("span", { class: "n", text: String(n) }));
  }

  // ---------- cards
  function tagChips(item, isNews) {
    if (isNews) return el("div", { class: "chips" }, el("button", { class: "chip", dataset: { g: "news" },
      onclick: () => { S.f = blankFilters(); S.f.cats.add(item.category); applyFilters(); } }, item.category));
    return el("div", { class: "chips" }, (item.tags || []).map((t) => el("button", {
      class: "chip" + (t === item.primary_tag ? " on" : ""), dataset: { g: S.groupOf[t] || "" },
      onclick: () => { S.f = blankFilters(); S.f.tags.add(t); applyFilters(); },
    }, t)));
  }
  const blankFilters = () => ({ type: "all", tags: new Set(), cats: new Set(), q: "", from: null, to: null });

  function byline(item, isNews) {
    if (isNews) return (item.sources || []).map((s) => s.name).join(" · ");
    const a = item.authors || [];
    let s = a.slice(0, 4).join(", ") + (a.length > 4 ? ` +${a.length - 4}` : "");
    if (item.affiliations && item.affiliations.length) s += " — " + item.affiliations.slice(0, 4).join(", ");
    return s;
  }

  function fullCard(item, isNews, date) {
    const href = isNews ? safeUrl((item.sources || [])[0] && item.sources[0].url) : safeUrl(item.links && item.links.arxiv);
    const kindText = isNews ? `News · ${item.category}` : `Paper · ${item.primary_tag}`;
    const when = isNews && item.published ? fmtShort(item.published.slice(0, 10))
      : (!isNews && item.announced ? `arXiv ${fmtShort(item.announced.slice(0, 10))}` : fmtShort(date));
    const body = el("div", { class: "body" }, (item.sections || []).map((s) => [
      el("h4", { text: s.heading }),
      ...String(s.body || "").split(/\n\s*\n/).map((p) => el("p", { text: p.trim() })),
    ]));
    const foot = el("div", { class: "card-foot" });
    if (isNews) {
      foot.append(el("strong", { text: "Sources:" }));
      for (const s of item.sources || []) { const u = safeUrl(s.url); if (u) foot.append(el("a", { href: u, target: "_blank", rel: "noopener", text: s.name })); }
    } else {
      const L = item.links || {};
      const links = [["arXiv", L.arxiv], ["alphaXiv", L.alphaxiv], ["PDF", L.arxiv && L.arxiv.replace("/abs/", "/pdf/")], ["Code", L.code], ["Project", L.project]];
      for (const [n, u] of links) if (safeUrl(u)) foot.append(el("a", { href: u, target: "_blank", rel: "noopener", text: n }));
    }
    if (item.why_selected) foot.append(el("span", { class: "why", text: "Why it's here: " + item.why_selected }));
    const toggle = el("button", { class: "toggle", text: "Collapse" });
    toggle.addEventListener("click", () => {
      const hidden = body.hidden = !body.hidden;
      toggle.textContent = hidden ? "Read summary" : "Collapse";
    });
    foot.append(toggle);
    return el("article", { class: `card ${isNews ? "news" : "paper"}`, id: `item-${item.id}`, dataset: { g: isNews ? "news" : S.groupOf[item.primary_tag] || "" } },
      el("div", { class: "card-top" }, el("span", { class: `kind ${isNews ? "news" : "paper"}`, text: kindText }), el("span", { class: "card-date", text: when })),
      el("h3", {}, href ? el("a", { href, target: "_blank", rel: "noopener", text: item.title }) : item.title),
      el("p", { class: "byline", text: byline(item, isNews) }),
      tagChips(item, isNews),
      el("p", { class: "tldr", text: item.tldr }),
      body, foot);
  }

  function compactCard(it) {
    const isNews = it.type === "news";
    const card = el("article", { class: `card compact ${isNews ? "news" : "paper"}`, dataset: { g: isNews ? "news" : S.groupOf[it.primary_tag] || "" } });
    const open = async () => {
      try {
        const day = await getDay(it.date);
        const full = (isNews ? day.news : day.papers).find((x) => x.id === it.id);
        if (full) card.replaceWith(fullCard(full, isNews, it.date));
      } catch (e) { btn.textContent = "Could not load"; }
    };
    const btn = el("button", { class: "toggle", text: "Read full summary", onclick: open });
    card.append(
      el("div", { class: "card-top" }, el("span", { class: `kind ${isNews ? "news" : "paper"}`, text: isNews ? `News · ${it.category}` : `Paper · ${it.primary_tag}` }),
        el("a", { class: "card-date", href: `#/day/${it.date}`, text: fmtShort(it.date) })),
      el("h3", {}, el("a", { href: "javascript:void 0", onclick: (e) => { e.preventDefault(); open(); }, text: it.title })),
      el("p", { class: "byline", text: it.byline }),
      tagChips(it, isNews),
      el("p", { class: "tldr", text: it.tldr }),
      el("div", { class: "card-foot" }, btn));
    return card;
  }

  // ---------- views
  async function renderDay(date) {
    const main = $("#main");
    if (!date) { main.replaceChildren(el("div", { class: "empty", text: "No digests yet — the first one arrives at 7:30 ET." })); return; }
    if (!S.dateSet.has(date)) { main.replaceChildren(el("div", { class: "empty" }, `No digest for ${fmtLong(date)}. `, el("a", { href: "#/", text: "Go to the latest." }))); return; }
    const j = await getDay(date);
    const i = S.dates.indexOf(date);
    const newer = S.dates[i - 1], older = S.dates[i + 1];
    const weekend = j.edition === "weekend";
    const nav = el("div", { class: "day-nav" },
      older ? el("a", { href: `#/day/${older}`, title: "Previous day (←)", text: "← " + fmtShort(older) }) : el("span", { text: "←" }),
      newer ? el("a", { href: `#/day/${newer}`, title: "Next day (→)", text: fmtShort(newer) + " →" }) : el("span", { text: "→" }));
    const head = el("div", { class: "day-head" },
      el("div", {}, el("h1", { text: fmtLong(date) }),
        el("div", { class: "day-meta" },
          el("span", { class: "badge" + (weekend ? " weekend" : ""), text: weekend ? "Weekend edition · best of the week" : "Daily edition" }),
          j.backfill ? el("span", { class: "badge demo", text: "Demo (backfilled)" }) : null,
          `${(j.news || []).length} news · ${(j.papers || []).length} papers`)),
      nav);
    const out = [head];
    if (j.summary) out.push(el("p", { class: "note", text: j.summary }));
    out.push(el("h2", { class: "section-title", text: "News" }));
    if ((j.news || []).length) out.push(...j.news.map((n) => fullCard(n, true, date)));
    else out.push(el("p", { class: "note", text: "No news story cleared the bar for this window." }));
    out.push(el("h2", { class: "section-title", text: weekend ? "Best papers of the week" : "Papers" }));
    if ((j.papers || []).length) out.push(...j.papers.map((p) => fullCard(p, false, date)));
    else out.push(el("p", { class: "note", text: "No papers this time." }));
    main.replaceChildren(...out);
    main.focus({ preventScroll: true });
    window.scrollTo({ top: 0 });
  }

  function renderBrowse() {
    const f = S.f, q = f.q.toLowerCase();
    const items = S.index.items.filter((it) => {
      if (f.type !== "all" && it.type !== f.type) return false;
      if (f.from && (it.date < f.from || it.date > f.to)) return false;
      if (f.tags.size || f.cats.size) {
        const okP = it.type === "paper" && f.tags.size && it.tags.some((t) => f.tags.has(t));
        const okN = it.type === "news" && f.cats.size && f.cats.has(it.category);
        if (!okP && !okN) return false;
      }
      if (q && !(`${it.title} ${it.tldr} ${it.byline}`.toLowerCase().includes(q))) return false;
      return true;
    });
    const desc = [];
    if (f.type !== "all") desc.push(f.type === "paper" ? "papers" : "news");
    if (f.tags.size) desc.push("tags: " + [...f.tags].join(", "));
    if (f.cats.size) desc.push("categories: " + [...f.cats].join(", "));
    if (f.from) desc.push(f.from === f.to ? fmtShort(f.from) : `${fmtShort(f.from)} – ${fmtShort(f.to)}`);
    if (f.q) desc.push(`“${f.q}”`);
    const out = [el("div", { class: "day-head" }, el("div", {}, el("h1", { text: "Browse" }),
      el("div", { class: "day-meta", text: desc.join(" · ") || "everything" })),
      el("div", { class: "day-nav" }, el("a", { href: "#/", text: "Latest digest" })))];
    out.push(el("p", { class: "result-count", text: `${items.length} result${items.length === 1 ? "" : "s"}` }));
    let cur = null;
    for (const it of items) {
      if (it.date !== cur) { cur = it.date; out.push(el("p", { class: "group-date" }, el("a", { href: `#/day/${it.date}`, text: fmtLong(it.date) }))); }
      out.push(compactCard(it));
    }
    if (!items.length) out.push(el("p", { class: "note", text: "Nothing matches these filters." }));
    $("#main").replaceChildren(...out);
  }

  // ---------- wiring
  function wire() {
    let t;
    $("#search").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { S.f.q = e.target.value.trim(); applyFilters(); }, 250); });
    for (const b of $("#typeSeg").children) b.addEventListener("click", () => { S.f.type = b.dataset.type; applyFilters(); });
    for (const b of document.querySelectorAll("[data-mode]")) b.addEventListener("click", () => {
      S.calMode = b.dataset.mode; S.rangeStart = null;
      document.querySelectorAll("[data-mode]").forEach((x) => x.classList.toggle("on", x === b));
      if (S.calMode === "day" && S.f.from) { S.f.from = S.f.to = null; applyFilters(); } else renderCalendar();
    });
    $("#clearAll").addEventListener("click", () => { S.f = blankFilters(); S.rangeStart = null; location.hash = "#/"; });
    $("#filtersToggle").addEventListener("click", () => {
      const open = $("#sidebar").classList.toggle("open");
      $("#filtersToggle").setAttribute("aria-expanded", String(open));
    });
    $("#themeToggle").addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (e) { /* storage unavailable */ }
    });
    document.addEventListener("keydown", (e) => {
      if (e.target.matches("input, textarea") || !S.current || S.current.view !== "day") return;
      const i = S.dates.indexOf(S.current.date);
      if (e.key === "ArrowLeft" && S.dates[i + 1]) location.hash = `#/day/${S.dates[i + 1]}`;
      if (e.key === "ArrowRight" && i > 0) location.hash = `#/day/${S.dates[i - 1]}`;
    });
    window.addEventListener("hashchange", route);
  }

  async function init() {
    try {
      S.index = await getJSON("data/index.json");
    } catch (e) {
      $("#main").replaceChildren(el("div", { class: "empty", text: "No digests published yet." }));
      return;
    }
    S.dates = S.index.days.map((d) => d.date);
    S.dateSet = new Set(S.dates);
    for (const [g, tags] of Object.entries(S.index.tag_groups)) for (const t of tags) S.groupOf[t] = g;
    const latest = S.dates[0] ? dObj(S.dates[0]) : new Date();
    S.calMonth = new Date(latest.getFullYear(), latest.getMonth(), 1);
    wire();
    route();
  }
  init();
})();
