"""Validate digest files before publishing. Exit code 1 on any error.

Checks: schema, section headings, 300-400 word bodies, tags/categories from the fixed
taxonomy, item caps, time windows (72h weekday / 7d weekend papers; 72h news),
duplicates against the previous 7 days, https links, and no HTML in text.

Usage: python pipeline/validate.py [DATE ...]   (default: every file in data/days/)
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DAYS, config, edition, featured_ids, news_window, paper_window,  # noqa: E402
                    parse_date, word_count)

NEWS_SECTIONS = ["Context", "What happened", "Why it matters", "What to watch"]
PAPER_SECTIONS = ["Problem", "Existing approaches", "Key idea", "Results", "Why it matters"]
HARD_MIN, SOFT_MIN, SOFT_MAX, HARD_MAX = 270, 300, 400, 430
MAX_NEWS, MAX_PAPERS = 2, 5
HTML_RE = re.compile(r"<\s*[a-zA-Z/!]")
ARXIV_RE = re.compile(r"^\d{4}\.\d{4,5}$")


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
    news, papers = j.get("news", []), j.get("papers", [])
    if len(news) > MAX_NEWS:
        E(f"{len(news)} news items (max {MAX_NEWS})")
    if len(papers) > MAX_PAPERS:
        E(f"{len(papers)} papers (max {MAX_PAPERS})")
    seen_papers, seen_stories = featured_ids(d)

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
        if not HARD_MIN <= n <= HARD_MAX:
            E(f"{label}: {n} words (must be {SOFT_MIN}-{SOFT_MAX}; hard limits {HARD_MIN}-{HARD_MAX})")
        elif not SOFT_MIN <= n <= SOFT_MAX:
            W(f"{label}: {n} words (target {SOFT_MIN}-{SOFT_MAX})")
        tl = item.get("tldr", "")
        if not tl or word_count(tl) > 40:
            E(f"{label}: tldr missing or over 40 words")
        for f in ("title",):
            if not item.get(f):
                E(f"{label}: missing {f}")

    ns, ne = news_window(d)
    cats = set(tax["news_categories"])
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
        try:
            t = dt.datetime.fromisoformat(n["published"])
            if not ns <= t <= ne:
                E(f"{label}: published {t} outside news window {ns} -> {ne}")
        except (KeyError, ValueError, TypeError):
            E(f"{label}: missing/invalid published timestamp")

    ps, pe = paper_window(d)
    tags = set(tax["paper_tags"])
    for i, p in enumerate(papers):
        label = f"paper[{i}] {p.get('id')}"
        body_check(p, label, PAPER_SECTIONS)
        if not ARXIV_RE.match(str(p.get("id", ""))):
            E(f"{label}: id must be an arXiv id")
        if p.get("id") in ids:
            E(f"{label}: duplicate id in this digest")
        ids.add(p.get("id"))
        if p.get("id") in seen_papers:
            E(f"{label}: already featured in the last 7 days")
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
        if not str(links.get("arxiv", "")).startswith("https://arxiv.org/abs/"):
            E(f"{label}: links.arxiv must be https://arxiv.org/abs/<id>")
        for k, v in links.items():
            if v and not str(v).startswith("https://"):
                E(f"{label}: link {k} must be https")
        try:
            t = dt.datetime.fromisoformat(p["announced"])
            if not ps <= t <= pe:
                E(f"{label}: announced {t} outside paper window {ps} -> {pe}")
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
