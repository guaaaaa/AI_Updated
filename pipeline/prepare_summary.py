"""Evidence brief for the monthly trend summary (no LLM usage; one tool call).

The brief is built around FIELD-WIDE evidence, so trends describe the field rather than our picks:
  1. previous monthly summaries (continuity: what was rising, what has faded or been replaced)
  2. research: every tracked direction across ALL new arXiv papers in our categories -- the 3-month window ending
     this month vs the previous 3 months and vs a year earlier, with significance, persistence, team breadth and
     Hugging Face attention (pipeline/field_stats.py), plus emerging and fading title terms
  3. industry: reputable-outlet AI stories of the window grouped by category and company, vs the previous 3 months
  4. the month's most-upvoted papers on Hugging Face (field-level attention examples)
  5. our digest items (illustrations only: they may illustrate a trend, never establish one)
Writes work/summary_input_<id>.json (the ids the write-up may cite) for assemble_summary.py.

Usage: python3 pipeline/prepare_summary.py --id 2026-10      (omit --id: the previous month)
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field_data as FD  # noqa: E402
import field_stats as FS  # noqa: E402
from common import DAYS, SUMMARIES, WORK, load_json, month_days, today_et  # noqa: E402

pct = lambda x: "-" if x is None else f"{x:.2%}"
sgn = lambda x: "-" if x is None else f"{x:+.0%}"


def previous(mid, n=3):
    folder = SUMMARIES / "monthly"
    files = sorted(f for f in folder.glob("*.json") if f.stem < mid) if folder.exists() else []
    return [json.loads(f.read_text()) for f in files[-n:]]


def render_summary(s):
    L = [f"### {s['id']}: {s['headline']}"]
    for part in ("research", "industry"):
        p = s[part]
        L.append(f"{part.upper()} heating: {'; '.join(h['label'] for h in p['heating'])} | "
                 f"cooling: {'; '.join(h['label'] for h in p['cooling']) or '-'}")
        L += [f"- {t['title']}: {' '.join(t['body'].split())}" for t in p["themes"]]
    return "\n".join(L)


def dir_line(d, months):
    spark = " ".join(f"{v * 100:.2f}" for v in d["series"][-12:])
    att = f"; HF attention {pct(d['attention'])} of upvotes (was {pct(d['attention_prev'])})" if d["attention"] is not None else ""
    return (f"- {d['name']} [{d['id']}]: {pct(d['share'])} of new papers ({d['n']} papers, {d['teams']} teams) vs "
            f"{pct(d['share_prev'])} prev 3 mo ({sgn(d['rel_prev'])}, z {d['z_prev']}) and {pct(d['share_year_ago'])} a year "
            f"earlier ({sgn(d['rel_year'])}); above prior level in {d['months_above']}/3 months{att}\n"
            f"    monthly % of new papers, last 12 months: {spark}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--kind", default="monthly", choices=["monthly"])  # kept for compatibility
    a = ap.parse_args()
    today = today_et()
    mid = a.id or f"{today.replace(day=1) - dt.timedelta(days=1):%Y-%m}"
    first, last = month_days(mid)
    published = last + dt.timedelta(days=1)
    # make sure the field aggregates exist for every month the analysis needs (fetches what is missing)
    for m in sorted(set(FS.window(mid, 15))):
        FS.build_month(m)
    rep = FS.analyze(mid)
    W, P, Y = rep["window"], rep["prev"], rep["year_ago"]
    out = [f"# Evidence brief: monthly summary {mid}",
           f"Month {first} .. {last}; published {published}. Write as of {published} 08:30 ET.",
           f"Trend window: {W[0]}..{W[-1]} (3 months) vs previous {P[0]}..{P[-1]}"
           + (f" and the year-earlier {Y[0]}..{Y[-1]}" if Y else " (no year-earlier data)") + ".",
           "RULE: trend claims rest on sections 2-4 (field-wide). Our digest items (section 5) may only illustrate.",
           "RULE: heating/cooling labels only for directions marked RISING/NEW/FADING or categories/companies marked SHIFT; "
           "anything marked steady is noise and may appear only as context, explicitly called below the significance bar.", ""]

    out.append("## 1. Previous monthly summaries")
    prev = previous(mid)
    out += [render_summary(s) for s in prev] or ["(none: this is the first monthly summary)"]
    out.append("")

    vol = dict(rep["volume"])
    yoy = ""
    if rep["n_year_ago"]:
        yoy = f"; a year earlier {rep['n_year_ago']} ({rep['n_papers'] / rep['n_year_ago'] - 1:+.0%})"
    out += ["## 2. Research: the whole field (cite as [field stats])",
            f"New arXiv papers in our categories: {rep['n_papers']} in the window vs {rep['n_prev']} in the previous 3 months{yoy}. "
            "Monthly: " + ", ".join(f"{m} {n}" for m, n in list(vol.items())[-12:]),
            "Status rules: rising/fading = z >= 3, >= 10% relative change, held in >= 2 of 3 months, >= 15 teams, and not "
            "contradicted by the year-ago comparison. Everything else is steady (noise-level movement).", ""]
    D = rep["directions"]
    for st, title in (("new", "NEW (barely present a year ago)"), ("rising", "RISING"), ("fading", "FADING")):
        rows = sorted([d for d in D if d["status"] == st], key=lambda d: -abs(d["z_prev"]))
        out.append(f"### {title}: {len(rows)}")
        out += [dir_line(d, rep["series_months"]) for d in rows] or ["(none)"]
    steady = sorted([d for d in D if d["status"] == "steady"], key=lambda d: -d["share"])
    out.append("### LARGEST STEADY DIRECTIONS (context)")
    out += [f"- {d['name']}: {pct(d['share'])} ({sgn(d['rel_prev'])} vs prev, {sgn(d['rel_year'])} vs year ago)" for d in steady[:12]]
    att = [d for d in D if d["attention"] is not None and d["attention_prev"]]
    att.sort(key=lambda d: -(d["attention"] - d["attention_prev"]))
    out.append("### ATTENTION SHIFTS (share of Hugging Face upvotes, window vs previous; compare with publication share)")
    out += [f"- {d['name']}: {pct(d['attention'])} vs {pct(d['attention_prev'])}; publication share {sgn(d['rel_prev'])}"
            for d in att[:5] + att[-5:]]
    out.append("### EMERGING TITLE TERMS (outside or across directions; count in window vs expected from previous 3 months)")
    le = lambda flag: "at most " if flag else ""
    out += [f"- '{t['term']}': {t['now']} vs {le(t.get('prev_upper'))}{t['prev']}"
            + (f" (year ago {le(t.get('year_ago_upper'))}{t['year_ago']})" if t.get("year_ago") is not None else "")
            + f", {t['teams']} teams" for t in rep["terms_up"]] or ["(none)"]
    out.append("### FADING TITLE TERMS")
    out += [f"- '{t['term']}': {t['now']} vs {t['prev']}" for t in rep["terms_down"]] or ["(none)"]
    out.append("")

    nr = rep["news"]
    out.append("## 3. Industry: reputable-outlet AI stories (cite as [news stats])")
    if nr:
        out.append(f"Stories in the window: {nr['stories']} (previous 3 months: {nr['stories_prev'] or '-'}). Shares = share of "
                   "stories touching each category or company; the pool comes from fixed news searches, so read movement, "
                   "not absolute levels. z >= 3 marks a real shift.")
        def mark(c):  # same bar as research: z >= 3 and >= 10% relative change, else noise
            z, a, b = c["z_prev"], c["share"], c["share_prev"]
            if z is None or not b:
                return "no baseline"
            return ("SHIFT UP" if z > 0 else "SHIFT DOWN") if abs(z) >= 3 and abs(a / b - 1) >= 0.10 else "steady (noise)"
        out.append("### CATEGORIES")
        out += [f"- {c['name']}: {pct(c['share'])} of stories ({c['n']}) vs {pct(c['share_prev'])} (z {c['z_prev']}) -> {mark(c)}"
                for c in nr["categories"]]
        out.append("### COMPANIES")
        out += [f"- {c['name']}: {pct(c['share'])} ({c['n']}) vs {pct(c['share_prev'])} (z {c['z_prev']}) -> {mark(c)}"
                for c in nr["entities"][:14]]
        out.append(f"### MOST-COVERED STORIES OF {mid} (outlets)")
        out += [f"- {n} outlets | {d} | {t}" for t, n, d in nr["top"]]
    else:
        out.append("(news statistics unavailable for this window)")
    out.append("")

    hf = sorted(FD.hf_month(mid), key=lambda p: -p["up"])[:15]
    out.append("## 4. Most-upvoted papers on Hugging Face this month (field attention; cite as [paper id])")
    out += [f"[{p['id']}] {p['t']} | {p['up']} upvotes | {p['d']}" for p in hf]
    out.append("")

    featured_p, featured_n = {}, {}
    out.append("## 5. Our digest items this month (ILLUSTRATIONS ONLY; cite as [paper id] / [news id])")
    d = first
    while d <= last:
        j = load_json(DAYS / f"{d.isoformat()}.json")
        for n in (j or {}).get("news", []):
            featured_n[n["id"]] = {"title": n["title"], "date": j["date"]}
            out.append(f"[{n['id']}] NEWS {j['date']} | {n['category']} | {n['title']}")
        for p in (j or {}).get("papers", []):
            featured_p[p["id"]] = {"title": p["title"], "date": j["date"]}
            out.append(f"[{p['id']}] PAPER {j['date']} | {p['primary_tag']} | {p['title']} -- {p['tldr']}")
        d += dt.timedelta(days=1)

    allowed = {"kind": "monthly", "id": mid, "start": first.isoformat(), "end": last.isoformat(),
               "published": published.isoformat(),
               "papers": {**{p["id"]: {"title": p["t"], "date": None} for p in hf}, **featured_p}, "news": featured_n}
    WORK.mkdir(exist_ok=True)
    (WORK / f"summary_input_{mid}.json").write_text(json.dumps(allowed, ensure_ascii=False, indent=0))
    print("\n".join(out))


if __name__ == "__main__":
    main()
