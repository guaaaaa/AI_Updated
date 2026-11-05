/* Updated — static front end. One tab per domain (data/domains.json): AI (data/index.json + data/days/) and the
   other domains (data/<id>/index.json + data/<id>/days/), plus the Jobs board. Trends view: assets/trends.js (AI).
   Routes: #/<domain>[/day/<date>[/<item>] | /browse?... | /trends...]; old #/day, #/trends, #/browse links are AI.
   All content is rendered with textContent (never innerHTML) so digest text can't inject markup. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const S = {
    domains: [], dom: null, D: null, byDom: new Map(),
    index: null, dayFiles: new Map(), groupOf: {}, dates: [], dateSet: new Set(),
    calMonth: null, calMode: "day", rangeStart: null, sumByDate: {}, weekOf: {},
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
  const dataBase = (dom) => (dom === "ai" ? "data/" : `data/${dom}/`);
  const home = (dom = S.dom) => `#/${dom}`;
  const dayHref = (date, item, dom = S.dom) => `#/${dom}/day/${date}${item ? "/" + item : ""}`;
  const paperWord = () => (S.D && S.D.paper_label) || "Papers";
  const paperNoun = (n) => (paperWord() === "Research" ? "research paper" : "paper") + (n === 1 ? "" : "s");
  const weekHref = (id) => (S.dom === "ai" ? `#/trends/week/${id}` : `#/${S.dom}/week/${id}`);   // AI's lives in Trends
  // items live in monthly files (index.item_months); only browsing, search and AI's Trends need them
  async function loadItems() {
    if (S.index.items) return S.index.items;
    const base = S.D.index.replace(/index\.json$/, "");
    const parts = await Promise.all((S.index.item_months || []).map((m) => getJSON(`${base}items/${m.month}.json`).catch(() => [])));
    return (S.index.items = parts.flat());
  }

  async function getDay(date, dom = S.dom) {
    const k = `${dom}/${date}`;
    if (!S.dayFiles.has(k)) S.dayFiles.set(k, getJSON(`${dataBase(dom)}days/${date}.json`));
    return S.dayFiles.get(k);
  }

  // Switch the digest state (index, dates, tag groups, calendar marks) to a domain; cached per domain.
  async function useDomain(dom) {
    if (S.dom === dom && S.index) return;
    if (!S.byDom.has(dom)) {
      const D = S.domains.find((d) => d.id === dom);
      let index;
      try { index = await getJSON(D.index); } catch (e) { index = { days: [], items: [], tag_groups: {}, tag_counts: {}, news_categories: [], category_counts: {}, weeks: [], summaries: [] }; }
      const st = { D, index, dates: index.days.map((d) => d.date), groupOf: {}, sumByDate: {}, weekOf: {} };
      st.dateSet = new Set(st.dates);
      for (const [g, tags] of Object.entries(index.tag_groups)) for (const t of tags) st.groupOf[t] = g;
      // Sundays (no digest) open that week's Week in review; the 1st opens the monthly summary if there is no digest.
      for (const w of index.weeks || []) {
        const sun = dObj(w.end); sun.setDate(sun.getDate() + 1);
        st.sumByDate[isoOf(sun)] = { kind: "weekly", id: w.id, headline: "Week in review" };
        for (let d = dObj(w.start); isoOf(d) <= w.end; d.setDate(d.getDate() + 1)) st.weekOf[isoOf(d)] = w;
      }
      for (const x of index.summaries || []) if (x.kind === "monthly" && !st.sumByDate[x.published]) st.sumByDate[x.published] = x;
      S.byDom.set(dom, st);
    }
    const st = S.byDom.get(dom);
    Object.assign(S, { dom, D: st.D, index: st.index, dates: st.dates, dateSet: st.dateSet, groupOf: st.groupOf, sumByDate: st.sumByDate, weekOf: st.weekOf });
    S.f = blankFilters(); S.rangeStart = null;
    const latest = S.dates[0] ? dObj(S.dates[0]) : new Date();
    S.calMonth = new Date(latest.getFullYear(), latest.getMonth(), 1);
    $("#typeSeg").children[1].textContent = paperWord();
    $("#typeSeg").hidden = !st.D.papers;                         // news-only domains have no papers
    $("#tagsTitle").closest(".panel").hidden = !st.D.papers;
    $("#tagsTitle").textContent = `${paperWord() === "Papers" ? "Paper" : paperWord()} tags`;
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
    return `#/${S.dom}/browse` + (p.toString() ? "?" + p : "");
  }
  function applyFilters() { location.hash = filtersActive() ? browseHash() : home(); }

  function parseRoute() {
    const full = location.hash.replace(/^#/, "").replace(/^\/health(?=\/|$)/, "/biology");   // Health became Biology
    if (full === "" || full === "/" || full === "/today") return { view: "today", dom: S.dom || "ai" };
    const j = full.match(/^\/jobs(?:\/([\w-]+))?/);
    if (j) return { view: "jobs", id: j[1] || null, dom: S.dom || "ai" };
    const dm = full.match(/^\/([a-z]+)(\/.*)?$/);
    const known = dm && S.domains.some((d) => d.id === dm[1]);
    const dom = known ? dm[1] : "ai", h = known ? dm[2] || "" : full;   // old links without a domain are AI
    const m = h.match(/^\/day\/(\d{4}-\d{2}-\d{2})(?:\/([\w.-]+))?/);
    if (m) return { view: "day", date: m[1], item: m[2] || null, dom };
    const t = dom === "ai" && h.match(/^\/trends(?:\/(week|month|direction|field)\/([\w.-]+))?/);
    const wk = dom !== "ai" && h.match(/^\/week\/([\w-]+)/);
    if (wk) return { view: "week", id: wk[1], dom };
    if (t) return { view: "trends", kind: t[1] ? { week: "weekly", month: "monthly", direction: "direction", field: "field" }[t[1]] : null, id: t[2] || null, dom };
    if (h.startsWith("/browse")) {
      const p = new URLSearchParams(h.split("?")[1] || "");
      S.f.type = ["paper", "news"].includes(p.get("type")) ? p.get("type") : "all";
      S.f.tags = new Set((p.get("tags") || "").split("|").filter(Boolean));
      S.f.cats = new Set((p.get("cats") || "").split("|").filter(Boolean));
      S.f.q = p.get("q") || "";
      S.f.from = p.get("from"); S.f.to = p.get("to") || p.get("from");
      return { view: "browse", dom, keep: true };
    }
    return { view: "day", date: null, dom };
  }

  async function renderWeek(id) {   // other tabs' Week in review (AI's is part of its Trends view)
    const card = await window.AIUTrends.weekCard(S.index.weeks || [], id,
      { base: S.D.index.replace(/index\.json$/, ""), link: (date, item) => dayHref(date, item), paperWord: paperWord() });
    $("#main").replaceChildren(card || el("div", { class: "empty", text: `No ${S.D.name} Week in review yet.` }));
  }

  async function route() {
    let r = parseRoute();
    if (r.view !== "jobs" && r.view !== "today" && r.dom !== S.dom) {
      const keep = r.view === "browse" ? { ...S.f } : null;
      await useDomain(r.dom);
      if (keep) r = parseRoute();   // browse filters were parsed before the switch reset them
    }
    if (r.view === "day") {
      S.f = blankFilters();
      r.date = r.date || S.dates[0];
      if (r.date) S.calMonth = new Date(dObj(r.date).getFullYear(), dObj(r.date).getMonth(), 1);
    }
    const wide = r.view === "trends" || r.view === "jobs" || r.view === "today";
    $(".layout").classList.toggle("wide", wide);
    for (const a of document.querySelectorAll("#viewNav a")) {
      a.classList.toggle("on", a.dataset.view === (r.view === "jobs" || r.view === "today" ? r.view : r.dom));
      if (a.classList.contains("on") && a.parentElement.scrollWidth > a.parentElement.clientWidth) a.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
    document.title = r.view === "jobs" ? "Jobs · Updated" : r.view === "today" ? "Today · Updated" : `${S.D.name} · Updated`;
    if (!wide) syncSidebar(r); else S.current = r;
    const main = $("#main");
    main.replaceChildren(el("div", { class: "loading", text: "Loading…" }));
    try {
      if (r.view === "browse" || r.view === "trends") await loadItems();
      if (r.view === "today") await renderToday();
      else if (r.view === "day") await renderDay(r.date, r.item);
      else if (r.view === "trends") await window.AIUTrends.render(main, r, S);
      else if (r.view === "jobs") await window.AIUJobs.render(main, r, S);
      else if (r.view === "week") await renderWeek(r.id);
      else renderBrowse();
      if (r.view !== "jobs" && r.view !== "today" && S.D.trends) $("#main").prepend(subNav(r.view === "trends" ? "trends" : "digest"));
    } catch (e) {
      main.replaceChildren(el("div", { class: "empty", text: `Could not load this view (${e.message}).` }));
    }
    if (window.innerWidth <= 900) { $("#sidebar").classList.remove("open"); $(".layout").classList.remove("filters-open"); }
    $("#filtersToggle").classList.toggle("active", Boolean(filtersActive()));
  }

  // Digest / Trends switch for domains with a trends view.
  function subNav(on) {
    return el("nav", { class: "sub-nav", "aria-label": `${S.D.name} views` },
      el("a", { href: home(), class: on === "digest" ? "on" : null, text: "Digest" }),
      el("a", { href: `#/${S.dom}/trends`, class: on === "trends" ? "on" : null, text: "Trends" }));
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
      const sum = !has && S.sumByDate[iso];
      const ranged = S.calMode === "range";
      const cls = ["cal-day", has && "has", sum && "sum", ranged && "pickable", iso === today && "today",
        (iso === sel || iso === from || iso === to) && "sel",
        from && to && iso > from && iso < to && "inrange"].filter(Boolean).join(" ");
      grid.append(el("button", {
        class: cls, text: String(d), disabled: !has && !sum && !ranged,
        "aria-label": fmtLong(iso) + (has ? " (digest available)" : sum ? (sum.kind === "weekly" ? " (week in review)" : " (monthly summary)") : ""),
        title: sum ? (sum.kind === "weekly" ? "Week in review" : `Monthly summary: ${sum.headline}`) : null,
        onclick: () => (sum && !ranged ? (location.hash = sum.kind === "weekly" ? weekHref(sum.id) : `#/trends/month/${sum.id}`) : pickDate(iso)),
      }));
    }
    const head = el("div", { class: "cal-head" },
      el("button", { class: "cal-nav", "aria-label": "Previous month", disabled: !prevOk, onclick: () => shiftMonth(-1), text: "‹" }),
      el("strong", { text: m.toLocaleDateString("en-US", { month: "long", year: "numeric" }) }),
      el("button", { class: "cal-nav", "aria-label": "Next month", disabled: !nextOk, onclick: () => shiftMonth(1), text: "›" }));
    box.replaceChildren(head, grid);
    $("#calHint").textContent = S.calMode === "range"
      ? (S.rangeStart ? "Now pick the end date." : (S.f.from ? `Showing ${fmtShort(S.f.from)} – ${fmtShort(S.f.to)}` : "Pick a start date."))
      : (S.index.weeks || []).length ? "Dots mark days with a digest; ringed Sundays open the Week in review." : "Dots mark days with a digest.";
  }
  function shiftMonth(k) { S.calMonth = new Date(S.calMonth.getFullYear(), S.calMonth.getMonth() + k, 1); renderCalendar(); }

  function pickDate(iso) {
    if (S.calMode === "day") { location.hash = dayHref(iso); return; }
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

  // Cards open collapsed: label, title and the one-sentence summary. "Read summary" reveals the rest.
  function cardLinks(item, isNews) {
    const box = el("div", { class: "card-links" });
    if (isNews) {
      for (const s of item.sources || []) { const u = safeUrl(s.url); if (u) box.append(el("a", { href: u, target: "_blank", rel: "noopener", text: s.name })); }
    } else {
      const L = item.links || {};
      for (const [n, u] of [["arXiv", L.arxiv], ["PDF", L.arxiv && L.arxiv.replace("/abs/", "/pdf/")], ["Paper", L.paper], ["DOI", L.doi], ["Code", L.code]])
        if (safeUrl(u)) box.append(el("a", { href: u, target: "_blank", rel: "noopener", text: n }));
    }
    return box;
  }

  function fullCard(item, isNews, date, open = false) {
    const L0 = item.links || {}, venue = (item.signals || {}).venue;
    const href = isNews ? safeUrl((item.sources || [])[0] && item.sources[0].url) : safeUrl(L0.arxiv || L0.paper || L0.doi);
    const when = isNews && item.published ? fmtShort(item.published.slice(0, 10))
      : (!isNews && item.announced ? `${venue || "arXiv"} ${fmtShort(item.announced.slice(0, 10))}` : fmtShort(date));
    const L = item.links || {};
    const more = isNews ? [] : [["alphaXiv", L.alphaxiv], ["Project", L.project]].filter(([, u]) => safeUrl(u));
    const body = el("div", { class: "body" },
      el("p", { class: "byline", text: byline(item, isNews) }),
      tagChips(item, isNews),
      (item.sections || []).map((s) => [
        el("h4", { text: s.heading }),
        ...String(s.body || "").split(/\n\s*\n/).map((p) => el("p", { text: p.trim() })),
      ]),
      item.why_selected || more.length ? el("p", { class: "why" }, item.why_selected ? "Why it's here: " + item.why_selected + " " : "",
        more.map(([n, u]) => el("a", { href: u, target: "_blank", rel: "noopener", text: n }))) : null);
    body.hidden = !open;
    const toggle = el("button", { class: "toggle", "aria-expanded": String(open), text: open ? "Show less" : "Read summary" });
    toggle.addEventListener("click", () => {
      const hidden = body.hidden = !body.hidden;
      toggle.textContent = hidden ? "Read summary" : "Show less";
      toggle.setAttribute("aria-expanded", String(!hidden));
    });
    return el("article", { class: `card ${isNews ? "news" : "paper"}`, id: `item-${item.id}`, dataset: { g: isNews ? "news" : S.groupOf[item.primary_tag] || "" } },
      el("div", { class: "card-top" }, el("span", { class: "kind", text: isNews ? item.category : item.primary_tag }), el("span", { class: "card-date", text: when })),
      el("h3", {}, href ? el("a", { href, target: "_blank", rel: "noopener", text: item.title }) : item.title),
      el("p", { class: "tldr", text: item.tldr }),
      body,
      el("div", { class: "card-foot" }, toggle, cardLinks(item, isNews)));
  }

  function compactCard(it) {
    const isNews = it.type === "news";
    const card = el("article", { class: `card ${isNews ? "news" : "paper"}`, dataset: { g: isNews ? "news" : S.groupOf[it.primary_tag] || "" } });
    const open = async () => {
      try {
        const day = await getDay(it.date);
        const full = (isNews ? day.news : day.papers).find((x) => x.id === it.id);
        if (full) card.replaceWith(fullCard(full, isNews, it.date, true));
      } catch (e) { btn.textContent = "Could not load"; }
    };
    const btn = el("button", { class: "toggle", text: "Read summary", onclick: open });
    card.append(
      el("div", { class: "card-top" }, el("span", { class: "kind", text: isNews ? it.category : it.primary_tag }),
        el("a", { class: "card-date", href: dayHref(it.date), text: fmtShort(it.date) })),
      el("h3", {}, el("a", { href: "javascript:void 0", onclick: (e) => { e.preventDefault(); open(); }, text: it.title })),
      el("p", { class: "tldr", text: it.tldr }),
      el("div", { class: "card-foot" }, btn));
    return card;
  }

  // ---------- views
  // Today: the latest digest of every tab, three highlights each (news first, at least one paper where a tab has them)
  async function renderToday() {
    const doms = S.domains.filter((d) => d.latest);
    const [days, idxs] = await Promise.all([
      Promise.all(doms.map((d) => getDay(d.latest, d.id).catch(() => null))),
      Promise.all(doms.map((d) => (S.byDom.has(d.id) ? Promise.resolve(S.byDom.get(d.id).index) : getJSON(d.index)).catch(() => ({}))))]);
    const latest = doms.map((d) => d.latest).sort().pop();
    const sections = doms.map((d, i) => {
      const j = days[i];
      if (!j) return null;
      const groupOf = {};
      for (const [g, tags] of Object.entries(idxs[i].tag_groups || {})) for (const t of tags) groupOf[t] = g;
      const news = j.news || [], papers = j.papers || [];
      const nP = papers.length ? Math.min(papers.length, Math.max(1, 3 - Math.min(news.length, 2))) : 0;
      const picks = [...news.slice(0, 3 - nP).map((x) => [x, true]), ...papers.slice(0, nP).map((x) => [x, false])];
      const word = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
      return el("section", { class: "today-tab" },
        el("div", { class: "today-tab-head" },
          el("h2", {}, el("a", { href: `#/${d.id}`, text: d.name })),
          el("span", { class: "day-meta", text: `${fmtShort(j.date)} · ${word(news.length, "news story").replace("storys", "stories")}` +
            (d.papers ? ` · ${word(papers.length, d.paper_label === "Research" ? "research paper" : "paper")}` : "") }),
          el("a", { class: "today-more", href: dayHref(j.date, null, d.id), text: "Full digest →" })),
        el("div", { class: "today-grid" }, ...picks.map(([x, isNews]) =>
          el("article", { class: `card compact ${isNews ? "news" : "paper"}`, dataset: { g: isNews ? "news" : groupOf[x.primary_tag] || "" } },
            el("div", { class: "card-top" }, el("span", { class: "kind", text: isNews ? x.category : x.primary_tag }),
              el("span", { class: "card-date", text: isNews ? (x.sources || []).slice(0, 2).map((s) => s.name).join(" · ")
                : ((x.signals || {}).venue || (d.id === "ai" ? "arXiv" : "")) })),
            el("h3", {}, el("a", { href: dayHref(j.date, x.id, d.id), text: x.title })),
            el("p", { class: "tldr", text: x.tldr })))));
    });
    $("#main").replaceChildren(
      el("div", { class: "day-head" }, el("div", {}, el("h1", { text: "Today" }),
        el("div", { class: "day-meta" }, `The latest digest from every tab${latest ? ", " + fmtLong(latest) : ""} · `,
          el("a", { href: "data/feeds/all.xml", text: "RSS" })))),
      ...(sections.some(Boolean) ? sections.filter(Boolean) : [el("div", { class: "empty", text: "No digests yet." })]));
    window.scrollTo({ top: 0 });
  }

  function glanceList(j, date) {
    const rows = [...(j.news || []).map((n) => ({ it: n, news: true })), ...(j.papers || []).map((p) => ({ it: p, news: false }))];
    return el("ol", { class: "glance" }, rows.map(({ it, news }) =>
      el("li", { dataset: { g: news ? "news" : S.groupOf[it.primary_tag] || "" } },
        el("span", { class: "g-dot", "aria-hidden": "true" }),
        el("a", { href: dayHref(date, it.id), text: it.title }),
        el("span", { class: "g-kind", text: news ? it.category : it.primary_tag }))));
  }

  async function renderDay(date, itemId) {
    const main = $("#main");
    if (!date) { main.replaceChildren(el("div", { class: "empty", text: `No ${S.D.name} digests yet: the first one arrives on a weekday morning (ET).` })); return; }
    if (!S.dateSet.has(date)) { main.replaceChildren(el("div", { class: "empty" }, `No ${S.D.name} digest for ${fmtLong(date)}. `, el("a", { href: home(), text: "Go to the latest." }))); return; }
    const j = await getDay(date);
    const i = S.dates.indexOf(date);
    const newer = S.dates[i - 1], older = S.dates[i + 1];
    const weekend = j.edition === "weekend";
    const nav = el("div", { class: "day-nav" },
      older ? el("a", { href: dayHref(older), title: "Previous day (←)", text: "← " + fmtShort(older) }) : el("span", { text: "←" }),
      newer ? el("a", { href: dayHref(newer), title: "Next day (→)", text: fmtShort(newer) + " →" }) : el("span", { text: "→" }));
    const meta = [S.dom === "ai" && weekend ? "Weekend edition" : null, `${S.D.name}: ${(j.news || []).length} news · ${(j.papers || []).length} ${paperNoun((j.papers || []).length)}`,
      j.backfill ? "backfilled" : null].filter(Boolean).join(" · ");
    const head = el("div", { class: "day-head" },
      el("div", {}, el("h1", { text: fmtLong(date) }),
        el("div", { class: "day-meta" }, meta,
          S.weekOf[date] ? el("a", { href: weekHref(S.weekOf[date].id), text: "Week in review →" }) : null)),
      nav);
    const out = [head];
    if (j.summary) out.push(el("p", { class: "day-summary", text: j.summary }));
    out.push(el("h2", { class: "section-title", text: "News" }));
    if ((j.news || []).length) out.push(...j.news.map((n) => fullCard(n, true, date, n.id === itemId)));
    else out.push(el("p", { class: "note", text: "No news story cleared the bar for this window." }));
    if (S.D.papers) {
      out.push(el("h2", { class: "section-title", text: S.dom === "ai" && weekend ? "Best papers of the week" : paperWord() }));
      if ((j.papers || []).length) out.push(...j.papers.map((p) => fullCard(p, false, date, p.id === itemId)));
      else out.push(el("p", { class: "note", text: `No ${paperWord().toLowerCase()} this time.` }));
    }
    main.replaceChildren(...out);
    main.focus({ preventScroll: true });
    const target = itemId && document.getElementById(`item-${itemId}`);
    if (target) target.scrollIntoView({ block: "start" }); else window.scrollTo({ top: 0 });
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
    if (f.type !== "all") desc.push(f.type === "paper" ? paperWord().toLowerCase() : "news");
    if (f.tags.size) desc.push("tags: " + [...f.tags].join(", "));
    if (f.cats.size) desc.push("categories: " + [...f.cats].join(", "));
    if (f.from) desc.push(f.from === f.to ? fmtShort(f.from) : `${fmtShort(f.from)} – ${fmtShort(f.to)}`);
    if (f.q) desc.push(`“${f.q}”`);
    const out = [el("div", { class: "day-head" }, el("div", {}, el("h1", { text: `Browse ${S.D.name}` }),
      el("div", { class: "day-meta", text: desc.join(" · ") || "everything" })),
      el("div", { class: "day-nav" }, el("a", { href: home(), text: "Latest digest" })))];
    out.push(el("p", { class: "result-count", text: `${items.length} result${items.length === 1 ? "" : "s"}` }));
    let cur = null;
    for (const it of items) {
      if (it.date !== cur) { cur = it.date; out.push(el("p", { class: "group-date" }, el("a", { href: dayHref(it.date), text: fmtLong(it.date) }))); }
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
    $("#clearAll").addEventListener("click", () => { S.f = blankFilters(); S.rangeStart = null; location.hash = home(); });
    const setFilters = (open, remember) => {
      $("#sidebar").classList.toggle("open", open);
      $(".layout").classList.toggle("filters-open", open);
      $("#filtersToggle").setAttribute("aria-expanded", String(open));
      if (remember) try { localStorage.setItem("filters", open ? "open" : "closed"); } catch (e) { /* storage unavailable */ }
    };
    $("#filtersToggle").addEventListener("click", () => setFilters(!$("#sidebar").classList.contains("open"), true));
    let remembered = null;
    try { remembered = localStorage.getItem("filters"); } catch (e) { /* storage unavailable */ }
    if (remembered === "open" && window.innerWidth > 900) setFilters(true, false);
    // colour schemes (assets/themes.json, generated by pipeline/make_themes.py); the choice is saved per browser
    const pbtn = $("#paletteBtn"), pmenu = $("#paletteMenu");
    if (pbtn && pmenu) {
      const close = () => { pmenu.hidden = true; pbtn.setAttribute("aria-expanded", "false"); };
      getJSON("assets/themes.json").then((list) => {
        const draw = () => pmenu.replaceChildren(el("div", { class: "pm-title", text: "Colour scheme" }), ...list.map((s) =>
          el("button", { class: "palette-opt" + (document.documentElement.dataset.palette === s.id ? " on" : ""), role: "menuitemradio",
            "aria-checked": String(document.documentElement.dataset.palette === s.id),
            onclick: () => {
              document.documentElement.dataset.palette = s.id;
              try { localStorage.setItem("palette", s.id); } catch (e) { /* storage unavailable */ }
              draw(); close();
            } },
            el("span", { class: "sw", "aria-hidden": "true" }, ...s.swatch.map((c) => el("i", { style: `background:${c}` }))),
            el("span", {}, el("b", { text: s.name }), el("small", { text: `light: ${s.light} · dark: ${s.dark}` })))));
        draw();
        pbtn.addEventListener("click", (e) => { e.stopPropagation(); const open = pmenu.hidden; pmenu.hidden = !open; pbtn.setAttribute("aria-expanded", String(open)); });
        document.addEventListener("click", (e) => { if (!pmenu.hidden && !pmenu.contains(e.target)) close(); });
        document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pmenu.hidden) { close(); pbtn.focus(); } });
      }).catch(() => { pbtn.hidden = true; });
    }
    $("#themeToggle").addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (e) { /* storage unavailable */ }
    });
    document.addEventListener("keydown", (e) => {
      if (e.target.matches("input, textarea, select") || !S.current || S.current.view !== "day") return;
      const i = S.dates.indexOf(S.current.date);
      if (e.key === "ArrowLeft" && S.dates[i + 1]) location.hash = dayHref(S.dates[i + 1]);
      if (e.key === "ArrowRight" && i > 0) location.hash = dayHref(S.dates[i - 1]);
    });
    window.addEventListener("hashchange", route);
  }

  async function init() {
    try {
      S.domains = (await getJSON("data/domains.json")).domains;
    } catch (e) {
      S.domains = [{ id: "ai", name: "AI", index: "data/index.json", trends: true, paper_label: "Papers", papers: 5 }];
    }
    $("#viewNav").replaceChildren(el("a", { href: "#/", dataset: { view: "today" }, text: "Today" }),
      ...S.domains.map((d) => el("a", { href: `#/${d.id}`, dataset: { view: d.id }, text: d.name })),
      el("a", { href: "#/jobs", dataset: { view: "jobs" }, text: "Jobs" }));
    const feeds = $("#feeds");
    if (feeds) feeds.replaceChildren("RSS: ", el("a", { href: "data/feeds/all.xml", text: "all tabs" }),
      ...S.domains.flatMap((d) => [" · ", el("a", { href: d.feed || `data/feeds/${d.id}.xml`, text: d.name })]));
    const helpers = { el, getJSON, getDay, dObj, fmtShort, fmtLong, isoOf, safeUrl, glanceList };
    if (window.AIUTrends) window.AIUTrends.init(helpers);
    if (window.AIUJobs) window.AIUJobs.init(helpers, window.AIUTrends && window.AIUTrends.kit);
    await useDomain("ai");
    wire();
    route();
  }
  init();
})();
