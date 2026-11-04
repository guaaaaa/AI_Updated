/* AI Updated — Job board (#/jobs) and role pages (#/jobs/<id>). Data: data/jobs.json, data/jobs/<id>.json
   (pipeline/build_jobs.py). A role's "price" comes from the job market itself: open postings at tracked employers
   (daily since the tracker started), Hacker News hiring ads (monthly since 2012) and Indeed's category index (daily
   since 2020). Research only enters through the labelled "research tailwind". Text goes in with textContent. */
(() => {
  "use strict";
  let H = null, K = null;
  const files = new Map();
  const get = (url) => { if (!files.has(url)) files.set(url, H.getJSON(url).catch((e) => { files.delete(url); throw e; })); return files.get(url); };
  const pct = (x, d = 0) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
  const money = (v, cur = "USD") => (v == null ? "–" : `${cur === "CAD" ? "CA$" : "$"}${Math.round(v / 1000)}K`);
  const signedPct = (x) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(0)}%`);
  const jobHref = (id) => `#/jobs/${id}`;
  const OUTLOOK = ["", "Very limited", "Limited", "Moderate", "Good", "Very good"];

  // ---------------------------------------------------------------- scoring: percentiles among roles, user weights
  const CRITERIA = [
    { key: "demand", label: "Demand trend", parts: [["demand", 1], ["ca_outlook", 1]],
      help: "Is hiring for the role growing? Hacker News hiring-ad share (last 6 months vs a year earlier), Indeed's category index (6 months), openings at tracked employers once 4 weeks of snapshots exist, and Canada's official 3-year outlook (Job Bank)." },
    { key: "openings", label: "Job volume", parts: [["open", 1], ["bls_emp", 1]],
      help: "Open US and Canada postings at the tracked employers, and how many people hold the occupation in the US (BLS)." },
    { key: "pay", label: "Pay", parts: [["pay", 1]], help: "Median midpoint of posted salary ranges (US, in USD; Canadian ranges converted at 0.73 where a role has no US data)." },
    { key: "entry", label: "Ease of entry", parts: [["junior", 1], ["phd", -1], ["yrs", -1]],
      help: "Share of postings open to interns and juniors, how often a PhD is mentioned, and the median years of experience asked." },
    { key: "competition", label: "Low competition", parts: [["seekers_per_ad", -1], ["age", 1]],
      help: "Job seekers per hiring ad naming the role on Hacker News (last 12 months), and how long postings stay open (older = harder to fill = better odds)." },
    { key: "stability", label: "Stability", parts: [["companies", 1], ["top3", -1]], help: "How many employers are hiring, and how concentrated postings are in the top three." },
    { key: "ai", label: "AI outlook", parts: [["tailwind", 1]],
      help: "Research tailwind: momentum in research directions that create demand for the role, minus momentum in directions that automate its tasks (scaled by how much of the work AI already does). A heuristic, not a forecast." },
    { key: "flex", label: "Flexibility", parts: [["remote", 1], ["equity", 1]], help: "Share of postings that are remote or offer equity." },
  ];
  const DEFAULT_W = { demand: 4, openings: 2, pay: 4, entry: 3, competition: 2, stability: 1, ai: 3, flex: 1 };
  const LS = "aiu-job-weights";
  const loadW = () => { try { return { ...DEFAULT_W, ...JSON.parse(localStorage.getItem(LS) || "{}") }; } catch (e) { return { ...DEFAULT_W }; } };
  const saveW = (w) => { try { localStorage.setItem(LS, JSON.stringify(w)); } catch (e) { /* private mode */ } };
  const rawOf = (r, k) => (k === "pay" ? (r.pay_us ?? (r.pay_ca != null ? r.pay_ca * 0.73 : null)) : r[k]);

  function scoreRoles(roles, w) {
    const pctl = {};
    for (const c of CRITERIA) for (const [k, sign] of c.parts) {
      const vals = roles.map((r) => rawOf(r, k)).filter((v) => v != null).map((v) => v * sign).sort((a, b) => a - b);
      pctl[k] = (r) => {
        const v = rawOf(r, k);
        if (v == null || vals.length < 2) return null;
        const x = v * sign, lo = vals.filter((y) => y < x).length, eq = vals.filter((y) => y === x).length;
        return (lo + (eq - 1) / 2) / (vals.length - 1);
      };
    }
    return roles.map((r) => {
      const crit = {};
      for (const c of CRITERIA) {
        const ps = c.parts.map(([k]) => pctl[k](r)).filter((p) => p != null);
        crit[c.key] = ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : null;
      }
      let num = 0, den = 0;
      for (const c of CRITERIA) if (crit[c.key] != null && w[c.key]) { num += w[c.key] * crit[c.key]; den += w[c.key]; }
      return { ...r, crit, score: den ? Math.round((100 * num) / den) : null };
    });
  }

  // ---------------------------------------------------------------- board
  async function board(main, S) {
    let B;
    try { B = await get("data/jobs.json"); } catch (e) {
      main.replaceChildren(H.el("p", { class: "note", text: "The job board has no data yet." })); return;
    }
    const w = loadW(), st = { sort: "score", group: "all" };
    const body = H.el("div");
    const sliders = H.el("div", { class: "weights" });
    const draw = () => {
      const rows = scoreRoles(B.roles, w).filter((r) => st.group === "all" || r.group === st.group);
      const key = { score: (r) => r.score, open: (r) => r.open, pay: (r) => rawOf(r, "pay"), demand: (r) => r.demand, ai: (r) => r.tailwind, entry: (r) => r.crit.entry }[st.sort];
      rows.sort((a, b) => (key(b) ?? -1e9) - (key(a) ?? -1e9));
      const tracking = B.tracker_days > 1;
      body.replaceChildren(H.el("div", { class: "table-wrap" }, H.el("table", { class: "board jobs" },
        H.el("thead", {}, H.el("tr", {}, ["#", "Role", "Score", "Openings", "Pay (US)", "Entry", "AI outlook", "Hiring trend"].map((h, i) =>
          H.el("th", { class: ["num", "", "c-score", "num", "num", "num c-entry", "num c-ai", "c-spark"][i], text: h })))),
        H.el("tbody", {}, rows.map((r, i) => H.el("tr", { onclick: (e) => { if (!e.target.closest("a")) location.hash = jobHref(r.id); } },
          H.el("td", { class: "num rank-n", text: String(i + 1) }),
          H.el("td", { class: "c-name" }, H.el("a", { href: jobHref(r.id), text: r.name }),
            (r.open ?? 0) < 30 ? H.el("span", { class: "few", title: "Fewer than 30 open postings at the tracked employers: treat its numbers as rough", text: "few postings" }) : null,
            H.el("span", { class: "c-field", text: r.group })),
          H.el("td", { class: "c-score" }, H.el("span", { class: "score-bar" }, H.el("span", { style: `width: ${r.score ?? 0}%` })),
            H.el("strong", { text: r.score == null ? "–" : String(r.score) })),
          H.el("td", { class: "num" }, H.el("strong", { text: r.open == null ? "–" : r.open.toLocaleString() }),
            H.el("span", { class: "sub", text: tracking && r.new_7d != null ? `${r.new_7d} new this week` : `${r.companies ?? 0} employers` })),
          H.el("td", { class: "num" }, H.el("strong", { text: money(r.pay_us) }),
            H.el("span", { class: "sub", text: r.pay_us_p25 ? `${money(r.pay_us_p25)}–${money(r.pay_us_p75)}` : r.pay_ca ? `CA ${money(r.pay_ca, "CAD")}` : "" })),
          H.el("td", { class: "num c-entry" }, H.el("strong", { text: pct(r.junior) }), H.el("span", { class: "sub", text: `junior · PhD ${pct(r.phd)}` })),
          H.el("td", { class: "num c-ai" }, H.el("strong", { class: r.tailwind == null ? "" : r.tailwind >= 0 ? "up" : "down",
            text: r.tailwind == null ? "–" : `${r.tailwind >= 0 ? "▲" : "▼"} ${Math.abs(r.tailwind).toFixed(2)}` }),
            H.el("span", { class: "sub", text: r.ai_exposure == null ? "" : `AI exposure ${pct(r.ai_exposure)}` })),
          H.el("td", { class: "c-spark" }, r.spark.length > 3 ? K.miniLine(smooth(r.spark, 3), (r.hn_yoy ?? 0) >= 0 ? "--div-warm" : "--div-cool") : null,
            H.el("span", { class: "sub", text: r.hn_yoy == null ? "" : `${signedPct(Math.exp(r.hn_yoy) - 1)} vs a year ago` }))))))));
    };
    const drawSliders = () => sliders.replaceChildren(...CRITERIA.map((c) => {
      const out = H.el("output", { text: String(w[c.key]) });
      const inp = H.el("input", { type: "range", min: "0", max: "5", step: "1", value: String(w[c.key]), "aria-label": `${c.label} weight` });
      inp.addEventListener("input", () => { w[c.key] = Number(inp.value); out.textContent = inp.value; saveW(w); draw(); });
      return H.el("label", { class: "weight", title: c.help }, H.el("span", { class: "w-name", text: c.label }), inp, out,
        H.el("span", { class: "w-help", text: c.help }));
    }));
    drawSliders();
    const groups = ["all", ...B.groups.filter((g) => B.roles.some((r) => r.group === g))];
    main.replaceChildren(
      H.el("div", { class: "day-head" }, H.el("div", {},
        H.el("h1", { text: "Jobs" }),
        H.el("div", { class: "day-meta", text: `How good each AI and tech job is right now in the US and Canada, measured from the job market: ` +
          `${(B.open_total || 0).toLocaleString()} open postings at ${B.boards} employers, ${B.hn_months} months of Hacker News hiring ads and Indeed's postings index.` }))),
      H.el("details", { class: "card weights-card", open: window.innerWidth > 700 ? "" : null },
        H.el("summary", { class: "kind", text: "What matters to you" }),
        H.el("p", { class: "viz-sub", text: "Each criterion ranks the roles against each other (0 = lowest, 100 = highest); the score is their weighted average. Drag to change what counts. Saved in this browser." }),
        sliders,
        H.el("button", { class: "link-btn", text: "Reset to defaults", onclick: () => { Object.assign(w, DEFAULT_W); saveW(w); drawSliders(); draw(); } })),
      H.el("section", { class: "card viz-card" },
        H.el("div", { class: "line-controls" },
          K.segmented(groups.map((g) => [g, g === "all" ? "All" : g]), "all", (k) => { st.group = k; draw(); }, "Group"),
          K.segmented([["score", "Score"], ["open", "Openings"], ["pay", "Pay"], ["demand", "Demand"], ["ai", "AI outlook"], ["entry", "Entry"]], "score",
            (k) => { st.sort = k; draw(); }, "Sort by")),
        body,
        H.el("p", { class: "board-key", text: `Openings: tracked employers' US/Canada postings on ${B.tracker_last ? H.fmtShort(B.tracker_last) : "–"}` +
          (B.tracker_days > 1 ? "" : " (daily snapshots started today; weekly changes appear as they build up)") +
          ". Pay: median of posted ranges. Entry: share of intern and junior postings. AI outlook: research tailwind (▲ research momentum favours the role, ▼ it points to automation). " +
          "Hiring trend: share of Hacker News hiring ads naming the role, last 3 years. Select a row for its page." })));
    draw();
  }
  const smooth = (a, k) => a.map((_, i) => { const w = a.slice(Math.max(0, i - k + 1), i + 1).filter((x) => x != null); return w.length ? w.reduce((x, y) => x + y, 0) / w.length : null; });

  // ---------------------------------------------------------------- role page: measures with their own ranges
  const DAILY = [{ key: "1W", days: 7, k: 1, words: "past week" }, { key: "1M", months: 1, k: 3, words: "past month" },
    { key: "3M", months: 3, k: 7, words: "past 3 months" }, { key: "6M", months: 6, k: 14, words: "past 6 months" },
    { key: "1Y", months: 12, k: 30, words: "past year" }, { key: "2Y", months: 24, k: 60, words: "past 2 years" }];
  const LONG = [{ key: "1M", months: 1, k: 1, words: "past month" }, { key: "3M", months: 3, k: 1, words: "past 3 months" },
    { key: "6M", months: 6, k: 7, words: "past 6 months" }, { key: "1Y", months: 12, k: 14, words: "past year" },
    { key: "2Y", months: 24, k: 30, words: "past 2 years" }, { key: "5Y", months: 60, k: 60, words: "past 5 years" },
    { key: "All", all: true, k: 90, words: "since Feb 2020" }];
  const MONTHLY = [{ key: "1Y", months: 12, k: 3, words: "past year" }, { key: "2Y", months: 24, k: 3, words: "past 2 years" },
    { key: "5Y", months: 60, k: 6, words: "past 5 years" }, { key: "All", all: true, k: 12, words: "since 2012" }];
  const view = { measure: null, range: { daily: "1M", long: "1Y", monthly: "5Y" }, ctry: "NA" };

  function measures(P, ctry) {
    const out = [], T = P.tracker;
    if (T && T.days.length) {
      const s = T[ctry];
      const payCtry = ctry === "CA" ? "CA" : "US", payCur = payCtry === "CA" ? "CAD" : "USD";
      out.push({ key: "open", label: "Openings", unit: "open postings", ranges: DAILY, kind: "mean", days: T.days, vals: s.index, bars: s.new, barsWord: "new postings",
        fmt: (v) => Math.round(v).toLocaleString(), d: (x) => Math.round(Math.abs(x)).toLocaleString(),
        about: "open postings at the tracked employers, chain-linked so a board that fails for a day or joins later does not move the line" });
      out.push({ key: "new", label: "New postings", unit: "new postings a day", ranges: DAILY, kind: "mean", days: T.days, vals: s.new.map((v, i) => (i ? v : null)),
        fmt: (v) => v.toFixed(1), d: (x) => Math.abs(x).toFixed(1), about: "postings that appeared that day at employers already tracked the day before" });
      out.push({ key: "pay", label: "Pay", unit: `${payCur} a year, median posted`, ranges: DAILY, kind: "mean", days: T.days, vals: T[payCtry].pay_mid,
        fmt: (v) => money(v, payCur), d: (x) => money(Math.abs(x), payCur), about: `the median midpoint of posted salary ranges (${payCtry === "CA" ? "Canada" : "US"})` });
    }
    if (P.hn) {
      const months = P.hn.months.map((m) => `${m}-15`);
      out.push({ key: "hn", label: "Startup demand", unit: "of hiring ads", ranges: MONTHLY, kind: "ratio", days: months, num: P.hn.ads_role, den: P.hn.ads,
        fmt: (v) => pct(v, 1), d: (x) => `${Math.abs(x * 100).toFixed(1)} pts`, dateFmt: (iso) => H.dObj(iso).toLocaleDateString("en-US", { month: "long", year: "numeric" }),
        bars: P.hn.ads_role, barsWord: "ads", about: "share of Hacker News 'Who is hiring?' ads (US and Canada) that name the role, a startup-heavy view going back to 2012" });
    }
    const ic = ctry === "CA" ? "CA" : "US", I = P.indeed_series && P.indeed_series[ic];
    if (I) {
      const start = H.dObj(I.start), days = I.v.map((_, i) => { const d = new Date(start); d.setDate(d.getDate() + i); return H.isoOf(d); });
      out.push({ key: "market", label: "Market", unit: "Indeed index (Feb 2020 = 100)", ranges: LONG, kind: "mean", days, vals: I.v,
        fmt: (v) => v.toFixed(1), d: (x) => Math.abs(x).toFixed(1),
        about: `Indeed Hiring Lab's "${P.indeed}" postings index for ${ic === "CA" ? "Canada" : "the US"}: the whole market for this kind of work, shared with other roles in the category (source: Indeed Hiring Lab, CC BY 4.0)` });
    }
    return out;
  }
  function valueAt(M, i, k) {
    let a = 0, b = 0, n = 0;
    for (let j = Math.max(0, i - k + 1); j <= i; j++) {
      if (M.kind === "ratio") { a += M.num[j] || 0; b += M.den[j] || 0; }
      else if (M.vals[j] != null) { a += M.vals[j]; n++; }
    }
    return M.kind === "ratio" ? (b ? a / b : null) : n ? a / n : null;
  }
  function ratioZ(M, i0, i1, k) {
    if (M.kind !== "ratio") return null;
    const w = (i) => { let a = 0, b = 0; for (let j = Math.max(0, i - k + 1); j <= i; j++) { a += M.num[j] || 0; b += M.den[j] || 0; } return [a, b]; };
    const [c1, n1] = w(i0), [c2, n2] = w(i1), p = (c1 + c2) / (n1 + n2), se = Math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2));
    return se ? (c2 / n2 - c1 / n1) / se : 0;
  }

  function measureCard(P) {
    const big = H.el("strong", { class: "stock-big" }), unit = H.el("span", { class: "stock-unit" });
    const chg = H.el("div", { class: "stock-change", "aria-live": "polite" }), note = H.el("div", { class: "stock-note" });
    const plot = H.el("div", { class: "stock-plot" }), how = H.el("p", { class: "viz-sub stock-how" });
    const ranges = H.el("div", { class: "stock-ranges" }), switches = H.el("div", { class: "stock-switches" });
    const card = H.el("section", { class: "card stock-card" });
    const draw = () => {
      const ms = measures(P, view.ctry);
      if (!ms.length) { card.replaceChildren(H.el("p", { class: "note", text: "No market data for this role yet." })); return; }
      const M = ms.find((m) => m.key === view.measure) || ms.find((m) => m.key === (P.tracker && P.tracker.days.length >= 20 ? "open" : "hn")) || ms[0];
      view.measure = M.key;
      const rk = M.ranges === DAILY ? "daily" : M.ranges === LONG ? "long" : "monthly";
      const r = M.ranges.find((x) => x.key === view.range[rk]) || M.ranges[0];
      const from = K.startIndex(M.days, r), vals = [];
      for (let i = from; i < M.days.length; i++) vals.push(valueAt(M, i, r.k));
      const [a, b] = K.ends(vals), base = vals[a];
      switches.replaceChildren(
        K.segmented(ms.map((m) => [m.key, m.label]), M.key, (k) => { view.measure = k; draw(); }, "Measure"),
        M.key === "hn" ? H.el("span") : K.segmented([["NA", "US + Canada"], ["US", "US"], ["CA", "Canada"]].filter(([c]) => c !== "NA" || M.key !== "market"),
          M.key === "market" && view.ctry === "NA" ? "US" : view.ctry, (k) => { view.ctry = k; draw(); }, "Country"));
      ranges.replaceChildren(K.segmented(M.ranges.map((x) => [x.key, x.key]), r.key, (k) => { view.range[rk] = k; draw(); }, "Time range"));
      const enough = vals.filter((v) => v != null).length >= 2;
      if (!enough) {
        big.textContent = base == null ? "–" : M.fmt(base); unit.textContent = M.unit;
        chg.replaceChildren(H.el("span", { class: "when", text: `Daily snapshots began ${H.fmtShort(M.days[0])}; this line fills in as they build up. Try Startup demand or Market for the long view.` }));
        note.textContent = ""; plot.replaceChildren(); how.textContent = `Line: ${M.about}.`;
        return;
      }
      const z = ratioZ(M, from + a, from + b, r.k), up = vals[b] >= base, color = up ? "--div-warm" : "--div-cool";
      const quote = (i) => {
        const v = vals[i], dv = v - base, rel = base ? dv / base : null, atEnd = i === b;
        big.textContent = M.fmt(v); unit.textContent = M.unit;
        chg.replaceChildren(...[
          H.el("span", { class: dv >= 0 ? "up" : "down", text: `${dv >= 0 ? "▲" : "▼"} ${M.d(dv)}${rel == null ? "" : ` (${Math.abs(rel * 100).toFixed(Math.abs(rel) < 0.1 ? 1 : 0)}%)`}` }),
          H.el("span", { class: "when", text: atEnd ? r.words : `since ${(M.dateFmt || K.longDate)(M.days[from + a])}` }),
          atEnd && z != null && Math.abs(z) < 2 ? H.el("span", { class: "noise", title: `z = ${z.toFixed(1)}`, text: "within noise" }) : null].filter(Boolean));
        const unitWord = M.ranges === MONTHLY ? "month" : "day";
        note.textContent = `${r.k === 1 ? `Single ${unitWord}` : `${r.k}-${unitWord} average`} · ${(M.dateFmt || K.longDate)(M.days[from + i])}`;
      };
      quote(b);
      plot.replaceChildren(K.stockChart(M.days, { from, vals }, (M.bars || []).slice(from).map((x) => x || 0), r, M, color, (i) => quote(i == null ? b : i)));
      how.textContent = `Line: ${M.about}; ${r.k === 1 ? "one point per " + (M.ranges === MONTHLY ? "month" : "day") : `each point averages the ${r.k} ${M.ranges === MONTHLY ? "months" : "days"} up to it`}` +
        ` (longer ranges average more, so the line smooths out). Dotted line: the value at the start of the range.` + (M.bars ? ` Bars: ${M.barsWord}.` : "");
    };
    card.append(H.el("div", { class: "stock-top" }, H.el("div", { class: "stock-quote" }, H.el("div", {}, big, unit), chg, note), switches), plot, ranges, how);
    draw();
    return card;
  }

  async function rolePage(main, id) {
    let P, B;
    try { [P, B] = await Promise.all([get(`data/jobs/${id}.json`), get("data/jobs.json")]); } catch (e) {
      main.replaceChildren(H.el("p", { class: "note" }, "That role does not exist. ", H.el("a", { href: "#/jobs", text: "Back to Jobs" }))); return;
    }
    const scored = scoreRoles(B.roles, loadW()), me = scored.find((r) => r.id === id) || {}, rank = scored.slice().sort((a, b) => (b.score ?? -1) - (a.score ?? -1)).findIndex((r) => r.id === id) + 1;
    const stat = (k, v, sub) => H.el("div", {}, H.el("dt", { text: k }), H.el("dd", {}, H.el("strong", { text: v }), sub ? H.el("span", { text: sub }) : null));
    const kstats = H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Key statistics" })),
      H.el("dl", { class: "kstats" },
        stat("Open postings", (P.open ?? 0).toLocaleString(), `US ${P.open_us ?? 0} · Canada ${P.open_ca ?? 0}` +
          ((P.open_us || 0) + (P.open_ca || 0) > (P.open || 0) ? " (some list both)" : "")),
        stat("Employers hiring", String(P.companies ?? 0), P.top3 == null ? "" : `top three hold ${pct(P.top3)}`),
        stat("Pay (US)", money(P.pay_us), P.pay_us_p25 ? `middle half ${money(P.pay_us_p25)}–${money(P.pay_us_p75)} · ${P.pay_us_n} ranges` : "no posted ranges"),
        stat("Pay (Canada)", money(P.pay_ca, "CAD"), P.pay_ca_n ? `${P.pay_ca_n} posted ranges` : "few posted ranges"),
        stat("Open to juniors", pct(P.junior), `interns ${pct(P.intern)} · senior titles ${pct(P.senior)}`),
        stat("Mentions a PhD", pct(P.phd), P.yrs ? `median ${P.yrs} years of experience asked` : ""),
        stat("Remote", pct(P.remote), `equity offered ${pct(P.equity)}`),
        stat("Posting age", P.age == null ? "–" : `${Math.round(P.age)} days`, "median days open (longer = harder to fill)"),
        stat("Seekers per ad", P.seekers_per_ad == null ? "–" : P.seekers_per_ad.toFixed(2), "Hacker News, last 12 months"),
        stat("US employment", P.bls_emp == null ? "–" : P.bls_emp.toLocaleString(),
          P.bls_wage ? `median wage ${money(P.bls_wage)} across all employers (BLS ${P.bls_year})` : "BLS figures pending"),
        stat("Canada outlook", P.ca_outlook == null ? "–" : OUTLOOK[Math.round(P.ca_outlook)],
          P.ca_good == null ? "" : `${pct(P.ca_good)} of regions rated good or very good (Job Bank 2025–27)`),
        stat("AI exposure", pct(P.ai_exposure), "share of the occupation's work seen done with AI (Anthropic Economic Index)"),
        stat("Robot exposure", pct(P.robot_exposure), "physical tasks robots could do (same source)"),
        stat("Score", me.score == null ? "–" : `${me.score} · #${rank} of ${scored.length}`, "with your weights on the board")));
    const crit = H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "How it scores" }),
      H.el("a", { class: "card-date", href: "#/jobs", text: "Change weights →" })),
      H.el("div", { class: "crit" }, CRITERIA.map((c) => {
        const v = me.crit ? me.crit[c.key] : null;
        return H.el("div", { class: "crit-row", title: c.help }, H.el("span", { class: "crit-name", text: c.label }),
          H.el("span", { class: "crit-bar" }, H.el("span", { style: `width: ${v == null ? 0 : Math.round(v * 100)}%` })),
          H.el("span", { class: "crit-val", text: v == null ? "–" : String(Math.round(v * 100)) }), H.el("span", { class: "crit-help", text: c.help }));
      })));
    const ex = P.exposures || [], maxC = Math.max(0.01, ...ex.map((x) => Math.abs(x.c)));
    const moves = H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "What moves this job" }),
      H.el("span", { class: "card-date", text: P.tailwind == null ? "" : `research tailwind ${P.tailwind >= 0 ? "+" : "−"}${Math.abs(P.tailwind).toFixed(2)}` })),
      H.el("p", { class: "viz-sub", text: "Research directions that matter for this role, with a signed weight: + means progress there tends to create demand for the role, − means it automates the role's tasks. " +
        "Each bar is weight × the direction's momentum (its share of new papers vs a year earlier). These weights are reviewed guesses, to be checked against postings as months of data build up." }),
      H.el("div", { class: "expo" }, ex.map((x) => H.el("a", { class: "expo-row", href: K.dirHref(x.id) },
        H.el("span", { class: "expo-name", text: x.name }),
        H.el("span", { class: `expo-w ${x.w >= 0 ? "up" : "down"}`, text: `${x.w >= 0 ? "+" : "−"}${Math.abs(x.w).toFixed(1)}` }),
        H.el("span", { class: "expo-m", text: `×${Math.pow(2, x.m).toFixed(1)} in a year` }),
        H.el("span", { class: "expo-bar" }, H.el("span", { class: x.c >= 0 ? "pos" : "neg", style: `width: ${Math.round((Math.abs(x.c) / maxC) * 50)}%` }))))));
    const hiring = H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Who's hiring" })),
      P.top_companies.length ? H.el("div", { class: "chips" }, P.top_companies.map(([n, c]) => H.el("span", { class: "chip" }, n, H.el("span", { class: "n", text: String(c) })))) :
        H.el("p", { class: "note", text: "No open postings at the tracked employers." }));
    const latest = H.el("section", { class: "card" }, H.el("div", { class: "card-top" }, H.el("span", { class: "kind", text: "Latest postings" })),
      P.recent.length ? H.el("ol", { class: "rank" }, P.recent.map((p) => H.el("li", {},
        H.safeUrl(p.url) ? H.el("a", { href: p.url, target: "_blank", rel: "noopener", text: p.title }) : H.el("span", { text: p.title }),
        H.el("span", { class: "rank-meta", text: [p.company, p.ctry.replace("|", " & "), p.pay ? `${money(+p.pay[0], p.pay[2])}–${money(+p.pay[1], p.pay[2])}` : "",
          p.published ? H.fmtShort(p.published) : ""].filter(Boolean).join(" · ") })))) : H.el("p", { class: "note", text: "None right now." }));
    main.replaceChildren(
      H.el("div", { class: "day-head" }, H.el("div", {},
        H.el("a", { class: "back", href: "#/jobs", text: "← Jobs" }),
        H.el("h1", { text: P.name }),
        H.el("div", { class: "day-meta", text: `${P.group} · ${P.about}` }))),
      measureCard(P), kstats, crit, moves, hiring, latest,
      H.el("p", { class: "note sources", text: "Sources: public job boards of the tracked employers (Greenhouse, Ashby, Lever), Hacker News 'Who is hiring?' and 'Who wants to be hired?' threads, " +
        "Indeed Hiring Lab Job Postings Index (CC BY 4.0), U.S. Bureau of Labor Statistics (OEWS), Job Bank 3-year employment outlooks (Government of Canada), " +
        "Anthropic Economic Index (AI and robot exposure), and this site's research-direction model." }));
  }

  async function render(main, route) {
    const fresh = render.last !== location.hash;
    render.last = location.hash;
    if (route.id) await rolePage(main, route.id); else await board(main);
    if (fresh) window.scrollTo({ top: 0 });
  }
  let lastW = window.innerWidth, t = null;
  window.addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      if (Math.abs(window.innerWidth - lastW) < 40 || !/^#\/jobs/.test(location.hash)) return;
      lastW = window.innerWidth;
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    }, 250);
  });
  window.AIUJobs = { init(helpers, kit) { H = helpers; K = kit; }, render };
})();
