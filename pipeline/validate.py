"""Validate digest files before publishing. Exit code 1 on any error.

Checks: schema, section headings, 250-350 word bodies (300-400 for Oct 26 - Nov 2), no Sunday digests, tags/categories from the fixed
taxonomy, item caps, time windows (72h weekday / 7d weekend papers; 72h news),
duplicates against the previous 7 days, https links, and no HTML in text.

Usage: python pipeline/validate.py [DATE ...]   (default: every file in data/days/)
"""
import datetime as dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DAYS, DOM, DOMAIN, config, edition, featured_ids, is_digest_day, news_window, other_tabs,  # noqa: E402
                    paper_window, parse_date, word_count)
from stories import tokens  # noqa: E402

NEWS_SECTIONS = ["Context", "What happened", "Why it matters", "What to watch"]
PAPER_SECTIONS = ["Problem", "Existing approaches", "Key idea", "Results", "Why it matters"]
WORD_LIMITS = (225, 250, 350, 375)          # hard min, target min, target max, hard max
OLD_WORD_LIMITS = (270, 300, 400, 430)      # the first digests (Oct 26 - Nov 2), written before the change
OLD_LIMIT_DAYS = (dt.date(2026, 10, 26), dt.date(2026, 11, 2))
MAX_NEWS, MAX_PAPERS = DOM["news"], DOM["papers"]
RESEARCH_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{3,100}$")
RECENT_RESEARCH_DAYS = 45   # news-led domains: journal and working papers from the last 45 days (fetch_research.py)
HTML_RE = re.compile(r"<\s*[a-zA-Z/!]")
ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}$")
SOURCE_RULES_FROM = dt.date(2026, 11, 5)   # two-source rule, placeholder affiliations, one story per tab: errors from here on
OFFICIAL_HOST = re.compile(r"(?:\.gov|\.gov\.[a-z]{2}|\.gc\.ca|(?:^|\.)canada\.ca|\.europa\.eu|\.int|\.edu|\.ac\.[a-z]{2}|\.mil)$")
PAPER_HOSTS = {"doi.org", "arxiv.org", "nature.com", "science.org", "cell.com", "nejm.org", "thelancet.com",
               "jamanetwork.com", "pnas.org", "nber.org", "biorxiv.org", "medrxiv.org", "eurekalert.org"}
PLACEHOLDER = re.compile(r"^\s*(?:n/?a|none|null|unknown|tbd|tba|various|multiple|\.{2,}|-+|\?+|not (?:listed|shown|stated|given|"
                         r"available|provided|found)|see (?:the )?(?:paper|text|article))\s*\.?\s*$|placeholder|affiliations? "
                         r"(?:not|unavailable|unknown)", re.I)


def site(url):
    """Registered site of a URL (news.example.co.uk -> example.co.uk), for counting independent sources."""
    h = (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    parts = h.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "gov", "gc", "ac", "org", "net", "edu", "nhs"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def primary_sites():
    src = config("sources")
    feeds = [f for f in src.get("news_feeds", []) if f.get("tier") == "primary"] + src.get("research", {}).get("feeds", [])
    return {site(f["url"]) for f in feeds if f.get("url")} | PAPER_HOSTS


PRIMARY = primary_sites()


def is_primary(url, title=""):
    """Official, journal or listed primary site, or the subject's own site (anthropic.com for "Anthropic reports ...")."""
    s = site(url)
    own = len(s.split(".")[0]) >= 3 and re.search(rf"\b{re.escape(s.split('.')[0])}", title.lower()) is not None
    return s in PRIMARY or own or bool(OFFICIAL_HOST.search((urllib.parse.urlparse(url).hostname or "").lower()))


def check_day(path, tax):
    errs, warns = [], []
    E, W = errs.append, warns.append
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"], []
    d = parse_date(path.stem)
    if j.get("date") != path.stem:
        E(f"date field {j.get('date')!r} != filename")
    if j.get("edition") != edition(d):
        E(f"edition should be {edition(d)!r}")
    if not is_digest_day(d):
        E("no digest on Sundays (the Week in review covers the week)")
    news, papers = j.get("news", []), j.get("papers", [])
    if len(news) > MAX_NEWS:
        E(f"{len(news)} news items (max {MAX_NEWS})")
    if len(papers) > MAX_PAPERS:
        E(f"{len(papers)} papers (max {MAX_PAPERS})")
    seen_papers, seen_stories = featured_ids(d)
    strict = d >= SOURCE_RULES_FROM
    elsewhere = other_tabs(d)
    elsewhere_papers = {x["key"]: x for x in other_tabs(d, 60) if x["kind"] == "paper"}

    def strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)

    for s in strings(j):
        if HTML_RE.search(s):
            E(f"HTML-like markup in text: {s[:80]!r}")
            break

    def body_check(item, label, expected):
        heads = [s.get("heading") for s in item.get("sections", [])]
        if heads != expected:
            E(f"{label}: sections must be {expected}, got {heads}")
        n = sum(word_count(s.get("body", "")) for s in item.get("sections", []))
        old = OLD_LIMIT_DAYS[0] <= d <= OLD_LIMIT_DAYS[1]
        HARD_MIN, SOFT_MIN, SOFT_MAX, HARD_MAX = OLD_WORD_LIMITS if old else WORD_LIMITS
        if not HARD_MIN <= n <= HARD_MAX:
            E(f"{label}: {n} words (must be {SOFT_MIN}-{SOFT_MAX}; hard limits {HARD_MIN}-{HARD_MAX})")
        elif not SOFT_MIN <= n <= SOFT_MAX:
            W(f"{label}: {n} words (target {SOFT_MIN}-{SOFT_MAX})")
        tl = item.get("tldr", "")
        if not tl or word_count(tl) > 35:
            E(f"{label}: tldr missing or over 35 words")
        for sec in item.get("sections", []):
            if re.search(r"(?m)^\s*([-*\u2022]|\d+[.)])\s+", sec.get("body", "")):
                E(f"{label}: section {sec.get('heading')!r} contains a list; write prose paragraphs")
        for f in ("title",):
            if not item.get(f):
                E(f"{label}: missing {f}")

    ns, ne = news_window(d)
    retired = tax.get("retired", {}) if d.isoformat() <= tax.get("retired", {}).get("until", "") else {}
    cats = set(tax["news_categories"]) | set(retired.get("news_categories", []))
    ids = set()
    for i, n in enumerate(news):
        label = f"news[{i}] {n.get('title', '')[:50]!r}"
        body_check(n, label, NEWS_SECTIONS)
        if n.get("id") in ids or not n.get("id"):
            E(f"{label}: missing/duplicate id")
        ids.add(n.get("id"))
        if n.get("category") not in cats:
            E(f"{label}: category {n.get('category')!r} not in taxonomy")
        if not n.get("story_key"):
            E(f"{label}: missing story_key")
        elif n["story_key"] in seen_stories:
            E(f"{label}: story_key {n['story_key']!r} already featured in the last 7 days")
        srcs = n.get("sources", [])
        if not srcs or any(not str(s.get("url", "")).startswith("https://") or not s.get("name") for s in srcs):
            E(f"{label}: needs >=1 source with name and https url")
        elif not any(is_primary(s["url"], n.get("title", "")) for s in srcs) and len({site(s["url"]) for s in srcs}) < 2:
            (E if strict else W)(f"{label}: needs a primary source (official, journal or the company's own site) or >=2 "
                                 f"independent outlets; got {sorted({site(s['url']) for s in srcs})}")
        tk = tokens(n.get("title", ""))
        for x in elsewhere:
            xt = tokens(x["title"])
            shared = len(tk & xt)
            if (n.get("story_key") and n.get("story_key") == x["key"]) or (shared >= 3 and shared >= 0.5 * min(len(tk), len(xt))):
                W(f"{label}: looks like the story {x['tab']} ran on {x['date']} ({x['title']!r}); each story goes on one tab")
        try:
            t = dt.datetime.fromisoformat(n["published"])
            if not ns <= t <= ne:
                E(f"{label}: published {t} outside news window {ns} -> {ne}")
        except (KeyError, ValueError, TypeError):
            E(f"{label}: missing/invalid published timestamp")

    ps, pe = paper_window(d)
    tags = set(tax["paper_tags"]) | set(retired.get("paper_tags", []))
    for i, p in enumerate(papers):
        label = f"paper[{i}] {p.get('id')}"
        body_check(p, label, PAPER_SECTIONS)
        if DOMAIN == "ai" and not ARXIV_RE.match(str(p.get("id", ""))):
            E(f"{label}: id must be an arXiv id")
        if DOMAIN != "ai" and not (ARXIV_RE.match(str(p.get("id", ""))) or RESEARCH_ID.match(str(p.get("id", "")))):
            E(f"{label}: id must come from the research shortlist")
        if p.get("id") in ids:
            E(f"{label}: duplicate id in this digest")
        ids.add(p.get("id"))
        if p.get("id") in seen_papers:
            E(f"{label}: already featured in the last 7 days")
        if p.get("id") in elsewhere_papers:
            x = elsewhere_papers[p["id"]]
            (E if strict else W)(f"{label}: already featured on the {x['tab']} tab ({x['date']}); one paper, one tab")
        for a in p.get("affiliations") or []:
            if PLACEHOLDER.search(str(a)):
                (E if strict else W)(f"{label}: placeholder affiliation {a!r}; leave affiliations empty when no page shows them")
        ptags = p.get("tags", [])
        if p.get("primary_tag") not in tags:
            E(f"{label}: primary_tag {p.get('primary_tag')!r} not in taxonomy")
        if not ptags or ptags[0] != p.get("primary_tag"):
            E(f"{label}: tags must start with primary_tag")
        if len(ptags) > 4 or len(set(ptags)) != len(ptags):
            E(f"{label}: 1-4 unique tags allowed")
        for t in ptags:
            if t not in tags:
                E(f"{label}: tag {t!r} not in taxonomy")
        if not p.get("authors"):
            E(f"{label}: missing authors")
        links = p.get("links", {})
        if DOMAIN == "ai" and not str(links.get("arxiv", "")).startswith("https://arxiv.org/abs/"):
            E(f"{label}: links.arxiv must be https://arxiv.org/abs/<id>")
        if DOMAIN != "ai" and not any(str(links.get(k, "")).startswith("https://") for k in ("paper", "doi", "arxiv")):
            E(f"{label}: needs a paper, doi or arxiv https link")
        for k, v in links.items():
            if v and not str(v).startswith("https://"):
                E(f"{label}: link {k} must be https")
        try:
            t = dt.datetime.fromisoformat(p["announced"])
            lo = ps if DOMAIN == "ai" else pe - dt.timedelta(days=RECENT_RESEARCH_DAYS)
            if not lo <= t <= pe:
                E(f"{label}: announced {t} outside paper window {lo} -> {pe}")
        except (KeyError, ValueError, TypeError):
            E(f"{label}: missing/invalid announced timestamp")
    primaries = [p.get("primary_tag") for p in papers]
    for t in set(primaries):
        if primaries.count(t) > 3:
            E(f"diversity: {primaries.count(t)} papers share primary tag {t!r} (max 3)")
    return errs, warns


def main():
    tax = config("taxonomy")
    files = [DAYS / f"{a}.json" for a in sys.argv[1:]] or sorted(DAYS.glob("*.json"))
    bad = 0
    for f in files:
        if not f.exists():
            print(f"✗ {f.name}: missing")
            bad += 1
            continue
        errs, warns = check_day(f, tax)
        status = "✗" if errs else "✓"
        print(f"{status} {f.name}: {len(errs)} errors, {len(warns)} warnings")
        for e in errs:
            print(f"    ERROR {e}")
        for w in warns:
            print(f"    warn  {w}")
        bad += bool(errs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
