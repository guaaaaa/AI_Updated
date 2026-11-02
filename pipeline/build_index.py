"""Rebuild data/index.json (what the site loads first) from data/days/*.json and data/summaries/,
and data/trends.json (dashboard charts) from data/state/arxiv_weekly/ (field-wide arXiv statistics)."""
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arxiv_stats as AS  # noqa: E402
from common import DATA, DAYS, STATE, SUMMARIES, UTC, config, week_days  # noqa: E402


def byline(p):
    a = p.get("authors", [])
    s = ", ".join(a[:3]) + (" et al." if len(a) > 3 else "")
    aff = p.get("affiliations") or []
    return s + (f" · {', '.join(aff[:3])}" if aff else "")


def main():
    tax = config("taxonomy")
    days, items = [], []
    tag_counts, cat_counts = Counter(), Counter()
    for f in sorted(DAYS.glob("*.json"), reverse=True):
        j = json.loads(f.read_text(encoding="utf-8"))
        days.append({"date": j["date"], "edition": j["edition"], "news": len(j.get("news", [])),
                     "papers": len(j.get("papers", [])), "backfill": bool(j.get("backfill"))})
        for n in j.get("news", []):
            cat_counts[n["category"]] += 1
            items.append({"id": n["id"], "date": j["date"], "type": "news", "title": n["title"], "tldr": n["tldr"],
                          "category": n["category"], "byline": ", ".join(s["name"] for s in n["sources"][:3])})
        for p in j.get("papers", []):
            tag_counts.update(p["tags"])
            items.append({"id": p["id"], "date": j["date"], "type": "paper", "title": p["title"], "tldr": p["tldr"],
                          "primary_tag": p["primary_tag"], "tags": p["tags"], "byline": byline(p),
                          "hf": (p.get("signals") or {}).get("hf_upvotes")})
    groups = {}
    for t, v in tax["paper_tags"].items():
        groups.setdefault(v["group"], []).append(t)
    summaries = []
    for f in sorted(SUMMARIES.glob("*/*.json"), key=lambda f: json.loads(f.read_text())["published"], reverse=True):
        j = json.loads(f.read_text(encoding="utf-8"))
        summaries.append({"kind": j["kind"], "id": j["id"], "start": j["period"]["start"], "end": j["period"]["end"],
                          "published": j["published"], "headline": j["headline"],
                          "heating": [h["label"] for h in j["research"]["heating"] + j["industry"]["heating"]],
                          "cooling": [h["label"] for h in j["research"]["cooling"] + j["industry"]["cooling"]]})
    out = {"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "days": days, "items": items,
           "tag_groups": groups, "tag_counts": dict(tag_counts), "news_categories": list(tax["news_categories"]),
           "category_counts": dict(cat_counts), "summaries": summaries}
    (DATA / "index.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"index.json: {len(days)} days, {len(items)} items, {len(summaries)} summaries")
    build_trends(groups)


def build_trends(groups):
    """Weekly field-wide shares per tag group / tag, plus rising and fading terms for each week and month."""
    weeks = [json.loads(f.read_text()) for f in (STATE / "arxiv_weekly").glob("*.json")]
    weeks = [w for w in sorted(weeks, key=lambda w: w["week"]) if w.get("n_papers")]
    by_id = {w["week"]: w for w in weeks}
    series = []
    for w in weeks:
        n = w["n_papers"]
        base = AS.combine([by_id.get(x) for x in AS.weeks_back(w["week"], 4)])
        up, down = AS.movers(AS.combine([w]), base) if base["n_papers"] else ([], [])
        series.append({"week": w["week"], "start": w["mailing_dates"][0] if w["mailing_dates"] else None,
                       "n_papers": n,
                       "groups": {g: round(w["groups"].get(g, 0) / n, 4) for g in groups},
                       "tags": {t: round(w["topics"].get(t, 0) / n, 4) for ts in groups.values() for t in ts},
                       "rising": up[:10], "fading": down[:8]})
    months = {}
    for w in weeks:  # a week belongs to the month holding most of its mailings (its Wednesday)
        months.setdefault(f"{week_days(w['week'])[0] + dt.timedelta(days=2):%Y-%m}", []).append(w)
    mrows, prev = [], None
    for m in sorted(months):
        cur = AS.combine(months[m])
        up, down = AS.movers(cur, prev, min_count=20) if prev and prev["n_papers"] else ([], [])
        mrows.append({"month": m, "n_papers": cur["n_papers"], "weeks": [w["week"] for w in months[m]],
                      "rising": up[:12], "fading": down[:10]})
        prev = cur
    out = {"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "groups": groups,
           "weeks": series, "months": mrows}
    (DATA / "trends.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"trends.json: {len(series)} weeks, {len(mrows)} months of field statistics")


if __name__ == "__main__":
    main()
