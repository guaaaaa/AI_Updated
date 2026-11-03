"""Field-wide trend model (no LLM usage): what the whole field is doing, not what our digest picked.

Monthly aggregates (data/state/field/YYYY-MM.json, a few hundred KB each) built from work/field/ raw data:
  * arXiv: for each research direction in config/directions.json, how many of the month's new papers (titles)
    are about it, and from how many distinct teams (last author) -- breadth, so one lab's series can't make a trend;
    plus title-term counts with team counts (to spot emerging phrases outside the direction list)
  * Hugging Face Daily Papers: the same directions matched on titles, weighted by upvotes -- attention
  * news: reputable headlines grouped into stories, tagged by config/industry.json categories and companies

Trend analysis for a month M compares the 3-month window ending at M with the 3 months before it and with the
same 3 months a year earlier (which cancels conference-deadline seasonality). A direction is "rising" or
"fading" only if the change is statistically large (two-proportion z >= 3), material (>= 10% relative), held in
at least 2 of the 3 months, spread across >= 15 teams, and not contradicted by the year-ago comparison.

Usage: python3 pipeline/field_stats.py --through 2026-10 --months 27 [--rebuild]   (build aggregates + report)
"""
import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field_data as FD  # noqa: E402
import stories  # noqa: E402
from common import STATE, config, load_json  # noqa: E402

OUT = STATE / "field"
NEWS_FROM = "2025-08"           # first month with a news backfill
MIN_Z, MIN_REL, MIN_TEAMS = 3.0, 0.10, 15

FUNCTION = set("""a an the of for and or in on with to from by at as is are be into over under using towards toward
through without within across between beyond about against its their our we can do does not no vs versus based new
how what when why which who whose than that this these those more less most least via""".split())
GENERIC = set("""learning model models approach method methods framework novel efficient large language data deep neural
network networks analysis study system systems improving improved enhancing enhanced effective robust scalable adaptive
task tasks multi generation problem problems performance training using use case application applications evaluation
benchmark understanding recognition prediction detection estimation representation representations information
knowledge time real world control dynamic dynamics graph graphs image images text video optimization machine ai learn
learns learned reliable research online simple general better unified fast good free rethinking revisiting matter
matters make makes need needs work works evidence case role power limits beyond across one two three single first all
every any many much""".split())
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*[a-z0-9]|[a-z]")


def directions():
    return [{**d, "rx": re.compile("|".join(f"(?:{p})" for p in d["patterns"]), re.I)}
            for d in config("directions")["directions"]]


def industry():
    j = config("industry")
    comp = lambda dd: {k: re.compile("|".join(f"(?:{p})" for p in v), re.I) for k, v in dd.items()}
    return comp(j["categories"]), comp(j["entities"])


def title_terms(title):
    toks = TOKEN_RE.findall(re.sub(r"['’]", "", title.lower()))
    out = set()
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in FUNCTION or g[-1] in FUNCTION or any(t.isdigit() for t in g):
                continue
            if n == 1 and (g[0] in GENERIC or len(g[0]) < 3):
                continue
            out.add(" ".join(g))
    return out


def team(authors):
    if not authors:
        return None
    return re.sub(r"[^a-z ]", "", authors[-1].lower()).strip() or None


# ---------------------------------------------------------------- monthly aggregates
def build_month(mid, force=False):
    path = OUT / f"{mid}.json"
    if path.exists() and not force:
        return json.loads(path.read_text())
    D = directions()
    papers = FD.arxiv_month(mid)
    agg = {"month": mid, "n_papers": len(papers), "teams": len({team(p["a"]) for p in papers} - {None})}
    dn, dteams = Counter(), defaultdict(set)
    gn, gteams = Counter(), defaultdict(set)   # fields = taxonomy groups: papers matching ANY of their directions
    tn, tteams = Counter(), defaultdict(set)
    for p in papers:
        tk = team(p["a"]) or p["id"]
        hit_groups = set()
        for d in D:
            if d["rx"].search(p["t"]):
                dn[d["id"]] += 1
                dteams[d["id"]].add(tk)
                hit_groups.add(d["group"])
        for g in hit_groups:
            gn[g] += 1
            gteams[g].add(tk)
        for t in title_terms(p["t"]):
            tn[t] += 1
            tteams[t].add(tk)
    agg["dirs"] = {d["id"]: [dn[d["id"]], len(dteams[d["id"]])] for d in D}
    agg["groups"] = {g: [gn[g], len(gteams[g])] for g in sorted({d["group"] for d in D})}
    # phrases only (multi-word or hyphenated): single words are mostly generic and the directions cover topics
    kept = [(t, n) for t, n in tn.most_common() if n >= 5 and (" " in t or "-" in t)][:6000]
    agg["terms"] = {t: [n, len(tteams[t])] for t, n in kept}
    agg["terms_floor"] = kept[-1][1] if len(kept) == 6000 else 4   # terms not stored had at most this many papers
    hf = FD.hf_month(mid)
    hn, hup, htop = Counter(), Counter(), defaultdict(list)
    for p in hf:  # titles, like the publication share, so the two are comparable
        for d in D:
            if d["rx"].search(p["t"]):
                hn[d["id"]] += 1
                hup[d["id"]] += p["up"]
                htop[d["id"]].append([p["id"], p["t"], p["up"], p["d"]])
    agg["hf"] = {"n": len(hf), "up": sum(p["up"] for p in hf), "dirs": {d["id"]: [hn[d["id"]], hup[d["id"]]] for d in D},
                 "top": {k: sorted(v, key=lambda x: -x[2])[:5] for k, v in htop.items()}}   # most-upvoted per direction
    if mid >= NEWS_FROM:
        cats, ents = industry()
        heads = FD.news_month(mid)
        st = stories.cluster(heads)
        cn, en = Counter(), Counter()
        for s in st:
            for c, rx in cats.items():
                if rx.search(s["text"]):
                    cn[c] += 1
            for e, rx in ents.items():
                if rx.search(s["text"]):
                    en[e] += 1
        agg["news"] = {"n_headlines": len(heads), "n_stories": len(st), "cats": dict(cn), "ents": dict(en),
                       "top": [[s["title"], len(s["outlets"]), s["date"]] for s in st[:30]]}
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agg, ensure_ascii=False, separators=(",", ":")) + "\n")
    return agg


def load_month(mid):
    return load_json(OUT / f"{mid}.json")


# ---------------------------------------------------------------- statistics
def ztest(a, na, b, nb):
    if not na or not nb:
        return 0.0
    p = (a + b) / (na + nb)
    se = math.sqrt(max(p * (1 - p), 1e-12) * (1 / na + 1 / nb))
    return (a / na - b / nb) / se


def window(mid, k=3):
    return [FD.shift(mid, -i) for i in range(k - 1, -1, -1)]


def _sum(aggs, get):
    vals = [get(a) for a in aggs if a]
    return sum(vals) if len(vals) == len(aggs) else None   # None = window incomplete


def analyze(mid, series_months=24):
    """Trend report for the 3-month window ending at `mid` (vs previous 3 months and vs a year earlier)."""
    W, P, Y = window(mid), window(FD.shift(mid, -3)), window(FD.shift(mid, -12))
    A = {m: load_month(m) for m in set(W + P + Y + [FD.shift(mid, -i) for i in range(series_months)])}
    aw, ap, ay = [A[m] for m in W], [A[m] for m in P], [A[m] for m in Y]
    NW, NP, NY = (_sum(x, lambda a: a["n_papers"]) for x in (aw, ap, ay))
    if not NW:
        raise SystemExit(f"field aggregates missing for {W}: run field_stats.py --through {mid}")
    series_m = [m for m in [FD.shift(mid, -i) for i in range(series_months - 1, -1, -1)] if A.get(m)]
    rep = {"month": mid, "window": W, "prev": P, "year_ago": Y if NY else None, "n_papers": NW, "n_prev": NP,
           "n_year_ago": NY, "volume": [[m, A[m]["n_papers"]] for m in series_m], "directions": []}
    for d in config("directions")["directions"]:
        k = d["id"]
        nW = _sum(aw, lambda a: a["dirs"].get(k, [0, 0])[0])
        nP = _sum(ap, lambda a: a["dirs"].get(k, [0, 0])[0])
        nY = _sum(ay, lambda a: a["dirs"].get(k, [0, 0])[0]) if NY else None
        teams = _sum(aw, lambda a: a["dirs"].get(k, [0, 0])[1])
        pW, pP = nW / NW, (nP / NP if NP else None)
        pY = nY / NY if NY else None
        z_m = ztest(nW, NW, nP, NP) if NP else 0.0
        z_y = ztest(nW, NW, nY, NY) if NY else None
        rel_m = (pW / pP - 1) if pP else None
        rel_y = (pW / pY - 1) if pY else None
        months_above = sum(1 for a in aw if pP is not None and a["dirs"].get(k, [0, 0])[0] / a["n_papers"] > pP)
        hW = _sum(aw, lambda a: a["hf"]["dirs"].get(k, [0, 0])[1])
        hWt = _sum(aw, lambda a: a["hf"]["up"])
        hP = _sum(ap, lambda a: a["hf"]["dirs"].get(k, [0, 0])[1])
        hPt = _sum(ap, lambda a: a["hf"]["up"])
        att_W = hW / hWt if hWt else None
        att_P = hP / hPt if hPt else None
        status = "steady"
        if rel_m is not None and z_m >= MIN_Z and rel_m >= MIN_REL and months_above >= 2 and teams >= MIN_TEAMS \
                and (rel_y is None or rel_y > 0):
            status = "rising"
            if pY is not None and nY < 10 and nW >= 30:
                status = "new"
        elif rel_m is not None and z_m <= -MIN_Z and rel_m <= -MIN_REL and months_above <= 1 and (rel_y is None or rel_y < 0):
            status = "fading"
        rep["directions"].append({
            "id": k, "name": d["name"], "group": d["group"], "status": status, "n": nW, "teams": teams,
            "share": round(pW, 5), "share_prev": round(pP, 5) if pP is not None else None,
            "share_year_ago": round(pY, 5) if pY is not None else None,
            "rel_prev": round(rel_m, 3) if rel_m is not None else None, "z_prev": round(z_m, 1),
            "rel_year": round(rel_y, 3) if rel_y is not None else None, "z_year": round(z_y, 1) if z_y is not None else None,
            "months_above": months_above,
            "attention": round(att_W, 4) if att_W is not None else None,
            "attention_prev": round(att_P, 4) if att_P is not None else None,
            "series": [round(A[m]["dirs"].get(k, [0, 0])[0] / A[m]["n_papers"], 5) for m in series_m],
            "counts": [A[m]["dirs"].get(k, [0, 0])[0] for m in series_m],
            "att_series": [round(A[m]["hf"]["dirs"].get(k, [0, 0])[1] / A[m]["hf"]["up"], 4) if A[m]["hf"]["up"] else 0
                           for m in series_m],
            "hf_top": sorted({x[0]: x for a in aw for x in a["hf"].get("top", {}).get(k, [])}.values(), key=lambda x: -x[2])[:8],
        })
    rep["series_months"] = series_m
    groups = sorted({d["group"] for d in config("directions")["directions"]})
    rep["groups"] = [{"name": g, "counts": [(A[m].get("groups") or {}).get(g, [0, 0])[0] for m in series_m],
                      "series": [round((A[m].get("groups") or {}).get(g, [0, 0])[0] / A[m]["n_papers"], 5) for m in series_m]}
                     for g in groups]
    rep["terms_up"], rep["terms_down"] = term_movers(aw, ap, ay, NW, NP, NY)
    rep["news"] = news_report(mid, A)
    return rep


def term_movers(aw, ap, ay, NW, NP, NY, k=15):
    """Phrases whose share of titles jumped or collapsed. A phrase missing from a month's stored terms had at most
    that month's floor count, so missing months are filled conservatively: high when testing for a rise against the
    baseline, high when testing for a fall in the window."""
    if not NP:
        return [], []
    floor = lambda a: a.get("terms_floor", 4)

    def total(aggs, t, fill):
        return sum(a["terms"][t][0] if t in a["terms"] else (floor(a) if fill else 0) for a in aggs)
    tw = Counter()
    for a in aw:
        for t, (n, tm) in a["terms"].items():
            tw[t] += tm
    cands = set().union(*[a["terms"] for a in aw + ap])
    up, down = [], []
    for t in cands:
        if " " not in t and "-" not in t:
            continue
        n, b = total(aw, t, False), total(ap, t, True)          # rise: window as stored, baseline at its upper bound
        nd, bd = total(aw, t, True), total(ap, t, False)        # fall: window at its upper bound, baseline as stored
        cy = Counter({t: total(ay, t, True)}) if NY else Counter()
        need = 25
        z = ztest(n, NW, b, NP)
        exp = b * NW / NP
        if n >= need and tw[t] >= 12 and z >= 4 and (n + 5) / (exp + 5) >= 1.6:
            yexp = cy[t] * NW / NY if NY else None
            if yexp is None or (n + 5) / (yexp + 5) >= 1.6:
                up.append({"term": t, "now": n, "prev": round(exp, 1), "year_ago": round(yexp, 1) if yexp is not None else None,
                           "year_ago_upper": bool(NY) and any(t not in a["terms"] for a in ay),
                           "prev_upper": any(t not in a["terms"] for a in ap), "teams": tw[t], "z": round(z, 1)})
            continue
        zd, expd = ztest(nd, NW, bd, NP), bd * NW / NP
        if expd >= need and zd <= -4 and (nd + 5) / (expd + 5) <= 0.6:
            down.append({"term": t, "now": nd, "prev": round(expd, 1), "z": round(zd, 1),
                         "approx": any(t not in a["terms"] for a in aw)})

    def dedupe(rows, key):
        kept = []
        for r in sorted(rows, key=key):
            if any(r["term"] in x["term"] or x["term"] in r["term"] for x in kept):
                continue
            kept.append(r)
        return kept[:k]
    return dedupe(up, lambda r: -r["z"]), dedupe(down, lambda r: r["z"])


def news_report(mid, A):
    W, P = window(mid), window(FD.shift(mid, -3))
    aw, ap = [A.get(m) for m in W], [A.get(m) for m in P]
    if not all(a and a.get("news") for a in aw):
        return None
    have_p = all(a and a.get("news") for a in ap)
    SW = sum(a["news"]["n_stories"] for a in aw)
    SP = sum(a["news"]["n_stories"] for a in ap) if have_p else None
    out = {"stories": SW, "stories_prev": SP, "categories": [], "entities": [],
           "top": A[mid]["news"]["top"][:20] if A.get(mid) and A[mid].get("news") else []}
    for key, field in (("categories", "cats"), ("entities", "ents")):
        names = set().union(*[a["news"][field] for a in aw])
        for nm in names:
            nW = sum(a["news"][field].get(nm, 0) for a in aw)
            nP = sum(a["news"][field].get(nm, 0) for a in ap) if have_p else None
            out[key].append({"name": nm, "n": nW, "share": round(nW / SW, 4),
                             "share_prev": round(nP / SP, 4) if have_p and SP else None,
                             "z_prev": round(ztest(nW, SW, nP, SP), 1) if have_p and SP else None})
        out[key].sort(key=lambda r: -r["n"])
    months = sorted(m for m, a in A.items() if a and a.get("news"))
    out["series_months"] = months
    out["category_series"] = {c: [round(A[m]["news"]["cats"].get(c, 0) / max(1, A[m]["news"]["n_stories"]), 4) for m in months]
                              for c in config("industry")["categories"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--through", required=True)
    ap.add_argument("--months", type=int, default=27)
    ap.add_argument("--rebuild", action="store_true", help="recompute aggregates (e.g. after editing directions)")
    a = ap.parse_args()
    for m in window(a.through, a.months):
        agg = build_month(m, force=a.rebuild)
        print(f"{m}: {agg['n_papers']} papers, {agg['hf']['n']} HF, "
              f"{agg.get('news', {}).get('n_stories', '-')} stories", file=sys.stderr)
    rep = analyze(a.through)
    for st in ("new", "rising", "fading"):
        rows = [d for d in rep["directions"] if d["status"] == st]
        print(f"{st.upper()}: " + "; ".join(f"{d['name']} {d['share']:.2%} vs {d['share_prev']:.2%} (z {d['z_prev']}, yoy "
                                            f"{d['rel_year']})" for d in rows))
    print("TERMS UP:", ", ".join(f"{t['term']} {t['now']}/{t['prev']}" for t in rep["terms_up"]))
    print("TERMS DOWN:", ", ".join(f"{t['term']} {t['now']}/{t['prev']}" for t in rep["terms_down"]))


if __name__ == "__main__":
    main()
