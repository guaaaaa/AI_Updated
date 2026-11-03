"""Turn a trend-summary write-up (work/summary_<id>.md) into data/summaries/<kind>/<id>.json, then validate.

Write-up format (plain text; references in square brackets, several separated by commas):

    # SUMMARY monthly 2026-10
    headline: one sentence, <= 40 words: the month's big picture

    ## RESEARCH
    heating: Short label [field stats, 2610.12345]; Another label [field stats]
    cooling: Short label [field stats]
    ### Theme title
    Paragraph: the field-wide movement [field stats], illustrated by [2610.12345] or [2026-10-27-n1].

    Another paragraph [S1].
    ### Another theme
    ...

    ## INDUSTRY
    heating: ...
    cooling: ...
    ### ...

    ## SOURCES
    S1: Reuters | https://www.reuters.com/...

Reference tokens: arXiv ids (our digest papers or the brief's most-upvoted papers), our news item ids
(e.g. 2026-10-27-n1), S1..Sn (outside sources listed under SOURCES), "field stats" (research statistics across all
new arXiv papers and Hugging Face attention) and "news stats" (industry story statistics).

Usage: python3 pipeline/assemble_summary.py --kind monthly --id 2026-10
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, SUMMARIES, UTC, WORK, load_json, month_days, week_days  # noqa: E402
from validate_summary import ref_tokens  # noqa: E402


def split_entries(line):
    out, depth, cur = [], 0, ""
    for ch in line:
        depth += ch == "["
        depth -= ch == "]"
        if ch == ";" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    res = []
    for e in (x.strip() for x in out):
        if not e:
            continue
        toks, _ = ref_tokens(e)
        res.append({"label": re.sub(r"\s*\[[^\]]*\]", "", e).strip(" -—:"), "refs": [t for _, t in toks]})
    return res


def parse(text):
    head, parts, sources = {}, {}, []
    part = theme = None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip().upper()
            part = name if name in ("RESEARCH", "INDUSTRY", "SOURCES") else None
            if part in ("RESEARCH", "INDUSTRY"):
                parts[part] = {"heating": [], "cooling": [], "themes": []}
            theme = None
        elif line.startswith("### ") and part in parts:
            theme = {"title": line[4:].strip(), "lines": []}
            parts[part]["themes"].append(theme)
        elif part == "SOURCES":
            m = re.match(r"^\s*(S\d+)\s*[:.]\s*(.*?)\s*\|\s*(\S+)\s*$", line)
            if m:
                sources.append({"id": m.group(1), "name": m.group(2), "url": m.group(3)})
        elif theme is not None:
            theme["lines"].append(line)
        elif part in parts:
            m = re.match(r"^(heating|cooling):\s*(.*)$", line.strip(), re.I)
            if m:
                parts[part][m.group(1).lower()] = split_entries(m.group(2))
        else:
            m = re.match(r"^(\w+):\s*(.*)$", line)
            if m:
                head[m.group(1)] = m.group(2).strip()
    for p in parts.values():
        for t in p["themes"]:
            body = "\n".join(t.pop("lines")).strip()
            t["body"] = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", body))
    return head, parts, sources


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["weekly", "monthly"], required=True)
    ap.add_argument("--id", required=True)
    a = ap.parse_args()
    head, parts, sources = parse((WORK / f"summary_{a.id}.md").read_text(encoding="utf-8"))
    allowed = load_json(WORK / f"summary_input_{a.id}.json", {}) or {}
    if a.kind == "weekly":
        start, end, pub = week_days(a.id)
    else:
        start, end = month_days(a.id)
        pub = end + dt.timedelta(days=1)
    refs = {}
    every = [t["body"] for p in parts.values() for t in p["themes"]]
    tokens = [x for b in every for x in ref_tokens(b)[0]]
    tokens += [(None, r) for p in parts.values() for h in p["heating"] + p["cooling"] for r in h["refs"]]
    for _, t in tokens:
        if t in allowed.get("papers", {}):
            refs[t] = {"type": "paper", **allowed["papers"][t]}
        elif t in allowed.get("news", {}):
            refs[t] = {"type": "news", **allowed["news"][t]}
    out = {"kind": a.kind, "id": a.id, "period": {"start": start.isoformat(), "end": end.isoformat()},
           "published": pub.isoformat(), "generated_at": dt.datetime.now(UTC).isoformat(timespec="seconds"),
           "headline": head.get("headline", ""),
           "research": parts.get("RESEARCH"), "industry": parts.get("INDUSTRY"),
           "sources": sources, "refs": dict(sorted(refs.items()))}
    path = SUMMARIES / a.kind / f"{a.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "validate_summary.py"), f"{a.kind}/{a.id}"],
                       capture_output=True, text=True)
    print(r.stdout, end="")
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
