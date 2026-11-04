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


CLIENTS = {"greenhouse": greenhouse, "ashby": ashby, "lever": lever}


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
