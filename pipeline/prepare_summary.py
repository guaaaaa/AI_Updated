"""Evidence brief for a weekly or monthly trend summary (no LLM usage; one tool call).

Prints, compactly:
  1. the previous summaries (continuity: what was rising, what is fading or being replaced),
  2. field-wide arXiv statistics (all new papers in our categories: topic-group shares vs baseline, rising and
     fading title terms) -- computed/updated here via arxiv_stats.py,
  3. our digest items for the period (the main evidence; cite them by id),
  4. attention outside our picks (high-signal shortlisted papers we did not feature),
  5. the most-covered news stories (headline clusters across the period's headline pools).
Writes work/summary_input_<id>.json (the ids the write-up may cite) for assemble_summary.py.

Usage: python3 pipeline/prepare_summary.py --kind weekly --id 2026-W44
       python3 pipeline/prepare_summary.py --kind monthly --id 2026-10
       (omit --id: weekly -> the week that ended yesterday; monthly -> the previous month)
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_stats as AS  # noqa: E402
from common import (DAYS, STATE, SUMMARIES, WORK, config, load_json, month_days, today_et,  # noqa: E402
                    week_days, week_id)

STOP = set("""the a an of for and or in on with to from by at as is are be its it this that after over into new says
say said will could would can may might amid about than more most just up out how why what who when report reports
ai artificial intelligence""".split())


def period(kind, pid):
    if kind == "weekly":
        mon, sat, sun = week_days(pid)
        return mon, sat, sun
    first, last = month_days(pid)
    return first, last, last + dt.timedelta(days=1)


def default_id(kind, today):
    if kind == "weekly":
        return week_id(today - dt.timedelta(days=1))
    prev = today.replace(day=1) - dt.timedelta(days=1)
    return f"{prev:%Y-%m}"


def stat_weeks(kind, pid):
    """ISO weeks whose mailings define the period, plus the baseline weeks to compare against."""
    if kind == "weekly":
        return [pid], AS.weeks_back(pid, 4)
    first, last = month_days(pid)

    def weeks_of(f, l):
        out, d = [], f
        while d <= l:
            w = week_id(d)
            mon, _, _ = week_days(w)
            in_month = sum(1 for i in range(5) if f <= mon + dt.timedelta(days=i) <= l)
            if in_month >= 3 and w not in out:
                out.append(w)
            d += dt.timedelta(days=1)
        return out
    cur = weeks_of(first, last)
    pf, pl = month_days(f"{first - dt.timedelta(days=1):%Y-%m}")
    return cur, weeks_of(pf, pl)


def digests(start, end):
    out, d = [], start
    while d <= end:
        j = load_json(DAYS / f"{d.isoformat()}.json")
        if j:
            out.append(j)
        d += dt.timedelta(days=1)
    return out


def sec(item, name):
    for s in item.get("sections", []):
        if s["heading"] == name:
            return " ".join(s["body"].split())
    return ""


def previous(kind, pid, n):
    folder = SUMMARIES / kind
    files = sorted(f for f in folder.glob("*.json") if f.stem < pid) if folder.exists() else []
    return [json.loads(f.read_text()) for f in files[-n:]]


def render_summary(s, full=True):
    L = [f"### {s['kind']} {s['id']} ({s['period']['start']} .. {s['period']['end']}): {s['headline']}"]
    for part in ("research", "industry"):
        p = s[part]
        hot = "; ".join(h["label"] for h in p["heating"])
        cold = "; ".join(h["label"] for h in p["cooling"]) or "-"
        L.append(f"{part.upper()} heating: {hot} | cooling: {cold}")
        if full:
            for t in p["themes"]:
                L.append(f"- {t['title']}: {' '.join(t['body'].split())}")
    return "\n".join(L)


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9$][a-z0-9$.\-']+", title.lower()) if w not in STOP and len(w) > 2}


def cluster_headlines(heads):
    """Greedy clustering by word overlap; returns clusters sorted by distinct-publisher count."""
    clusters = []
    for h in sorted(heads, key=lambda x: x["ts"]):
        tk = tokens(h["t"])
        if len(tk) < 3:
            continue
        best, score = None, 0.0
        for c in clusters:
            inter = len(tk & c["tokens"])
            j = inter / max(1, min(len(tk), len(c["seed"])))
            if inter >= 3 and j > score:
                best, score = c, j
        if best is not None and score >= 0.5:
            best["items"].append(h)
            best["pubs"].add(h["p"])
            best["tokens"] |= tk
        else:
            clusters.append({"seed": tk, "tokens": set(tk), "items": [h], "pubs": {h["p"]}})
    clusters.sort(key=lambda c: (-len(c["pubs"]), c["items"][0]["ts"]))
    return clusters


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["weekly", "monthly"], required=True)
    ap.add_argument("--id")
    ap.add_argument("--today", help="override 'today' (backfills)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else today_et()
    pid = a.id or default_id(a.kind, today)
    start, end, published = period(a.kind, pid)
    weekly = a.kind == "weekly"
    tax = config("taxonomy")["paper_tags"]
    out = [f"# Evidence brief: {a.kind} summary {pid}",
           f"Period: {start} .. {end} (digests Mon-Sat); published {published}. Write as of {published} 07:30 ET.", ""]

    # 1) previous summaries -------------------------------------------------------------------
    out.append("## 1. Previous summaries (continuity: what was heating up, what has cooled or been replaced)")
    prev = previous(a.kind, pid, 3)
    if weekly:
        prev_m = previous("monthly", f"{published:%Y-%m}", 1)  # the latest monthly published before this week
        prev = prev_m + prev
    else:
        prev += [s for s in previous("weekly", "9999", 99) if start.isoformat() <= s["period"]["end"]
                 and s["period"]["start"] <= end.isoformat()]
    out += [render_summary(s) for s in prev] or ["(none yet: this is the first summary of its kind)"]
    out.append("")

    # 2) field-wide arXiv statistics --------------------------------------------------------------
    cur_w, base_w = stat_weeks(a.kind, pid)
    got = AS.ensure_weeks(cur_w + base_w)
    cur = AS.combine([got[w] for w in cur_w])
    base = AS.combine([got[w] for w in base_w])
    nb = max(1, len(base_w))
    out.append(f"## 2. Field-wide arXiv statistics (ALL new papers in {', '.join(config('sources')['arxiv_categories'])}; "
               "title keyword matching, rough)")
    out.append(f"This period: {cur['n_papers']} new papers ({', '.join(cur_w)}). Baseline: {base['n_papers']} papers over "
               f"{', '.join(base_w)} (per-{'week' if weekly else 'month'} average {base['n_papers'] // (nb if weekly else 1)}). "
               "Cite as [arXiv stats].")
    if cur["n_papers"] and base["n_papers"]:
        rows = []
        for t in tax:
            c, b = cur["topics"].get(t, 0) / cur["n_papers"], base["topics"].get(t, 0) / base["n_papers"]
            rows.append((c - b, t, c, b))
        groups = sorted({v["group"] for v in tax.values()})
        out.append("Topic-group share of titles (now vs baseline): " + "; ".join(
            f"{g} {cur['groups'].get(g, 0) / cur['n_papers']:.1%} vs {base['groups'].get(g, 0) / base['n_papers']:.1%}"
            for g in groups))
        rows.sort(reverse=True)
        fmt = lambda r: f"{r[1]} {r[2]:.1%} (was {r[3]:.1%})"
        out.append("Tags gaining share: " + "; ".join(fmt(r) for r in rows[:6] if r[0] > 0))
        out.append("Tags losing share: " + "; ".join(fmt(r) for r in rows[::-1][:6] if r[0] < 0))
        up, down = AS.movers(cur, base, min_count=8 if weekly else 20)
        out.append("Rising title terms (count now vs expected from baseline): " +
                   "; ".join(f"'{m['term']}' {m['now']} vs {m['base']}" for m in up))
        out.append("Fading title terms: " + "; ".join(f"'{m['term']}' {m['now']} vs {m['base']}" for m in down))
        if weekly:
            series = [AS.load_week(w) for w in AS.weeks_back(pid, 7) + [pid]]
            series = [w for w in series if w and w.get("n_papers")]
            out.append("Weekly group shares, oldest -> newest (" + ", ".join(w["week"][-3:] for w in series) + "):")
            for g in groups:
                out.append(f"  {g}: " + " ".join(f"{w['groups'].get(g, 0) / w['n_papers']:.1%}" for w in series))
    else:
        out.append("(arXiv statistics unavailable for this period)")
    out.append("")

    # 3) our digest items --------------------------------------------------------------------------
    days = digests(start, end)
    featured_p, featured_n = {}, {}
    out.append(f"## 3. Our digest items ({len(days)} digests) -- the main evidence; cite as [paper id] / [news id]")
    for j in days:
        for n in j.get("news", []):
            featured_n[n["id"]] = {"title": n["title"], "date": j["date"]}
            if weekly:
                out.append(f"[{n['id']}] NEWS {j['date']} | {n['category']} | {n['title']}\n  TL;DR: {n['tldr']}\n"
                           f"  Why it matters: {sec(n, 'Why it matters')}")
            else:
                out.append(f"[{n['id']}] NEWS {j['date']} | {n['category']} | {n['title']} -- {n['tldr']}")
        for p in j.get("papers", []):
            featured_p[p["id"]] = {"title": p["title"], "date": j["date"]}
            sig = p.get("signals", {})
            s = ", ".join(x for x in [f"HF {sig['hf_upvotes']}" if sig.get("hf_upvotes") else "",
                                      sig.get("org") or ""] if x)
            if weekly:
                out.append(f"[{p['id']}] PAPER {j['date']} | {', '.join(p['tags'])} | {p['title']}"
                           + (f" ({s})" if s else "") + f"\n  TL;DR: {p['tldr']}\n  Why it matters: {sec(p, 'Why it matters')}")
            else:
                out.append(f"[{p['id']}] PAPER {j['date']} | {', '.join(p['tags'])} | {p['title']} -- {p['tldr']}")
    out.append("")

    # 4) attention outside our picks -----------------------------------------------------------------
    snaps, d = [], start
    while d <= end:
        s = load_json(STATE / "daily" / f"{d.isoformat()}.json")
        if s:
            snaps.append(s)
        d += dt.timedelta(days=1)
    seen = defaultdict(lambda: {"days": 0})
    for s in snaps:
        for p in (s.get("papers") or {}).get("shortlist", []):
            r = seen[p["id"]]
            r.update({"id": p["id"], "title": p["title"], "org": p.get("org") or r.get("org")})
            r["days"] += 1
            r["hf"] = max(r.get("hf") or 0, p.get("hf") or 0)
            r["hot"] = min(r.get("hot") or 999, p.get("hot") or 999)
    others = [r for r in seen.values() if r["id"] not in featured_p]
    others.sort(key=lambda r: (-(r["hf"] or 0) - 15 * (r["hot"] < 999) - 5 * r["days"]))
    k = 20 if weekly else 30
    out.append(f"## 4. High-attention papers we did NOT feature (from {len(snaps)} daily shortlists; cite as [paper id])")
    for r in others[:k]:
        sig = [f"HF {r['hf']}" if r["hf"] else "", f"alphaXiv hot #{r['hot']}" if r["hot"] < 999 else "",
               f"shortlisted {r['days']}d" if r["days"] > 1 else "", r.get("org") or ""]
        out.append(f"[{r['id']}] {r['title']} | " + ", ".join(x for x in sig if x))
    if not others:
        out.append("(no shortlist snapshots for this period)")
    out.append("")

    # 5) most-covered news stories ----------------------------------------------------------------------
    heads = [h for s in snaps for h in (s.get("news") or {}).get("headlines", []) if h.get("tier") != "primary"]
    prim = [h for s in snaps for h in (s.get("news") or {}).get("headlines", []) if h.get("tier") == "primary"]
    uniq = {(h["t"], h["p"]): h for h in heads}
    clusters = cluster_headlines(list(uniq.values()))
    out.append(f"## 5. Most-covered news stories ({len(uniq)} reputable headlines; outlets = distinct publishers). "
               "Leads for context, not citable by themselves: cite a source you read [S1] or our news items.")
    for c in clusters[:25 if weekly else 35]:
        pubs = sorted(c["pubs"])
        out.append(f"- {len(pubs)} outlets | {c['items'][0]['ts'][:10]} | {c['items'][0]['t']} "
                   f"({', '.join(pubs[:5])}{', ...' if len(pubs) > 5 else ''})")
    if prim:
        out.append("Official posts in the period (labs and companies): " + "; ".join(
            f"{h['p']}: {h['t']}" for h in sorted({(h['t'], h['p']): h for h in prim}.values(), key=lambda x: x["ts"])[-30:]))
    out.append("")

    allowed = {"kind": a.kind, "id": pid, "start": start.isoformat(), "end": end.isoformat(),
               "published": published.isoformat(),
               "papers": {**{r["id"]: {"title": r["title"], "date": None} for r in others}, **featured_p},
               "news": featured_n}
    WORK.mkdir(exist_ok=True)
    (WORK / f"summary_input_{pid}.json").write_text(json.dumps(allowed, ensure_ascii=False, indent=0))
    print("\n".join(out))


if __name__ == "__main__":
    main()
