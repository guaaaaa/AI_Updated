"""Validate weekly/monthly trend summaries (data/summaries/<kind>/<id>.json). Exit code 1 on any error.

Checks: schema and ids, publish date, headline length, 2-4 themes per part, 350-500 words per part
(error above 500 or below 300; references are not counted), every paragraph cites evidence, every theme
cites at least two distinct references including one item or source, heating/cooling lists with references,
references resolve (our items, shortlisted papers, numbered sources with https URLs), no HTML or lists.

Usage: python3 pipeline/validate_summary.py [weekly/2026-W44 monthly/2026-10 ...]   (default: all)
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import SUMMARIES, month_days, week_days  # noqa: E402

PART_WORDS = (300, 350, 500)   # hard min, target min, hard max (per part, references excluded)
HEADLINE_MAX = 40
REF_RE = re.compile(r"\[([^\[\]]+)\]")
TOKEN_RES = {"paper": re.compile(r"^\d{4}\.\d{4,5}$"), "news": re.compile(r"^\d{4}-\d{2}-\d{2}-n\d+$"),
             "source": re.compile(r"^S\d+$"), "stats": re.compile(r"^arXiv stats$")}
HTML_RE = re.compile(r"<\s*[a-zA-Z/!]")
LIST_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)


def ref_tokens(text):
    """-> (tokens, bad_brackets) for every [..] group in text."""
    toks, bad = [], []
    for grp in REF_RE.findall(text):
        parts = [t.strip() for t in grp.split(",")]
        kinds = [next((k for k, rx in TOKEN_RES.items() if rx.match(t)), None) for t in parts]
        if None in kinds:
            bad.append(grp)
        else:
            toks += [(k, t) for k, t in zip(kinds, parts)]
    return toks, bad


def words(text):
    return len(REF_RE.sub(" ", text).split())


def check(path):
    errs, warns = [], []
    E, W = errs.append, warns.append
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"], []
    kind, sid = path.parent.name, path.stem
    if s.get("kind") != kind or s.get("id") != sid:
        E(f"kind/id fields ({s.get('kind')}, {s.get('id')}) do not match the path")
    if kind == "weekly":
        mon, sat, sun = week_days(sid)
        start, end, pub = mon, sat, sun
    else:
        start, end = month_days(sid)
        pub = end + dt.timedelta(days=1)
    if s.get("period") != {"start": start.isoformat(), "end": end.isoformat()}:
        E(f"period should be {start}..{end}")
    if s.get("published") != pub.isoformat():
        E(f"published should be {pub}")
    if not s.get("headline") or len(s["headline"].split()) > HEADLINE_MAX:
        E(f"headline missing or over {HEADLINE_MAX} words")
    refs = s.get("refs", {})
    srcs = {x["id"]: x for x in s.get("sources", [])}
    for x in srcs.values():
        if not str(x.get("url", "")).startswith("https://"):
            E(f"source {x['id']} needs an https URL")

    def resolve(toks, where):
        for k, t in toks:
            if k == "source" and t not in srcs:
                E(f"{where}: [{t}] is not listed under SOURCES")
            elif k in ("paper", "news") and t not in refs:
                E(f"{where}: [{t}] is not one of the period's digest items or shortlisted papers")

    used_sources = set()
    for part in ("research", "industry"):
        p = s.get(part)
        if not p:
            E(f"missing {part} part")
            continue
        n = sum(words(t["title"]) + words(t["body"]) for t in p.get("themes", []))
        n += sum(words(h["label"]) for h in p.get("heating", []) + p.get("cooling", []))
        if n > PART_WORDS[2]:
            E(f"{part}: {n} words (max {PART_WORDS[2]})")
        elif n < PART_WORDS[0]:
            E(f"{part}: {n} words (min {PART_WORDS[0]}, target {PART_WORDS[1]}-{PART_WORDS[2]})")
        elif n < PART_WORDS[1]:
            W(f"{part}: {n} words (target {PART_WORDS[1]}-{PART_WORDS[2]})")
        if not 2 <= len(p.get("themes", [])) <= 4:
            E(f"{part}: needs 2-4 themes")
        if not 1 <= len(p.get("heating", [])) <= 4 or len(p.get("cooling", [])) > 3:
            E(f"{part}: needs 1-4 heating entries and at most 3 cooling entries")
        for h in p.get("heating", []) + p.get("cooling", []):
            if not h.get("refs"):
                E(f"{part}: heating/cooling entry '{h.get('label')}' needs a reference")
            if len(h.get("label", "").split()) > 8:
                E(f"{part}: label '{h['label']}' is over 8 words")
            resolve([(next(k for k, rx in TOKEN_RES.items() if rx.match(r)), r) for r in h.get("refs", [])
                     if any(rx.match(r) for rx in TOKEN_RES.values())], f"{part} heating/cooling")
        for t in p.get("themes", []):
            where = f"{part} / '{t['title']}'"
            if HTML_RE.search(t["body"]) or LIST_RE.search(t["body"]):
                E(f"{where}: plain prose only (no HTML, no lists)")
            toks, bad = ref_tokens(t["body"])
            if bad:
                E(f"{where}: unknown bracket content {bad[:3]} (use [2610.12345], [2026-10-27-n1], [S1], [arXiv stats])")
            resolve(toks, where)
            used_sources |= {x for k, x in toks if k == "source"}
            for i, para in enumerate(x for x in t["body"].split("\n\n") if x.strip()):
                if not ref_tokens(para)[0]:
                    E(f"{where}: paragraph {i + 1} cites no evidence")
            distinct = {x for x in toks}
            if len(distinct) < 2 or not any(k in ("paper", "news", "source") for k, _ in distinct):
                E(f"{where}: needs at least two distinct references, including an item or a source")
    for sid_ in set(srcs) - used_sources:
        W(f"source {sid_} is listed but never cited")
    return errs, warns


def main():
    targets = sys.argv[1:]
    paths = [SUMMARIES / f"{t}.json" for t in targets] if targets else sorted(SUMMARIES.glob("*/*.json"))
    bad = 0
    for p in paths:
        if not p.exists():
            print(f"✗ {p}: missing")
            bad += 1
            continue
        errs, warns = check(p)
        bad += bool(errs)
        print(f"{'✗' if errs else '✓'} {p.parent.name}/{p.name}: {len(errs)} errors, {len(warns)} warnings")
        for e in errs:
            print(f"   ERROR {e}")
        for w in warns:
            print(f"   warn  {w}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
