"""Turn Claude's plain-text write-up (work/writeup_<date>.md) into data/days/<date>.json.

Claude only writes prose + a few fields; paper metadata (title, authors, announcement time,
links, signals) is filled from work/papers_<date>.json (made by fetch_papers.py), so it can't drift.

Write-up format (no JSON escaping needed):

    # DIGEST 2026-10-29
    summary: optional one-line overview of the day

    ## NEWS
    title: Google launches Gemini 4 Carbon
    category: Model Release
    story_key: google-gemini-4-carbon-launch
    published: 2026-10-28T13:00:00-04:00
    sources: Google DeepMind | https://deepmind.google/... ; Reuters | https://www.reuters.com/...
    tldr: one sentence, <= 35 words
    why_selected: one short line
    ### Context
    paragraph(s)...
    ### What happened
    ...
    ### Why it matters
    ...
    ### What to watch
    ...

    ## PAPER 2610.39302
    primary_tag: Theory
    tags: Theory, Pre-training & Data
    affiliations: Brown University, New York University
    tldr: ...
    why_selected: ...
    code: https://github.com/...        (optional; overrides detected repo)
    ### Problem
    ...  (then Existing approaches / Key idea / Results / Why it matters)

Usage: python pipeline/assemble.py --date 2026-10-29 [--backfill] [--domain business|science]
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DAYS, DOMAIN, ROOT, UTC, WORK, arxiv_announce_time, edition, load_json, parse_date  # noqa: E402


def parse_writeup(text):
    head, blocks = {}, []
    cur = None
    sec = None
    for line in text.splitlines():
        if line.startswith("## "):
            kind, _, rest = line[3:].strip().partition(" ")
            cur = {"kind": kind.upper(), "id": rest.strip(), "fields": {}, "sections": []}
            blocks.append(cur)
            sec = None
        elif line.startswith("### ") and cur:
            sec = {"heading": line[4:].strip(), "lines": []}
            cur["sections"].append(sec)
        elif sec is not None:
            sec["lines"].append(line)
        elif cur is None:
            m = re.match(r"^(\w+):\s*(.*)$", line)
            if m:
                head[m.group(1)] = m.group(2).strip()
        else:
            m = re.match(r"^(\w+):\s*(.*)$", line)
            if m:
                cur["fields"][m.group(1)] = m.group(2).strip()
    for b in blocks:
        for s in b["sections"]:
            body = "\n".join(s.pop("lines")).strip()
            s["body"] = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", body))
    return head, blocks


def paper_meta(pid, cands):
    c = cands.get(pid)
    if DOMAIN != "ai":   # research candidates from fetch_research.py carry their own links and signals
        if c is None:
            raise SystemExit(f"PAPER {pid}: not in work/{DOMAIN}/papers_<date>.json (use an id from the shortlist)")
        return {"title": c["title"], "authors": c["authors"], "announced": c["announced"], "categories": c.get("categories", []),
                "links": dict(c["links"]), "signals": {k: v for k, v in c.get("signals", {}).items() if v}}
    if c is None:  # not in the shortlist file: look it up directly
        from fetch_papers import abs_page
        c = abs_page(pid)
        c["announced"] = arxiv_announce_time(dt.datetime.fromisoformat(c["submitted"])).isoformat()
    sig = {k: v for k, v in {"alphaxiv_hot_rank": c.get("hot_rank"), "alphaxiv_hot_days": c.get("hot_days") or None,
                             "hf_upvotes": c.get("hf_upvotes"), "notable_authors": c.get("notable_authors") or None,
                             "org": c.get("hf_org")}.items() if v}
    links = {"arxiv": f"https://arxiv.org/abs/{pid}", "alphaxiv": f"https://www.alphaxiv.org/abs/{pid}"}
    if c.get("github"):
        links["code"] = c["github"]
    return {"title": c["title"], "authors": c["authors"], "announced": c["announced"],
            "categories": c.get("categories", []), "links": links, "signals": sig}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--backfill", action="store_true", help="mark as a backfilled/demo digest")
    a = ap.parse_args()
    d = parse_date(a.date)
    src = WORK / f"writeup_{d}.md"
    head, blocks = parse_writeup(src.read_text(encoding="utf-8"))
    cands = {c["id"]: c for c in (load_json(WORK / f"papers_{d}.json", {}) or {}).get("candidates", [])}
    news, papers = [], []
    for b in blocks:
        f = b["fields"]
        if b["kind"] == "NEWS":
            sources = []
            for part in filter(None, (p.strip() for p in f.get("sources", "").split(" ; "))):
                name, _, url = part.partition("|")
                sources.append({"name": name.strip(), "url": url.strip()})
            news.append({"id": f"{d}-n{len(news) + 1}", "story_key": f.get("story_key", ""), "title": f.get("title", ""),
                         "category": f.get("category", ""), "published": f.get("published", ""),
                         "tldr": f.get("tldr", ""), "why_selected": f.get("why_selected", ""),
                         "sections": b["sections"], "sources": sources})
        elif b["kind"] == "PAPER":
            pid = b["id"]
            m = paper_meta(pid, cands)
            if f.get("code"):
                m["links"]["code"] = f["code"]
            if f.get("project"):
                m["links"]["project"] = f["project"]
            tags = [t.strip() for t in f.get("tags", "").split(",") if t.strip()]
            prim = f.get("primary_tag", tags[0] if tags else "")
            if prim and (not tags or tags[0] != prim):
                tags = [prim] + [t for t in tags if t != prim]
            papers.append({"id": pid, "title": f.get("title") or m["title"], "authors": m["authors"],
                           "affiliations": [x.strip() for x in f.get("affiliations", "").split(",") if x.strip()],
                           "announced": m["announced"], "primary_tag": prim, "tags": tags,
                           "tldr": f.get("tldr", ""), "why_selected": f.get("why_selected", ""),
                           "sections": b["sections"], "links": m["links"], "signals": m["signals"]})
    out = {"date": d.isoformat(), "edition": edition(d),
           "generated_at": dt.datetime.now(UTC).isoformat(timespec="seconds")}
    if a.backfill:
        out["backfill"] = True
    if head.get("summary"):
        out["summary"] = head["summary"]
    out["news"], out["papers"] = news, papers
    DAYS.mkdir(parents=True, exist_ok=True)
    path = DAYS / f"{d}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}: {len(news)} news, {len(papers)} papers")
    out_domain = ["--domain", DOMAIN]
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / "validate.py"), d.isoformat(), *out_domain], capture_output=True, text=True)
    print(r.stdout, end="")
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
