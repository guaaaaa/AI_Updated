"""Rebuild data/index.json (what the site loads first) from data/days/*.json and data/summaries/, the Week in
review files (data/weeks/, from the daily evidence snapshots) and data/trends.json (dashboard charts) from the
field-wide monthly aggregates in data/state/field/ (pipeline/field_stats.py)."""
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field_stats as FS  # noqa: E402
import week_review  # noqa: E402
from common import DATA, DAYS, SUMMARIES, UTC, config, today_et  # noqa: E402


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
           "category_counts": dict(cat_counts), "summaries": summaries, "weeks": week_review.build_all()}
    (DATA / "index.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"index.json: {len(days)} days, {len(items)} items, {len(summaries)} summaries, {len(out['weeks'])} weeks")
    build_trends()


def build_trends():
    """Dashboard data: the field-wide trend report for the latest complete month with a full 3-month window."""
    have = sorted(f.stem for f in FS.OUT.glob("*.json")) if FS.OUT.exists() else []
    cur = f"{today_et():%Y-%m}"
    ok = [m for m in have if m < cur and all(w in have for w in FS.window(m))]
    if not ok:
        print("trends.json: no field aggregates yet")
        return
    rep = FS.analyze(ok[-1])
    keep = ("id", "name", "group", "status", "n", "teams", "share", "share_prev", "share_year_ago", "rel_prev",
            "rel_year", "z_prev", "months_above", "attention", "attention_prev", "series", "counts")
    out = {"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "month": rep["month"], "window": rep["window"],
           "prev": rep["prev"], "year_ago": rep["year_ago"], "n_papers": rep["n_papers"], "n_prev": rep["n_prev"],
           "n_year_ago": rep["n_year_ago"], "volume": rep["volume"], "series_months": rep["series_months"],
           "directions": [{k: d[k] for k in keep} for d in rep["directions"]], "groups": rep["groups"],
           "terms_up": rep["terms_up"], "terms_down": rep["terms_down"], "news": rep["news"]}
    (DATA / "trends.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    st = Counter(d["status"] for d in rep["directions"])
    print(f"trends.json: {rep['month']} window, {len(rep['series_months'])} months; " + ", ".join(f"{k} {v}" for k, v in st.items()))


if __name__ == "__main__":
    main()
