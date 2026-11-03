"""Week in review (no LLM usage): the week's most-upvoted papers and most-covered stories, with no trend claims.

Built from the daily evidence snapshots (data/state/daily/, written by every daily run) and the digests, by
build_index.py, so it updates after every daily publish and is complete after Saturday's. Written to
data/weeks/<ISO week>.json.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stories  # noqa: E402
from common import DATA, DAYS, STATE, load_json, today_et, week_days, week_id  # noqa: E402

WEEKS = DATA / "weeks"


def build(wid):
    mon, sat, _ = week_days(wid)
    days = [mon + dt.timedelta(days=i) for i in range(6)]
    snaps = [s for s in (load_json(STATE / "daily" / f"{d.isoformat()}.json") for d in days) if s]
    digests = [j for j in (load_json(DAYS / f"{d.isoformat()}.json") for d in days) if j]
    if not snaps and not digests:
        return None
    featured = {p["id"]: j["date"] for j in digests for p in j.get("papers", [])}
    ours = [(n["id"], j["date"], stories.tokens(n["title"])) for j in digests for n in j.get("news", [])]
    papers = {}
    for s in snaps:
        for p in (s.get("papers") or {}).get("shortlist", []):
            r = papers.setdefault(p["id"], {"id": p["id"], "title": p["title"], "hf": 0, "org": None})
            r["hf"] = max(r["hf"], p.get("hf") or 0)
            r["org"] = r["org"] or p.get("org")
    for j in digests:  # featured papers may carry later upvote counts
        for p in j.get("papers", []):
            r = papers.setdefault(p["id"], {"id": p["id"], "title": p["title"], "hf": 0, "org": None})
            r["hf"] = max(r["hf"], (p.get("signals") or {}).get("hf_upvotes") or 0)
    top = sorted((r for r in papers.values() if r["hf"]), key=lambda r: -r["hf"])[:8]
    for r in top:
        r["featured"] = featured.get(r["id"])
    heads = {(h["t"], h["p"]): h for s in snaps for h in (s.get("news") or {}).get("headlines", [])
             if h.get("tier") != "primary"}
    st = [x for x in stories.cluster(list(heads.values())) if len(x["outlets"]) >= 3][:8]
    out_st = []
    for x in st:
        tk = stories.tokens(x["text"])
        cov = next((nid for nid, d, t in ours if len(t & tk) >= max(3, 0.5 * len(t))), None)
        out_st.append({"title": x["title"], "outlets": len(x["outlets"]), "date": x["date"], "covered": cov})
    return {"week": wid, "start": mon.isoformat(), "end": sat.isoformat(),
            "complete": bool(load_json(DAYS / f"{sat.isoformat()}.json")) or today_et() > sat,
            "digests": len(digests), "papers": top, "stories": out_st,
            "featured": {"news": sum(len(j.get("news", [])) for j in digests),
                         "papers": sum(len(j.get("papers", [])) for j in digests)}}


def build_all():
    """(Re)write every week that has snapshots or digests; return the index list, newest first."""
    weeks = set()
    for f in list((STATE / "daily").glob("*.json")) + list(DAYS.glob("*.json")):
        d = dt.date.fromisoformat(f.stem)
        if d.weekday() < 6:
            weeks.add(week_id(d))
    WEEKS.mkdir(parents=True, exist_ok=True)
    out = []
    for wid in sorted(weeks, reverse=True):
        r = build(wid)
        if not r:
            continue
        (WEEKS / f"{wid}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        out.append({"id": wid, "start": r["start"], "end": r["end"], "complete": r["complete"]})
    return out
