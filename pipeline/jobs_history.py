"""Long-run job-market history (no LLM usage) for the job pages, cached raw in work/jobs/ and aggregated into
data/state/jobs/:

  hn      Hacker News "Ask HN: Who is hiring?" (employers, since 2011) and "Who wants to be hired?" (job seekers)
          monthly threads, via the free Algolia HN API. Each top-level comment is one ad; we count ads matching
          each role (config/jobs.json patterns) and US/Canada locations -> hn.json {months, ads, seekers, roles}
  indeed  Indeed Hiring Lab job postings index by occupational category, US and Canada, daily since Feb 2020
          (CC BY 4.0, cite "Indeed Hiring Lab"), raw CSVs from github.com/hiring-lab/job_postings_tracker -> indeed.json

Usage: python3 pipeline/jobs_history.py --hn [--refresh-last 2] --indeed --exposure   (full rebuild)
       daily runs call hn_update() and indeed() from fetch_jobs.py on Mondays and the first days of a month
"""
import argparse
import csv
import datetime as dt
import gzip
import html
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import STATE, WORK, http_get  # noqa: E402

CACHE = WORK / "jobs"
OUT = STATE / "jobs"
KINDS = {"hiring": "Who is hiring", "seekers": "Who wants to be hired"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _plain(h):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", (h or "").replace("<p>", "\n"))).split())


# ---------------------------------------------------------------- Hacker News
def hn_threads(kind):
    """[(month 'YYYY-MM', story id)] for every monthly thread of a kind, posted by the whoishiring account."""
    out, page = {}, 0
    while True:
        q = f"https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=100&page={page}"
        hits = json.loads(http_get(q, timeout=60)).get("hits", [])
        if not hits:
            break
        for h in hits:
            m = re.match(rf"Ask HN: {KINDS[kind]}\?? \((\w+) (\d{{4}})\)", h.get("title") or "")
            if m:
                mid = dt.datetime.strptime(f"{m.group(1)} {m.group(2)}", "%B %Y").strftime("%Y-%m")
                out.setdefault(mid, int(h["objectID"]))
        page += 1
        time.sleep(0.5)
    return sorted(out.items())


def hn_fetch(refresh_last=2):
    """Cache each thread's top-level comments (the ads) as work/jobs/hn/<kind>_<YYYY-MM>.json.gz."""
    for kind in KINDS:
        threads = hn_threads(kind)
        log(f"  HN {kind}: {len(threads)} monthly threads {threads[0][0]} -> {threads[-1][0]}")
        for k, (mid, sid) in enumerate(threads):
            path = CACHE / "hn" / f"{kind}_{mid}.json.gz"
            if path.exists() and k < len(threads) - refresh_last:
                continue
            try:
                item = json.loads(http_get(f"https://hn.algolia.com/api/v1/items/{sid}", timeout=120))
            except Exception as e:
                log(f"  WARNING HN {kind} {mid}: {e}")
                continue
            ads = [{"id": c["id"], "t": _plain(c.get("text"))[:4000]} for c in item.get("children", [])
                   if c.get("text") and c.get("author")]   # deleted comments have no author
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps(ads, ensure_ascii=False).encode()))
            time.sleep(0.5)


def _hn_counts(ads, roles, JC):
    counts, counts_na, n_na = {r["id"]: 0 for r in roles}, {r["id"]: 0 for r in roles}, 0
    for a in ads:
        is_na = JC.north_america(a["t"])
        n_na += is_na
        for rid in JC.roles_in_text(a["t"][:1500], roles):   # the role list sits at the top of an ad
            counts[rid] += 1
            counts_na[rid] += is_na
    return len(ads), n_na, counts, counts_na


def hn_update(last=2):
    """Daily-run refresh: re-fetch the latest `last` months of both threads and merge them into hn.json."""
    import jobs_classify as JC
    path = OUT / "hn.json"
    if not path.exists():
        return
    H = json.loads(path.read_text())
    roles = JC.roles()
    for kind, key in (("hiring", "ads"), ("seekers", "seekers")):
        for mid, sid in hn_threads(kind)[-last:]:
            item = json.loads(http_get(f"https://hn.algolia.com/api/v1/items/{sid}", timeout=120))
            ads = [{"id": c["id"], "t": _plain(c.get("text"))[:4000]} for c in item.get("children", []) if c.get("text") and c.get("author")]
            if mid not in H["months"]:
                H["months"].append(mid)
                for k in ("ads", "ads_na", "seekers", "seekers_na"):
                    H[k].append(0)
                for r in H["roles"].values():
                    for k in ("ads", "ads_na", "seekers", "seekers_na"):
                        r[k].append(0)
            i = H["months"].index(mid)
            n, n_na, counts, counts_na = _hn_counts(ads, roles, JC)
            H[key][i], H[key + "_na"][i] = n, n_na
            for r in roles:
                rr = H["roles"].setdefault(r["id"], {k: [0] * len(H["months"]) for k in ("ads", "ads_na", "seekers", "seekers_na")})
                rr[key][i], rr[key + "_na"][i] = counts[r["id"]], counts_na[r["id"]]
            time.sleep(0.5)
    path.write_text(json.dumps(H, separators=(",", ":")))
    log(f"  hn.json: refreshed {H['months'][-last:]}")


def hn_aggregate():
    import jobs_classify as JC
    roles = JC.roles()
    months = sorted({p.stem.split("_")[1].split(".")[0] for p in (CACHE / "hn").glob("*.json.gz")})
    out = {"source": "Hacker News 'Who is hiring?' / 'Who wants to be hired?' threads (Algolia HN API)",
           "months": months, "ads": [], "ads_na": [], "seekers": [], "seekers_na": [],
           "roles": {r["id"]: {"ads": [], "ads_na": [], "seekers": [], "seekers_na": []} for r in roles}}
    for mid in months:
        for kind, key in (("hiring", "ads"), ("seekers", "seekers")):
            path = CACHE / "hn" / f"{kind}_{mid}.json.gz"
            ads = json.loads(gzip.decompress(path.read_bytes())) if path.exists() else []
            n, n_na, counts, counts_na = _hn_counts(ads, roles, JC)
            out[key].append(n)
            out[key + "_na"].append(n_na)
            for r in roles:
                out["roles"][r["id"]][key].append(counts[r["id"]])
                out["roles"][r["id"]][key + "_na"].append(counts_na[r["id"]])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hn.json").write_text(json.dumps(out, separators=(",", ":")))
    log(f"  hn.json: {len(months)} months {months[0]} -> {months[-1]}")


# ---------------------------------------------------------------- Indeed Hiring Lab
INDEED_RAW = "https://raw.githubusercontent.com/hiring-lab/job_postings_tracker/master"


def indeed():
    """Category indices for US and Canada (total and new postings), from a shallow clone of the public repo."""
    repo = CACHE / "indeed"
    for c in ("US", "CA"):
        for name in (f"job_postings_by_sector_{c}.csv", f"aggregate_job_postings_{c}.csv"):
            (repo / c).mkdir(parents=True, exist_ok=True)
            (repo / c / name).write_text(http_get(f"{INDEED_RAW}/{c}/{name}", timeout=180))
    out = {"source": "Indeed Hiring Lab, Job Postings Index (CC BY 4.0)", "note": "100 = Feb 1, 2020; 7-day trailing "
           "average, seasonally adjusted", "series": {}}
    import jobs_classify as JC
    wanted = {r["indeed"] for r in JC.roles()}
    for c in ("US", "CA"):
        rows = {}
        with open(repo / c / f"job_postings_by_sector_{c}.csv", newline="") as f:
            for r in csv.DictReader(f):
                key = f"{c}|{r['display_name']}|{'new' if r['variable'].startswith('new') else 'total'}"
                rows.setdefault(key, []).append((r["date"], float(r["indeed_job_postings_index"])))
        with open(repo / c / f"aggregate_job_postings_{c}.csv", newline="") as f:
            for r in csv.DictReader(f):
                var = r.get("variable") or "total postings"
                key = f"{c}|All postings|{'new' if var.startswith('new') else 'total'}"
                val = r.get("indeed_job_postings_index_SA") or r.get("indeed_job_postings_index")
                if val:
                    rows.setdefault(key, []).append((r["date"], float(val)))
        for key, pts in rows.items():
            _, cat, var = key.split("|")
            if var != "total" or (cat not in wanted and cat != "All postings"):
                continue
            pts.sort()
            out["series"][key] = {"start": pts[0][0], "v": [round(v, 1) for _, v in pts]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "indeed.json").write_text(json.dumps(out, separators=(",", ":")))
    log(f"  indeed.json: {len(out['series'])} series")


# ---------------------------------------------------------------- AI and robot exposure by occupation
AEI = "https://huggingface.co/datasets/Anthropic/EconomicIndex/resolve/main/"


def exposure():
    """Anthropic Economic Index: observed AI exposure (share of an occupation's work seen done with Claude) and robot
    exposure (0-3, rescaled to 0-1) by 6-digit SOC code -> exposure.json."""
    d = CACHE / "aei"
    d.mkdir(parents=True, exist_ok=True)
    for f in ("labor_market_impacts/job_exposure.csv", "robot_exposure/robot_exposure_occupations.csv"):
        path = d / f.split("/")[-1]
        if not path.exists():
            path.write_text(http_get(AEI + f, timeout=120))
    out = {}
    with open(d / "job_exposure.csv", newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["occ_code"], {"title": r["title"]})["ai"] = float(r["observed_exposure"])
    robot = {}
    with open(d / "robot_exposure_occupations.csv", newline="") as f:
        for r in csv.DictReader(f):
            robot.setdefault(r["onetsoc_code"][:7], []).append(float(r["robot_exposure_index"]) / 3)
    for soc, v in robot.items():
        out.setdefault(soc, {})["robot"] = round(sum(v) / len(v), 4)
    out["_source"] = {"ai": "Anthropic Economic Index, labor_market_impacts/job_exposure.csv (observed_exposure)",
                      "robot": "Anthropic Economic Index, robot_exposure_occupations.csv (index 0-3, rescaled to 0-1)"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "exposure.json").write_text(json.dumps(out, separators=(",", ":")))
    log(f"  exposure.json: {len(out) - 1} occupations")


# ---------------------------------------------------------------- official statistics
def bls():
    """BLS Occupational Employment and Wage Statistics (US, national): employment and annual median wage for every
    SOC code the roles use -> bls.json. Uses BLS_API_KEY (v2) when set, else the keyless v1 API (25 series a call)."""
    import os
    import jobs_classify as JC
    socs = sorted({s for r in JC.roles() for s in r.get("soc", [])})
    ids = [f"OEUN{'0' * 13}{soc.replace('-', '')}{dt_}" for soc in socs for dt_ in ("01", "13")]
    key = os.environ.get("BLS_API_KEY")
    url, size = ("https://api.bls.gov/publicAPI/v2/timeseries/data/", 50) if key else ("https://api.bls.gov/publicAPI/v1/timeseries/data/", 24)
    prev = json.loads((OUT / "bls.json").read_text()) if (OUT / "bls.json").exists() else {}
    out = {"source": "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics (national)",
           "soc": dict(prev.get("soc", {}))}   # keep earlier values when a call is refused (keyless daily limit)
    for k in range(0, len(ids), size):
        body = {"seriesid": ids[k:k + size], **({"registrationkey": key} if key else {})}
        r = json.loads(http_get(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, timeout=60))
        if r.get("status") != "REQUEST_SUCCEEDED":
            log(f"  WARNING BLS: {r.get('status')} {(r.get('message') or [''])[:1]}")
        for srs in (r.get("Results") or {}).get("series", []):
            sid, data = srs["seriesID"], srs.get("data") or []
            if not data:
                continue
            soc = f"{sid[17:19]}-{sid[19:23]}"
            v = data[0]["value"]
            rec = out["soc"].setdefault(soc, {})
            rec["year"] = data[0]["year"]
            rec["employment" if sid.endswith("01") else "median_wage"] = int(float(v)) if v not in ("-", "*", "#") else None
        time.sleep(1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bls.json").write_text(json.dumps(out, indent=0))
    log(f"  bls.json: {len(out['soc'])} occupations")


JOBBANK = ("https://open.canada.ca/data/dataset/b0e112e9-cf53-4e79-8838-23cd98debe5b/resource/cb52e1d0-ab62-4357-91cc-d8f5a2114e02/"
           "download/20252027_outlook_n21_en_251208.xlsx")
OUTLOOK_SCALE = {"Very limited": 1, "Limited": 2, "Moderate": 3, "Good": 4, "Very good": 5}


def jobbank(url=JOBBANK):
    """Job Bank 3-year employment outlooks (Canada, by economic region, NOC 2021) -> jobbank.json: per NOC code, the
    share of rated regions with a good or very good outlook and the average rating (1 very limited .. 5 very good)."""
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(io.BytesIO(http_get_bytes(url)))
    M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rows = []
    for _, el in ET.iterparse(z.open("xl/worksheets/sheet1.xml")):
        if el.tag == M + "row":
            vals = []
            for c in el.findall(M + "c"):
                if c.get("t") == "inlineStr":
                    vals.append("".join(x.text or "" for x in c.iter(M + "t")))
                else:
                    v = c.find(M + "v")
                    vals.append(v.text if v is not None else "")
            rows.append(vals)
            el.clear()
    hdr = rows[0]
    ci, ti, oi = hdr.index("NOC_Code"), hdr.index("NOC Title"), hdr.index("Outlook")
    agg = {}
    for r in rows[1:]:
        if len(r) <= oi or r[ci] == "NOC_Code":
            continue
        noc = r[ci].replace("NOC_", "")
        a = agg.setdefault(noc, {"title": r[ti], "ratings": []})
        if r[oi] in OUTLOOK_SCALE:
            a["ratings"].append(OUTLOOK_SCALE[r[oi]])
    out = {"source": "Employment and Social Development Canada, Job Bank 3-year employment outlooks 2025-2027 (NOC 2021)", "noc": {}}
    for noc, a in agg.items():
        rs = a["ratings"]
        out["noc"][noc] = {"title": a["title"], "regions": len(rs),
                           "good_share": round(sum(1 for x in rs if x >= 4) / len(rs), 3) if rs else None,
                           "avg": round(sum(rs) / len(rs), 2) if rs else None}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "jobbank.json").write_text(json.dumps(out, separators=(",", ":")))
    log(f"  jobbank.json: {len(out['noc'])} occupations")


def http_get_bytes(url, timeout=180):
    import urllib.request
    from common import UA
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hn", action="store_true", help="fetch new threads and re-aggregate")
    ap.add_argument("--hn-aggregate", action="store_true", help="re-aggregate cached threads only")
    ap.add_argument("--refresh-last", type=int, default=2)
    ap.add_argument("--indeed", action="store_true")
    ap.add_argument("--exposure", action="store_true")
    ap.add_argument("--official", action="store_true", help="BLS wages/employment and Job Bank outlooks")
    a = ap.parse_args()
    if a.exposure:
        exposure()
    if a.official:
        bls()
        jobbank()
    if a.hn:
        hn_fetch(a.refresh_last)
    if a.hn or a.hn_aggregate:
        hn_aggregate()
    if a.indeed:
        indeed()


if __name__ == "__main__":
    main()
