"""Rebuild data/index.json (what the site loads first) from data/days/*.json and data/summaries/, the Week in
review files (data/weeks/, from the daily evidence snapshots) and data/trends.json (dashboard charts) from the
field-wide monthly aggregates in data/state/field/ (pipeline/field_stats.py), plus the stock-style page data:
data/daily.json (every announcement day: all new papers, upvotes, each field) and data/fields/<slug>.json (a field's
directions, day by day) from data/state/field_daily/ (pipeline/field_daily.py)."""
import datetime as dt
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

os.environ["AIU_DOMAIN"] = "ai"   # this script builds every domain; the AI-only parts (trends, weeks) use AI's paths
sys.argv = [a for i, a in enumerate(sys.argv) if a != "--domain" and (i == 0 or sys.argv[i - 1] != "--domain")]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import field_daily as FY  # noqa: E402
import field_stats as FS  # noqa: E402
import week_review  # noqa: E402
from common import DATA, DAYS, DOMAINS, UTC, domain_paths, load_json, today_et  # noqa: E402


def byline(p):
    a = p.get("authors", [])
    s = ", ".join(a[:3]) + (" et al." if len(a) > 3 else "")
    aff = p.get("affiliations") or []
    return s + (f" · {', '.join(aff[:3])}" if aff else "")


def domain_index(did):
    """data/index.json (AI) or data/<id>/index.json: the day list, every item, tag/category counts, summaries."""
    P = domain_paths(did)
    tax = load_json(P["config"] / "taxonomy.json")
    days, items = [], []
    tag_counts, cat_counts = Counter(), Counter()
    for f in sorted(P["days"].glob("*.json"), reverse=True) if P["days"].exists() else []:
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
                          "hf": (p.get("signals") or {}).get("hf_upvotes"), "venue": (p.get("signals") or {}).get("venue")})
    groups = {}
    for t, v in tax["paper_tags"].items():
        groups.setdefault(v["group"], []).append(t)
    summaries = []
    sdir = P["summaries"]
    for f in sorted(sdir.glob("*/*.json"), key=lambda f: json.loads(f.read_text())["published"], reverse=True) if sdir.exists() else []:
        j = json.loads(f.read_text(encoding="utf-8"))
        summaries.append({"kind": j["kind"], "id": j["id"], "start": j["period"]["start"], "end": j["period"]["end"],
                          "published": j["published"], "headline": j["headline"],
                          "heating": [h["label"] for h in j["research"]["heating"] + j["industry"]["heating"]],
                          "cooling": [h["label"] for h in j["research"]["cooling"] + j["industry"]["cooling"]]})
    out = {"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "domain": did, "days": days, "items": items,
           "tag_groups": groups, "tag_counts": dict(tag_counts), "news_categories": list(tax["news_categories"]),
           "category_counts": dict(cat_counts), "summaries": summaries, "weeks": week_review.build_all() if did == "ai" else []}
    P["data"].mkdir(parents=True, exist_ok=True)
    (P["data"] / "index.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{did} index.json: {len(days)} days, {len(items)} items, {len(summaries)} summaries, {len(out['weeks'])} weeks")
    return {"latest": days[0]["date"] if days else None, "days": len(days)}


def main():
    meta = []
    for d in DOMAINS:
        info = domain_index(d["id"])
        meta.append({"id": d["id"], "name": d["name"], "tagline": d.get("tagline", ""), "trends": bool(d.get("trends")),
                     "paper_label": d.get("paper_label", "Papers"), "news": d["news"], "papers": d["papers"],
                     "index": "data/index.json" if d["id"] == "ai" else f"data/{d['id']}/index.json", **info})
    (DATA / "domains.json").write_text(json.dumps({"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "domains": meta},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    build_trends()
    try:   # the job board (data/jobs.json, data/jobs/) -- never blocks a digest
        import build_jobs
        build_jobs.build()
    except Exception as e:
        print(f"WARNING jobs build failed: {e}", file=sys.stderr)


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
            "rel_year", "z_prev", "months_above", "attention", "attention_prev", "series", "counts")   # trends.json stays light
    out = {"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "month": rep["month"], "window": rep["window"],
           "prev": rep["prev"], "year_ago": rep["year_ago"], "n_papers": rep["n_papers"], "n_prev": rep["n_prev"],
           "n_year_ago": rep["n_year_ago"], "volume": rep["volume"], "series_months": rep["series_months"],
           "directions": [{k: d[k] for k in keep} for d in rep["directions"]], "groups": rep["groups"],
           "terms_up": rep["terms_up"], "terms_down": rep["terms_down"], "news": rep["news"]}
    (DATA / "trends.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_direction_pages(rep)
    st = Counter(d["status"] for d in rep["directions"])
    print(f"trends.json: {rep['month']} window, {len(rep['series_months'])} months; " + ", ".join(f"{k} {v}" for k, v in st.items()))


def slug(group):
    return re.sub(r"[^a-z]+", "-", group.lower()).strip("-")


def featured_by_direction(dirs):
    out = {d["id"]: [] for d in dirs}
    for f in sorted(DAYS.glob("*.json"), reverse=True):
        j = json.loads(f.read_text(encoding="utf-8"))
        for p in j.get("papers", []):
            for d in dirs:
                if d["rx"].search(p["title"]):
                    out[d["id"]].append({"id": p["id"], "date": j["date"], "title": p["title"], "tldr": p["tldr"]})
    return out


def write_direction_pages(rep):
    """data/directions/<id>.json: the model numbers, top papers and our items for a direction's page;
    data/daily.json + data/fields/<slug>.json: the day-by-day series behind the stock-style charts."""
    dirs = FS.directions()
    featured = featured_by_direction(dirs)
    out_dir = DATA / "directions"
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = {f"{d['id']}.json" for d in rep["directions"]}
    for f in out_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    for d in rep["directions"]:
        page = {**d, "month": rep["month"], "window": rep["window"], "series_months": rep["series_months"],
                "featured": featured.get(d["id"], [])[:12]}
        (out_dir / f"{d['id']}.json").write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_daily(rep, featured)


def write_daily(rep, featured):
    days = FY.load_all()
    if not days:
        print("daily.json: no daily field series yet")
        return
    ks = sorted(days)
    col = lambda f: [f(days[k]) for k in ks]
    groups = sorted({d["group"] for d in rep["directions"]})
    now = dt.datetime.now(UTC).isoformat(timespec="seconds")
    daily = {"updated": now, "days": [k.isoformat() for k in ks], "n": col(lambda x: x["n"]), "hf_up": col(lambda x: x["hf_up"]),
             "groups": {g: {"slug": slug(g), "n": col(lambda x: x["groups"].get(g, 0)), "up": col(lambda x: x["hf_groups"].get(g, 0))}
                        for g in groups}}
    (DATA / "daily.json").write_text(json.dumps(daily, separators=(",", ":")), encoding="utf-8")
    out_dir = DATA / "fields"
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = {f"{slug(g)}.json" for g in groups}
    for f in out_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    for g in groups:
        members = [d for d in rep["directions"] if d["group"] == g]
        top, seen = [], set()
        for row in sorted((r for d in members for r in d.get("hf_top", [])), key=lambda r: -r[2]):
            if row[0] not in seen:
                seen.add(row[0])
                top.append(row)
        feat = sorted({f["id"]: f for d in members for f in featured.get(d["id"], [])}.values(), key=lambda f: f["date"], reverse=True)
        page = {"name": g, "slug": slug(g), "month": rep["month"], "window": rep["window"],
                "members": [{"id": d["id"], "name": d["name"], "status": d["status"], "share": d["share"], "rel_year": d["rel_year"],
                             "n": col(lambda x, i=d["id"]: x["dirs"].get(i, 0)), "up": col(lambda x, i=d["id"]: x["hf_dirs"].get(i, 0))}
                            for d in members],
                "hf_top": top[:8], "featured": feat[:12]}
        (out_dir / f"{slug(g)}.json").write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"daily.json: {len(ks)} announcement days {ks[0]} -> {ks[-1]}; {len(groups)} field pages")


if __name__ == "__main__":
    main()
