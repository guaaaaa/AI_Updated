"""Field-wide arXiv statistics per ISO week, for the weekly/monthly trend summaries (no LLM usage).

For every new paper (new submissions + cross-lists, deduplicated) announced in our categories during the week's
mailings (Mon-Fri listing dates), it records:
  * topic counts: how many titles match each paper tag (config/topic_lexicon.json; rough, a paper can match several)
  * term counts: title n-grams (1-3 words) used by at least 3 papers
Saved as data/state/arxiv_weekly/<week>.json (a few KB). Comparisons (rising/fading) are computed by readers.

Usage: python3 pipeline/arxiv_stats.py --week 2026-W44 [--week ...] [--force]
       python3 pipeline/arxiv_stats.py --through 2026-10-31 --weeks 9     (backfill a range of weeks)
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, STATE, config, load_json, week_days, week_id  # noqa: E402

OUT = STATE / "arxiv_weekly"
FUNCTION = set("""a an the of for and or in on with via to from by at as is are be into over under using towards toward
through without within across between beyond about against its their our we can do does not no vs versus based new
how what when why which who whose than that this these those more less most least""".split())
GENERIC = set("""learning model models approach method methods framework novel efficient large language data deep neural
network networks analysis study system systems improving improved enhancing enhanced effective robust scalable
adaptive task tasks multi towards generation problem problems performance training via using use case application
applications toward evaluation benchmark understanding recognition prediction detection estimation representation
representations information knowledge time real world control dynamic dynamics graph graphs image images text video
optimization machine ai learn learns learned reliable research online simple general better unified fast good free
rethinking revisiting matter matters make makes need needs work works evidence case role power limits toward
towards beyond across one two three single first all every any many much""".split())
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]*[a-z0-9]|[a-z]")


def lexicon():
    lex = load_json(CONFIG / "topic_lexicon.json")
    return {t: re.compile("|".join(f"(?:{p})" for p in pats), re.I) for t, pats in lex.items() if not t.startswith("_")}


def title_terms(title):
    toks = TOKEN_RE.findall(re.sub(r"['’]", "", title.lower()))  # "don't" -> "dont", "model's" -> "models"
    terms = set()
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in FUNCTION or g[-1] in FUNCTION or any(t.isdigit() for t in g):
                continue
            if n == 1 and (g[0] in GENERIC or len(g[0]) < 3):
                continue
            terms.add(" ".join(g))
    return terms


def mailing_dates(wid):
    mon, _, _ = week_days(wid)
    return [mon + dt.timedelta(days=i) for i in range(5)]


def week_stats(wid):
    from fetch_papers import catchup  # imported lazily: pulls in BeautifulSoup
    cats = config("sources")["arxiv_categories"]
    papers, dates = {}, []
    for ld in mailing_dates(wid):
        n0 = len(papers)
        for c in cats:
            try:
                for pid, p in catchup(c, ld).items():
                    papers.setdefault(pid, p["title"])
            except Exception as e:
                print(f"  WARNING catchup {c} {ld} failed: {e}", file=sys.stderr)
        if len(papers) > n0:
            dates.append(ld.isoformat())
    lex = lexicon()
    tax = config("taxonomy")["paper_tags"]
    topics, groups, terms = Counter(), Counter(), Counter()
    for title in papers.values():
        hit = {t for t, rx in lex.items() if rx.search(title)}
        topics.update(hit)
        groups.update({tax[t]["group"] for t in hit if t in tax})
        terms.update(title_terms(title))
    return {"week": wid, "mailing_dates": dates, "n_papers": len(papers),
            "topics": dict(topics.most_common()), "groups": dict(groups.most_common()),
            "terms": {k: v for k, v in terms.most_common(2500) if v >= 3}}


def load_week(wid):
    return load_json(OUT / f"{wid}.json")


def ensure_weeks(wids, force=False):
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    for wid in wids:
        j = None if force else load_week(wid)
        if j is None:
            j = week_stats(wid)
            if j["n_papers"]:
                (OUT / f"{wid}.json").write_text(json.dumps(j, separators=(",", ":")) + "\n")
            print(f"  arXiv stats {wid}: {j['n_papers']} papers over {len(j['mailing_dates'])} mailings", file=sys.stderr)
        out[wid] = j
    return out


def combine(weeks):
    """Sum several week stats into one period."""
    n, topics, groups, terms = 0, Counter(), Counter(), Counter()
    for w in weeks:
        if not w or not w.get("n_papers"):
            continue
        n += w["n_papers"]
        topics.update(w["topics"])
        groups.update(w["groups"])
        terms.update(w["terms"])
    return {"n_papers": n, "topics": topics, "groups": groups, "terms": terms}


def movers(cur, base, min_count=10, k_up=15, k_down=10):
    """Terms whose share of titles rose / fell most vs the baseline period (smoothed log ratio)."""
    if not cur["n_papers"] or not base["n_papers"]:
        return [], []
    scale = cur["n_papers"] / base["n_papers"]
    rows = []
    for t in set(cur["terms"]) | set(base["terms"]):
        c, b = cur["terms"].get(t, 0), base["terms"].get(t, 0)
        exp = b * scale
        # plain single words are noisy ("matter", "team"): they need far more support than phrases/compounds
        need = min_count if (" " in t or "-" in t) else max(25, int(min_count * 2.5))
        if max(c, exp) < need:
            continue
        rows.append((math.log((c + 5) / (exp + 5)), t, c, round(exp, 1)))
    rows.sort(reverse=True)

    def dedupe(rs):  # drop a term that is part of (or contains) a stronger, similar-count term already kept
        kept = []
        for r in rs:
            if any((r[1] in k[1] or k[1] in r[1]) and abs(r[2] - k[2]) <= max(3, 0.35 * k[2]) for k in kept):
                continue
            kept.append(r)
        return kept
    up = [dict(term=t, now=c, base=e) for s, t, c, e in dedupe([r for r in rows if r[0] > 0.25])][:k_up]
    down = [dict(term=t, now=c, base=e) for s, t, c, e in dedupe([r for r in reversed(rows) if r[0] < -0.25])][:k_down]
    return up, down


def weeks_back(wid, n):
    mon, _, _ = week_days(wid)
    return [week_id(mon - dt.timedelta(weeks=i)) for i in range(n, 0, -1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", action="append", default=[])
    ap.add_argument("--through", help="last date of a range of weeks to (re)compute")
    ap.add_argument("--weeks", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    wids = list(a.week)
    if a.through:
        last = week_id(dt.date.fromisoformat(a.through))
        wids += weeks_back(last, a.weeks - 1) + [last]
    got = ensure_weeks(wids, a.force)
    for wid, j in got.items():
        top = ", ".join(f"{g} {v / max(1, j['n_papers']):.0%}" for g, v in list(j["groups"].items())[:6])
        print(f"{wid}: {j['n_papers']} papers | {top}")


if __name__ == "__main__":
    main()
