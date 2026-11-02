"""Rebuild data/index.json (what the site loads first) from data/days/*.json."""
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, DAYS, UTC, config  # noqa: E402


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
                          "primary_tag": p["primary_tag"], "tags": p["tags"], "byline": byline(p)})
    groups = {}
    for t, v in tax["paper_tags"].items():
        groups.setdefault(v["group"], []).append(t)
    out = {"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "days": days, "items": items,
           "tag_groups": groups, "tag_counts": dict(tag_counts), "news_categories": list(tax["news_categories"]),
           "category_counts": dict(cat_counts)}
    (DATA / "index.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"index.json: {len(days)} days, {len(items)} items")


if __name__ == "__main__":
    main()
