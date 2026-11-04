"""Public job-board APIs (no keys, no LLM usage): Greenhouse, Ashby and Lever serve the JSON behind companies'
careers pages. Each client returns normalized postings:

  {id, title, dept, locs: [str], remote: bool|None, published: "YYYY-MM-DD"|None, text: str|None,
   pay: [min, max, currency, interval]|None, url}

text (the description) is included when the listing carries it (Ashby, Lever); Greenhouse descriptions come from
greenhouse_job() for the postings we keep. Fetched content is untrusted data: it is only parsed, never executed.

Usage: python3 pipeline/ats.py --probe   (checks config/employer_candidates.txt, writes config/employers.json)
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, http_get  # noqa: E402


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _plain(h):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(h or ""))).split())


def _day(s):
    return s[:10] if isinstance(s, str) and re.match(r"\d{4}-\d{2}-\d{2}", s) else None


def greenhouse(token):
    j = json.loads(http_get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout=60, retries=2))
    out = []
    for x in j.get("jobs", []):
        locs = [(x.get("location") or {}).get("name") or ""] + [o.get("location") or o.get("name") or "" for o in x.get("offices") or []]
        out.append({"id": str(x["id"]), "title": x.get("title") or "", "dept": " / ".join(d.get("name", "") for d in x.get("departments") or []),
                    "locs": [l for l in locs if l], "remote": None, "published": _day(x.get("first_published") or x.get("updated_at")),
                    "text": None, "pay": None, "url": x.get("absolute_url")})
    return out


def greenhouse_job(token, jid):
    """Description and pay range of one Greenhouse posting."""
    x = json.loads(http_get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{jid}?pay_transparency=true", timeout=40, retries=2))
    pay = None
    for r in x.get("pay_input_ranges") or []:
        try:
            lo, hi = int(r["min_cents"]) / 100, int(r["max_cents"]) / 100
            pay = [lo, hi, r.get("currency_type") or "USD", "year"]
            break
        except (KeyError, TypeError, ValueError):
            continue
    return {"text": _plain(x.get("content")), "pay": pay}


def ashby(token):
    j = json.loads(http_get(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true", timeout=60, retries=2))
    out = []
    for x in j.get("jobs", []):
        if x.get("isListed") is False:
            continue
        locs = [x.get("location") or ""] + [s.get("location") or "" for s in x.get("secondaryLocations") or []]
        addr = ((x.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        if addr:
            locs.append(f"country:{addr}")
        pay = None
        for comp in ((x.get("compensation") or {}).get("summaryComponents") or []):
            if comp.get("compensationType") == "Salary" and comp.get("minValue"):
                pay = [comp["minValue"], comp.get("maxValue") or comp["minValue"], comp.get("currencyCode") or "USD",
                       (comp.get("interval") or "1 YEAR").lower()]
                break
        out.append({"id": x["id"], "title": x.get("title") or "", "dept": " / ".join(filter(None, [x.get("department"), x.get("team")])),
                    "locs": [l for l in locs if l], "remote": bool(x.get("isRemote")) or (x.get("workplaceType") == "Remote"),
                    "published": _day(x.get("publishedAt")), "text": (x.get("descriptionPlain") or "")[:20000] or None,
                    "pay": pay, "url": x.get("jobUrl")})
    return out


def lever(token):
    j = json.loads(http_get(f"https://api.lever.co/v0/postings/{token}?mode=json", timeout=60, retries=2))
    if not isinstance(j, list):
        raise ValueError("not a Lever board")
    out = []
    for x in j:
        c = x.get("categories") or {}
        locs = (c.get("allLocations") or []) + [c.get("location") or ""] + ([f"country:{x['country']}"] if x.get("country") else [])
        sr = x.get("salaryRange") or {}
        pay = [sr["min"], sr.get("max") or sr["min"], sr.get("currency") or "USD", (sr.get("interval") or "per-year-salary")] if sr.get("min") else None
        text = " ".join(filter(None, [x.get("descriptionPlain"), " ".join(_plain(l.get("content")) for l in x.get("lists") or []),
                                      x.get("additionalPlain")]))
        ts = x.get("createdAt")
        out.append({"id": x["id"], "title": x.get("text") or "", "dept": " / ".join(filter(None, [c.get("department"), c.get("team")])),
                    "locs": [l for l in locs if l], "remote": (x.get("workplaceType") == "remote") if x.get("workplaceType") else None,
                    "published": dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date().isoformat() if ts else None,
                    "text": text[:20000] or None, "pay": pay, "url": x.get("hostedUrl")})
    return out


# ---------------------------------------------------------------- Workday (big tech careers sites) and Amazon
TECH_FAMILY = re.compile(r"engineer|software|hardware|research|data|technolog|\bit\b|information|product|scien|machine|\bai\b|analytic|"
                         r"security|cyber|develop|architect|silicon|cloud|digital|univ|intern|graduate", re.I)
COUNTRY = {"United States of America": "US", "United States": "US", "USA": "US", "Canada": "CA"}


def _wd(base, tenant, site, body):
    return json.loads(http_get(f"{base}/wday/cxs/{tenant}/{site}/jobs", data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=45, retries=2))


def _facets(fs):
    out = []
    for f in fs or []:
        out.append(f)
        out += _facets([v for v in f.get("values", []) if v.get("facetParameter")])
    return out


def _posted(txt, today):
    t = (txt or "").lower()
    n = 0 if "today" in t else 1 if "yesterday" in t else int(m.group(1)) if (m := re.search(r"(\d+)\+? days", t)) else None
    return (today - dt.timedelta(days=n)).isoformat() if n is not None else None


def workday(token):
    """token 'tenant|wdN|site'. Tech job families only, one pass per country (US, Canada) when the site has a country
    filter; 20 postings a page (Workday's limit), at most 2,000 per pass."""
    tenant, wd, site = token.split("|")
    base, today = f"https://{tenant}.{wd}.myworkdayjobs.com", dt.date.today()
    first = _wd(base, tenant, site, {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""})
    facets = _facets(first.get("facets"))
    applied = {}
    for f in facets:
        if f.get("facetParameter") in ("jobFamilyGroup", "jobFamily"):
            ids = [v["id"] for v in f.get("values", []) if v.get("id") and TECH_FAMILY.search(v.get("descriptor") or "")]
            if ids:
                applied[f["facetParameter"]] = ids
                break
    cf_ = next((f for f in facets if any((v.get("descriptor") or "") in COUNTRY for v in f.get("values", []))), None)
    passes = [(cf_["facetParameter"], v["id"], COUNTRY[v["descriptor"]]) for v in cf_["values"] if v.get("descriptor") in COUNTRY] if cf_ else [(None, None, None)]
    out = {}
    for param, cid, ctag in passes:
        body = {"appliedFacets": {**applied, **({param: [cid]} if param else {})}, "limit": 20, "offset": 0, "searchText": ""}
        total = None
        while True:
            r = _wd(base, tenant, site, body)
            total = r.get("total", 0) if total is None else total
            posts = r.get("jobPostings") or []
            for x in posts:
                path = x.get("externalPath") or ""
                jid = (x.get("bulletFields") or [path])[0]
                prev = out.get(jid)
                locs = (prev["locs"] if prev else [x.get("locationsText") or ""]) + ([f"country:{ctag}"] if ctag else [])
                out[jid] = {"id": jid, "title": x.get("title") or "", "dept": "", "locs": locs, "remote": None,
                            "published": _posted(x.get("postedOn"), today), "text": None, "pay": None,
                            "url": f"{base}/en-US/{site}{path}", "_path": path}
            body["offset"] += 20
            if not posts or body["offset"] >= min(total, 2000):
                break
            time.sleep(0.2)
    return list(out.values())


def workday_job(token, path):
    """Description, locations and posting date of one Workday posting."""
    tenant, wd, site = token.split("|")
    x = json.loads(http_get(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}", timeout=40, retries=2))
    j = x.get("jobPostingInfo") or {}
    locs = [j.get("location") or ""] + list(j.get("additionalLocations") or [])
    c = (j.get("country") or {}).get("descriptor")
    if c in COUNTRY:
        locs.append(f"country:{COUNTRY[c]}")
    return {"text": _plain(j.get("jobDescription")), "pay": None, "locs": [l for l in locs if l], "published": _day(j.get("startDate"))}


AMAZON_CATS = ("software-development", "machine-learning-science", "research-science", "data-science", "solutions-architect",
               "hardware-development", "systems-quality-security-engineering", "project-program-product-management-technical",
               "business-intelligence", "economics")


def amazon(token="amazon"):
    """amazon.jobs search feed: tech categories, US and Canada, 100 a page (descriptions included)."""
    out = {}
    cats = "".join(f"&category%5B%5D={c}" for c in AMAZON_CATS)
    for country, tag in (("USA", "US"), ("CAN", "CA")):
        off, hits = 0, None
        while True:
            r = json.loads(http_get(f"https://www.amazon.jobs/en/search.json?result_limit=100&offset={off}&country%5B%5D={country}&sort=recent{cats}",
                                    timeout=60, retries=2))
            hits = r.get("hits", 0) if hits is None else hits
            jobs = r.get("jobs") or []
            for x in jobs:
                try:
                    pub = dt.datetime.strptime(" ".join((x.get("posted_date") or "").split()), "%B %d, %Y").date().isoformat()
                except ValueError:
                    pub = None
                text = " ".join(_plain(x.get(k)) for k in ("description", "basic_qualifications", "preferred_qualifications"))
                out[str(x.get("id_icims") or x.get("id"))] = {
                    "id": str(x.get("id_icims") or x.get("id")), "title": x.get("title") or "", "dept": x.get("job_category") or "",
                    "locs": [x.get("location") or "", f"country:{tag}"], "remote": None, "published": pub, "text": text[:20000] or None,
                    "pay": None, "url": "https://www.amazon.jobs" + (x.get("job_path") or "")}
            off += 100
            if not jobs or off >= min(hits, 6000):
                break
            time.sleep(0.5)
    return list(out.values())


CLIENTS = {"greenhouse": greenhouse, "ashby": ashby, "lever": lever, "workday": workday, "amazon": amazon}


def fetch_board(emp):
    return CLIENTS[emp["ats"]](emp["token"])


# ---------------------------------------------------------------- probe
def _slugs(name, given):
    base = re.sub(r"\(.*?\)", "", name).strip().lower()
    out = [s.strip() for s in given.split(",") if s.strip()]
    out += [re.sub(r"[^a-z0-9]", "", base), re.sub(r"[^a-z0-9]+", "-", base).strip("-")]
    return list(dict.fromkeys(s for s in out if s))


def probe():
    cands = []
    for line in (CONFIG / "employer_candidates.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")] + ["", ""]
        cands.append((parts[0], parts[1], _slugs(parts[0], parts[2])))

    def one(c):
        name, sector, slugs = c
        best = None
        for ats in ("greenhouse", "ashby", "lever"):
            for s in slugs:
                try:
                    n = len(CLIENTS[ats](s))
                except Exception:
                    continue
                if n and (best is None or n > best["n"]):
                    best = {"name": name, "sector": sector, "ats": ats, "token": s, "n": n}
        return name, best

    found, missing = [], []
    with cf.ThreadPoolExecutor(8) as ex:
        for name, best in ex.map(one, cands):
            (found.append(best) if best else missing.append(name))
    seen, emps = set(), []
    old = json.loads((CONFIG / "employers.json").read_text())["employers"] if (CONFIG / "employers.json").exists() else []
    found += [e for e in old if e["ats"] in ("workday", "amazon")]   # added by hand: big-tech careers sites
    for e in sorted(found, key=lambda e: e["name"].lower()):
        if (e["ats"], e["token"]) not in seen:
            seen.add((e["ats"], e["token"]))
            emps.append(e)
    (CONFIG / "employers.json").write_text(json.dumps({
        "note": "Generated by pipeline/ats.py --probe from config/employer_candidates.txt; n = postings at probe time.",
        "employers": emps}, indent=1))
    log(f"probe: {len(emps)} boards found, {len(missing)} candidates without a public board")
    log("  no board: " + ", ".join(missing))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    if ap.parse_args().probe:
        probe()
