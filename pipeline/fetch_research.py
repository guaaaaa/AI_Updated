"""Research candidates for the news-led domains (business, science; no LLM usage): journal and working-paper feeds
(config/domains/<id>/sources.json "research") -> work/<id>/papers_<date>.json + a printed shortlist.

Only research items are kept (Nature-family /articles/s..., NEJM original articles, Science "Research Article" /
"Report", Lancet "[Articles]", Cell "Article", every NBER working paper), from the last 45 days (journal feeds list
the current issue, whose papers often went online weeks earlier; papers are not repeated within 60 days).

Candidate ids: a slug of the DOI (doi-10-1038-s41586-026-11368-9) or of the feed's own id (nber-w35967), or an
arXiv id. Signals: venue tier (flagship / major) and press coverage = how many of the day's news headlines
(work/<id>/news_<date>.json, so run fetch_news.py first) share at least two distinctive title words (words that
appear in more than 2% of the day's headlines do not count).

Usage: python3 pipeline/fetch_research.py --domain science --date 2026-11-04
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DOM, DOMAIN, ET as TZ, WORK, config, http_get, load_json, paper_window, parse_date, recent_digests, today_et  # noqa: E402

RECENT_DAYS, DEDUP_DAYS = 45, 60
KEEP_TYPE = re.compile(r"research|^article|original|report", re.I)
DROP_TYPE = re.compile(r"comment|editorial|perspective|review|correspond|letter|news|book|career|obituar|retract|correction|erratum|"
                       r"world view|feature|outlook|q&a|in brief|this week|policy forum|essay|clinical implications|image", re.I)
STOP = set("""about after against among analysis approach based between from have human into large model models more most
new over role study their these through using with without within across effect effects evidence data during under
toward towards which while when where what does show shows reveals revealed""".split())


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _txt(e):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", e or "")).split())


def parse_items(xml_text):
    """RSS 1.0 (RDF), RSS 2.0 or Atom -> [{title, link, date, authors, doi, type, desc}] (namespaces ignored)."""
    root = ET.fromstring(re.sub(r"^[^<]+", "", xml_text))
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        f = {}
        for c in it:
            k = c.tag.split("}")[-1]
            v = (c.text or "").strip() or c.get("href") or ""
            f.setdefault(k, []).append(v)
        g = lambda k: (f.get(k) or [""])[0]
        authors = [a for x in f.get("creator", []) + f.get("author", []) for a in re.split(r",\s*", x) if a][:30]
        date = g("date") or g("publicationDate") or g("coverDate") or g("pubDate") or g("published") or g("updated")
        out.append({"title": _txt(g("title")), "link": g("link") or g("url"), "date": date, "authors": authors,
                    "doi": g("doi") or re.sub(r"^doi:", "", g("identifier")) if (g("doi") or g("identifier").startswith(("doi:", "10."))) else "",
                    "type": g("type") or g("section"), "desc": _txt(g("description") or g("summary") or g("encoded"))[:700]})
    return out


def _date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return dt.datetime.strptime(s[:len(dt.datetime.now().strftime(fmt))] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return dt.date.fromisoformat(m.group(1)) if m else None


def is_research(feed, it):
    link, title, typ = it["link"], it["title"], it["type"]
    if "nature.com/articles/" in link:
        return "/articles/s" in link
    if "nejm.org" in link:
        return "NEJMoa" in link
    if "thelancet.com" in link:
        return title.startswith("[Articles]") or bool(KEEP_TYPE.search(typ)) and not DROP_TYPE.search(typ)
    if "nber.org" in link:
        return True
    if typ:
        return bool(KEEP_TYPE.search(typ)) and not DROP_TYPE.search(typ)
    return not DROP_TYPE.search(title)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:90]


def words(t):
    return {w for w in re.findall(r"[a-z][a-z\-]{4,}", t.lower()) if w not in STOP}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today_et().isoformat())
    ap.add_argument("--size", type=int, default=40)
    a = ap.parse_args()
    d = parse_date(a.date)
    start, end = paper_window(d)
    src = config("sources").get("research", {})
    news = load_json(WORK / f"news_{d}.json", {}) or {}
    heads = [words(h["title"]) for h in news.get("headlines", [])]
    df = {}
    for h in heads:
        for w in h:
            df[w] = df.get(w, 0) + 1
    common = {w for w, n in df.items() if n > max(2, 0.02 * len(heads))}   # everyday words of the day's news
    heads = [h - common for h in heads]
    seen = {p["id"] for j in recent_digests(d, DEDUP_DAYS) for p in j.get("papers", [])}
    cands, n_feed = {}, {}
    earlier = {c["id"]: c for c in (load_json(WORK / f"papers_{d}.json", {}) or {}).get("candidates", [])}
    for f in src.get("feeds", []):
        try:
            items = parse_items(http_get(f["url"], timeout=40, retries=3))
        except Exception as e:
            kept = {k: c for k, c in earlier.items() if c["signals"].get("venue") == f["venue"]}
            cands.update(kept)   # a feed that fails on a re-run keeps today's earlier candidates
            log(f"  WARNING research feed {f['name']} failed: {e}" + (f" (kept {len(kept)} earlier candidates)" if kept else ""))
            continue
        kept = 0
        for it in items:
            if not it["title"] or not is_research(f, it):
                continue
            title = re.sub(r"^\[[^\]]+\]\s*", "", it["title"])
            authors = it["authors"]
            if "nber.org" in it["link"] and " -- by " in title:
                title, _, by = title.partition(" -- by ")
                authors = [x.strip() for x in re.split(r",\s*|\s+and\s+", by) if x.strip()]
            day = _date(it["date"]) or end.date()
            if day < d - dt.timedelta(days=RECENT_DAYS) or day > end.date():
                continue
            m = re.search(r"/papers/(w\d+)", it["link"])
            cid = f"nber-{m.group(1)}" if m else f"doi-{slug(it['doi'])}" if it["doi"] else f"{slug(f['name'])}-{slug(title)[:40]}"
            if cid in seen or cid in cands:
                continue
            links = {"paper": re.sub(r"[?#].*$", "", it["link"]) if "nber.org" in it["link"] else it["link"].replace("?af=R", "").split("&rss=")[0]}
            if it["doi"]:
                links["doi"] = f"https://doi.org/{it['doi']}"
            tw = words(title) - common
            press = sum(1 for h in heads if len(tw & h) >= 2)
            abstract = "" if re.match(r"^[\w .&]+,\s*(Volume|Published online)", it["desc"]) else it["desc"]
            cands[cid] = {"id": cid, "title": title, "authors": authors, "abstract": abstract,
                          "announced": dt.datetime(day.year, day.month, day.day, 12, 0, tzinfo=TZ).isoformat(),
                          "categories": [f["venue"]], "links": {k: v for k, v in links.items() if v.startswith("https://")},
                          "signals": {"venue": f["venue"], "tier": f.get("tier", "major"), "press": press or None},
                          "score": (3 if f.get("tier") == "flagship" else 1) + 2 * min(press, 3) + (1 if day >= start.date() else 0)}
            kept += 1
        n_feed[f["name"]] = kept
        log(f"  research feed {f['name']}: {kept} research items")
    cats = src.get("arxiv_categories") or []
    if cats:   # arXiv papers only when the press picked them up (no attention signal otherwise)
        from fetch_papers import listing_sweep
        for pid, p in listing_sweep(cats, start, end).items():
            press = sum(1 for h in heads if len((words(p["title"]) - common) & h) >= 2)
            if press and pid not in seen:
                cands[pid] = {"id": pid, "title": p["title"], "authors": p["authors"], "abstract": "", "announced": p["announced"],
                              "categories": p["subjects"], "links": {"arxiv": f"https://arxiv.org/abs/{pid}"},
                              "signals": {"venue": "arXiv", "tier": "preprint", "press": press}, "score": 2 * min(press, 3)}
    pool = sorted(cands.values(), key=lambda c: (-c["score"], c["announced"]), reverse=False)[:a.size]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f"papers_{d}.json").write_text(json.dumps({"meta": {"date": d.isoformat(), "domain": DOMAIN, "feeds": n_feed,
                                                                 "n_candidates": len(cands)}, "candidates": list(cands.values())}, indent=1))
    L = [f"# {DOM['name']} research shortlist for {d}", f"{len(cands)} research items from {len(n_feed)} feeds (last {RECENT_DAYS} days, none featured in "
         f"the last {DEDUP_DAYS}). Score = venue (flagship 3, major 1) + 2 x press coverage (headlines sharing title words, max 3) + 1 if this week.", ""]
    for c in pool:
        s = c["signals"]
        L.append(f"- [{c['id']}] {c['title']}  ({s['venue']}, {c['announced'][:10]}; score {c['score']}"
                 + (f"; press {s['press']}" if s.get("press") else "") + ")")
        L.append(f"    {', '.join(c['authors'][:4])}{' et al.' if len(c['authors']) > 4 else ''}  <{c['links'].get('paper') or c['links'].get('arxiv')}>")
        if c["abstract"]:
            L.append(f"    {' '.join(c['abstract'].split()[:45])}…")
    md = "\n".join(L)
    (WORK / f"shortlist_{d}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
