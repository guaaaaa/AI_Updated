"""Job board page data (no LLM usage): data/jobs.json (the board) and data/jobs/<role>.json (one page per role), from
the daily tracker (data/state/jobs/), Hacker News and Indeed history, AI and robot exposure by occupation, and the
field model's research directions (data/trends.json).

Research tailwind (a heuristic, shown as such): each role has signed weights on research directions
(config/jobs.json). Momentum m = log2 of a direction's share of new papers now vs a year earlier, clipped to +-2.
Tailwind = (sum of w*m over demand-creating directions + s * sum of w*m over automating ones) / sum |w|, where
s = the role's observed AI exposure / the average across roles (automation pressure bites harder where AI already
does more of the work).
"""
import csv
import datetime as dt
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jobs_classify as JC  # noqa: E402
from common import DATA, STATE, UTC  # noqa: E402

J = STATE / "jobs"
METRICS = ("open", "chain", "new", "closed", "closed_days", "companies", "top3", "pay_mid", "pay_p25", "pay_p75", "pay_n",
           "junior", "senior", "intern", "phd", "remote", "equity", "yrs", "age")


def _load(name, default=None):
    p = J / name
    return json.loads(p.read_text()) if p.exists() else default


def tracker():
    lines = []
    for f in sorted((J / "daily").glob("*.jsonl")) if (J / "daily").exists() else []:
        lines += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    lines.sort(key=lambda l: l["date"])
    return lines


def series_for(lines, rid):
    out = {"days": [l["date"] for l in lines]}
    for c in ("NA", "US", "CA"):
        rows = [l["roles"].get(rid, {}).get(c, {}) for l in lines]
        s = {m: [r.get(m) for r in rows] for m in METRICS}
        # comparable-panel open postings: chain-linked, scaled so the latest day equals today's count
        idx, v = [], 1.0
        for k, r in enumerate(rows):
            if k and r.get("chain"):
                v *= r["chain"]
            idx.append(v)
        last = rows[-1].get("open") if rows else None
        s["index"] = [round(x / idx[-1] * last, 1) if last else None for x in idx] if rows else []
        out[c] = s
    return out


def log_ratio(a, b):
    return math.log(a / b) if a and b else None


def build():
    roles = JC.roles()
    lines = tracker()
    hn, ind = _load("hn.json"), _load("indeed.json", {"series": {}})
    expo = _load("exposure.json", {})
    T = json.loads((DATA / "trends.json").read_text()) if (DATA / "trends.json").exists() else {"directions": []}
    dirs = {d["id"]: d for d in T.get("directions", [])}
    reg = []
    if (J / "open.tsv").exists():
        with open(J / "open.tsv", newline="", encoding="utf-8") as f:
            reg = list(csv.DictReader(f, delimiter="\t"))

    def exposure(r, kind):
        vals = [expo[s][kind] for s in r.get("soc", []) if s in expo and expo[s].get(kind) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None
    ai_mean = statistics.mean([x for x in (exposure(r, "ai") for r in roles) if x is not None] or [0.3])

    def momentum(did):
        d = dirs.get(did)
        if not d or d.get("rel_year") is None:
            return None
        return max(-2.0, min(2.0, math.log2(max(1e-3, 1 + d["rel_year"]))))

    board, out_dir = [], DATA / "jobs"
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = set()
    for r in roles:
        rid = r["id"]
        ai = exposure(r, "ai")
        scale = (ai / ai_mean) if ai is not None else 1.0
        contrib = []
        for did, w in r.get("exposures", {}).items():
            m = momentum(did)
            if m is None:
                continue
            c = w * m * (scale if w < 0 else 1.0)
            contrib.append({"id": did, "name": dirs[did]["name"], "w": w, "m": round(m, 3), "c": round(c, 3), "status": dirs[did]["status"]})
        tw = round(sum(x["c"] for x in contrib) / sum(abs(x["w"]) for x in contrib), 3) if contrib else None
        contrib.sort(key=lambda x: -abs(x["c"]))

        # Hacker News (North America): share of hiring ads naming the role, and seekers per ad
        h = None
        if hn:
            hr = hn["roles"].get(rid, {})
            ads, ads_r = hn["ads_na"], hr.get("ads_na", [])
            seek, seek_r = hn["seekers_na"], hr.get("seekers_na", [])
            months = hn["months"]
            share = lambda a, b, k0, k1: (sum(a[k0:k1]) / sum(b[k0:k1])) if sum(b[k0:k1]) else None
            n = len(months)
            h = {"months": months, "ads": ads, "ads_role": ads_r, "seekers": seek, "seekers_role": seek_r,
                 "share_6m": share(ads_r, ads, n - 6, n), "share_6m_ya": share(ads_r, ads, n - 18, n - 12),
                 "seekers_per_ad": (sum(seek_r[n - 12:]) / sum(ads_r[n - 12:])) if sum(ads_r[n - 12:]) else None}
            # small roles have few ads: add 3 pseudo-ads to both halves so a handful of ads cannot swing the trend
            a1, b1, a0, b0 = sum(ads_r[n - 6:n]), sum(ads[n - 6:n]), sum(ads_r[n - 18:n - 12]), sum(ads[n - 18:n - 12])
            h["yoy"] = log_ratio((a1 + 3) / b1, (a0 + 3) / b0) if b1 and b0 else None
        # Indeed category (market-wide reference)
        cat = r.get("indeed")
        idd = {"category": cat}
        for c in ("US", "CA"):
            s = ind["series"].get(f"{c}|{cat}|total")
            if s:
                v = s["v"]
                idd[c] = s
                idd[f"{c}_1y"] = log_ratio(statistics.mean(v[-30:]), statistics.mean(v[-395:-365])) if len(v) > 400 else None
                idd[f"{c}_6m"] = log_ratio(statistics.mean(v[-30:]), statistics.mean(v[-213:-183])) if len(v) > 220 else None
        tr = series_for(lines, rid) if lines else None
        latest = {c: (lines[-1]["roles"].get(rid, {}).get(c, {}) if lines else {}) for c in ("NA", "US", "CA")}
        t30 = None
        if tr and len(tr["days"]) >= 28:
            ix = tr["NA"]["index"]
            t30 = log_ratio(ix[-1], ix[-28])
        new7 = sum(x or 0 for x in tr["NA"]["new"][-7:]) if tr else None
        posts = [p for p in reg if p["role"] == rid]
        comp = Counter(p["company"] for p in posts).most_common(12)
        recent = sorted(posts, key=lambda p: (p.get("published") or "", p["key"]), reverse=True)[:15]
        demand = [x for x in ((h or {}).get("yoy"), idd.get("US_6m"), t30) if x is not None]
        row = {"id": rid, "name": r["name"], "group": r["group"], "about": r["about"], "indeed": cat,
               "open": latest["NA"].get("open"), "open_us": latest["US"].get("open"), "open_ca": latest["CA"].get("open"),
               "new_7d": new7, "companies": latest["NA"].get("companies"), "top3": latest["NA"].get("top3"),
               "pay_us": latest["US"].get("pay_mid"), "pay_us_p25": latest["US"].get("pay_p25"), "pay_us_p75": latest["US"].get("pay_p75"),
               "pay_us_n": latest["US"].get("pay_n"), "pay_ca": latest["CA"].get("pay_mid"), "pay_ca_n": latest["CA"].get("pay_n"),
               "junior": latest["NA"].get("junior"), "intern": latest["NA"].get("intern"), "senior": latest["NA"].get("senior"),
               "phd": latest["NA"].get("phd"), "yrs": latest["NA"].get("yrs"), "remote": latest["NA"].get("remote"),
               "equity": latest["NA"].get("equity"), "age": latest["NA"].get("age"),
               "hn_share": (h or {}).get("share_6m"), "hn_yoy": (h or {}).get("yoy"), "seekers_per_ad": (h or {}).get("seekers_per_ad"),
               "indeed_us_6m": idd.get("US_6m"), "indeed_us_1y": idd.get("US_1y"), "indeed_ca_1y": idd.get("CA_1y"), "tracker_30d": t30,
               "demand": round(sum(demand) / len(demand), 4) if demand else None,
               "ai_exposure": ai, "robot_exposure": exposure(r, "robot"), "tailwind": tw,
               "spark": [round(a / b, 4) if b else None for a, b in zip((h or {}).get("ads_role", [])[-36:], (h or {}).get("ads", [])[-36:])] if h else []}
        board.append(row)
        page = {**row, "soc": r.get("soc"), "noc": r.get("noc"), "tracker": tr, "hn": h, "indeed_series": {c: idd.get(c) for c in ("US", "CA")},
                "exposures": contrib, "top_companies": comp,
                "recent": [{"title": p["title"], "company": p["company"], "ctry": p["ctry"], "url": p.get("url") or None, "published": p.get("published"),
                            "pay": [p["pmin"], p["pmax"], p["cur"]] if p.get("pmin") else None, "level": p["level"]} for p in recent]}
        (out_dir / f"{rid}.json").write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        keep.add(f"{rid}.json")
    for f in out_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    meta = {"updated": dt.datetime.now(UTC).isoformat(timespec="seconds"), "tracker_days": len(lines),
            "tracker_since": lines[0]["date"] if lines else None, "tracker_last": lines[-1]["date"] if lines else None,
            "boards": lines[-1]["boards_ok"] if lines else 0, "hn_months": len(hn["months"]) if hn else 0,
            "open_total": lines[-1]["roles"]["_tracked"]["NA"]["open"] if lines else None,
            "groups": json.loads((JC.CONFIG / "jobs.json").read_text())["groups"], "roles": board}
    (DATA / "jobs.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"jobs.json: {len(board)} roles; tracker {meta['tracker_days']} days; {meta['open_total']} open postings")


if __name__ == "__main__":
    build()
