"""Stage 1 of paper selection (no LLM): find every paper announced in the window,
attach cheap signals, and print a ~40-paper shortlist for Claude to judge.

Sources:
  * arXiv "pastweek" listing pages, one per category in config/sources.json
    (completeness + exact announcement dates; catches fresh papers from strong authors
    before any votes exist). The big arXiv search API is avoided: it rate-limits (429/503).
  * alphaXiv Hot feed via MCP (free; a snapshot is saved to data/state/alphaxiv_hot/)
  * Hugging Face Daily Papers (community upvotes, org, GitHub repo)
  * arXiv abstract pages only for the ~100-250 papers that have any signal (abstracts).

Usage: python pipeline/fetch_papers.py --date 2026-11-02 [--size 40]
Writes work/papers_<date>.json (all scored candidates) and work/shortlist_<date>.md.
"""
import argparse
import datetime as dt
import html
import json
import math
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET_XML
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ET, STATE, UTC, WORK, arxiv_announce_time, config, edition,  # noqa: E402
                    featured_ids, http_get, paper_window, parse_date, today_et)

NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
      "os": "http://a9.com/-/spec/opensearch/1.1/"}
ARXIV_API = "https://export.arxiv.org/api/query"
ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")
VENUE_RE = re.compile(r"\b(NeurIPS|ICLR|ICML|CVPR|ICCV|ECCV|ACL|EMNLP|NAACL|CoRL|RSS|AAAI|IJCAI|COLM|KDD|TMLR|JMLR|Nature|Science)\b")
ACCEPT_RE = re.compile(r"accept|to appear|published|camera.ready|oral|spotlight", re.I)
SURVEY_RE = re.compile(r"\b(survey|a review|systematic review|overview of)\b", re.I)
POSITION_RE = re.compile(r"\bposition paper\b|\bposition:\s", re.I)
CODE_RE = re.compile(r"github\.com|huggingface\.co/|code (is|will be) (publicly )?available|we (open[- ]source|release)", re.I)
OLD_CROSSLIST_SLACK = dt.timedelta(days=5)
LARGE_TEAM = 15  # v1 older than window start - slack => old paper, just cross-listed


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- arXiv listing pages
def parse_listing(page):
    """-> {id: {title, authors, subjects, listing_date}} from a /list/<cat>/pastweek page."""
    out = {}
    parts = re.split(r"<h3>(.*?)</h3>", page)
    for i in range(1, len(parts), 2):
        m = re.match(r"\w{3}, (\d{1,2} \w{3} \d{4})", parts[i].strip())
        if not m:
            continue
        ldate = dt.datetime.strptime(m.group(1), "%d %b %Y").date()
        for dt_block, dd_block in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", parts[i + 1], re.S):
            idm = re.search(r'/abs/(\d{4}\.\d{4,5})', dt_block)
            if not idm:
                continue
            tm = re.search(r"list-title[^>]*>.*?</span>(.*?)</div>", dd_block, re.S)
            am = re.search(r"list-authors'>(.*?)</div>", dd_block, re.S)
            sm = re.search(r"list-subjects'>.*?</span>(.*?)</div>", dd_block, re.S)
            clean = lambda x: " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)).split()) if x else ""
            out[idm.group(1)] = {
                "title": clean(tm.group(1)) if tm else "",
                "authors": [clean(a) for a in re.findall(r"<a [^>]*>(.*?)</a>", am.group(1))] if am else [],
                "subjects": re.findall(r"\(([a-z\-]+(?:\.[A-Za-z\-]+)?)\)", clean(sm.group(1)) if sm else ""),
                "listing_date": ldate,
            }
    return out


def listing_sweep(cats):
    """Union of pastweek listings. Announcement time = listing date - 1 day, 20:00 ET."""
    allp = {}
    for c in cats:
        got = {}
        for skip in (0, 2000, 4000):
            try:
                page = http_get(f"https://arxiv.org/list/{c}/pastweek?skip={skip}&show=2000", timeout=90)
            except Exception as e:
                log(f"  WARNING listing {c} skip={skip} failed: {e}")
                break
            batch = parse_listing(page)
            got.update(batch)
            if len(batch) < 2000:
                break
            time.sleep(1)
        for pid, p in got.items():
            prev = allp.get(pid)
            if prev is None or p["listing_date"] < prev["listing_date"]:
                allp[pid] = p
        log(f"  listing {c}: {len(got)} entries (union {len(allp)})")
        time.sleep(1)
    for p in allp.values():
        ld = p.pop("listing_date") - dt.timedelta(days=1)
        p["announced"] = dt.datetime(ld.year, ld.month, ld.day, 20, 0, tzinfo=ET).isoformat()
    return allp


def parse_feed(xml_text):
    root = ET_XML.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        raw_id = e.findtext("a:id", "", NS).rsplit("/abs/", 1)[-1]
        pid = re.sub(r"v\d+$", "", raw_id)
        if not ID_RE.match(pid):
            continue
        pub = dt.datetime.fromisoformat(e.findtext("a:published", "", NS).replace("Z", "+00:00"))
        authors, affs = [], set()
        for a in e.findall("a:author", NS):
            authors.append(" ".join(a.findtext("a:name", "", NS).split()))
            for af in a.findall("arxiv:affiliation", NS):
                affs.add(af.text.strip())
        prim = e.find("arxiv:primary_category", NS)
        out.append({
            "id": pid,
            "title": " ".join(e.findtext("a:title", "", NS).split()),
            "abstract": " ".join(e.findtext("a:summary", "", NS).split()),
            "authors": authors,
            "affiliations": sorted(affs),
            "comment": " ".join((e.findtext("arxiv:comment", "", NS) or "").split()),
            "primary_category": prim.get("term") if prim is not None else "",
            "categories": [c.get("term") for c in e.findall("a:category", NS)],
            "submitted": pub.isoformat(),
        })
    return out


def abs_page(pid):
    """Metadata from the arXiv abstract page (the search API rate-limits shared cloud IPs)."""
    s = http_get(f"https://arxiv.org/abs/{pid}", timeout=45, retries=3)
    clean = lambda x: " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)).split())
    title = re.search(r'<meta name="citation_title" content="([^"]+)"', s)
    ab = re.search(r'<blockquote class="abstract[^"]*">(.*?)</blockquote>', s, re.S)
    com = re.search(r'<td class="tablecell comments[^"]*">(.*?)</td>', s, re.S)
    subj = re.search(r'<td class="tablecell subjects">(.*?)</td>', s, re.S)
    v1 = re.search(r"\[v1\]</strong>\s*([^<(]+)", s)
    authors = []
    for a in re.findall(r'<meta name="citation_author" content="([^"]+)"', s):
        last, _, first = html.unescape(a).partition(", ")
        authors.append(f"{first} {last}".strip())
    cats = re.findall(r"\(([a-z\-]+\.[A-Za-z\-]+)\)", subj.group(1)) if subj else []
    sub = None
    if v1:
        try:
            sub = dt.datetime.strptime(v1.group(1).strip(), "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=UTC).isoformat()
        except ValueError:
            pass
    gh = None
    for block in (ab.group(1) if ab else "", com.group(1) if com else ""):
        m = re.search(r'href="(https?://github\.com/[^"#?]+)"', block)
        if m:
            gh = m.group(1).rstrip("/.")
            break
    return {
        "id": pid,
        "github": gh,
        "title": html.unescape(title.group(1)) if title else "",
        "abstract": re.sub(r"^Abstract:\s*", "", clean(ab.group(1))) if ab else "",
        "authors": authors,
        "affiliations": [],
        "comment": clean(com.group(1)) if com else "",
        "primary_category": cats[0] if cats else "",
        "categories": cats,
        "submitted": sub,
    }


def arxiv_by_ids(ids, workers=4):
    from concurrent.futures import ThreadPoolExecutor
    out = {}

    def one(pid):
        try:
            return abs_page(pid)
        except Exception as e:
            log(f"  WARNING abs page {pid} failed: {e}")
            return None

    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, sorted(ids)):
            if r:
                out[r["id"]] = r
    return out


# ---------------------------------------------------------------- signals
def hot_snapshots(d, start):
    """alphaXiv Hot ranks -> ({id: best_rank}, {id: days_on_list}, note).

    The live run (d == today) saves/overwrites today's snapshot; backfills never write.
    Ranks merge every snapshot inside the window, so multi-day presence is visible.
    """
    snap_dir = STATE / "alphaxiv_hot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    today = today_et()
    live_ids = None
    try:
        from alphaxiv import AlphaXiv
        live_ids = AlphaXiv().hot_feed(200)
        if d == today:
            (snap_dir / f"{today.isoformat()}.json").write_text(
                json.dumps({"fetched_at": dt.datetime.now(UTC).isoformat(), "ids": live_ids}, indent=0))
    except Exception as e:  # never let one source kill the run
        log(f"  WARNING alphaXiv hot feed failed: {e}")
    snaps = sorted((parse_date(f.stem), f) for f in snap_dir.glob("*.json"))
    lists = [json.loads(f.read_text())["ids"] for sd, f in snaps if start.date() <= sd <= d]
    note = ""
    if not lists and live_ids:
        lists, note = [live_ids], ("alphaXiv ranks come from today's feed (hindsight; backfill only)" if d < today else "")
    elif not lists:
        older = [f for sd, f in snaps if sd <= d]
        if older:
            lists, note = [json.loads(older[-1].read_text())["ids"]], f"alphaXiv unavailable; using stale snapshot {older[-1].stem}"
    best, days = {}, {}
    for ids in lists:
        for rank, pid in enumerate(ids, 1):
            if ID_RE.match(pid):
                best[pid] = min(best.get(pid, 10**9), rank)
                days[pid] = days.get(pid, 0) + 1
    return best, days, note


def hf_daily(dates):
    out = {}
    for day in dates:
        try:
            items = json.loads(http_get(f"https://huggingface.co/api/daily_papers?date={day.isoformat()}&limit=100"))
        except Exception as e:
            log(f"  WARNING HF daily papers {day} failed: {e}")
            continue
        for it in items:
            p = it.get("paper", {})
            pid = p.get("id", "")
            if not ID_RE.match(pid):
                continue
            org = it.get("organization") or p.get("organization") or {}
            prev = out.get(pid, {})
            out[pid] = {
                "upvotes": max(prev.get("upvotes", 0), p.get("upvotes") or 0),
                "org": org.get("fullname") or org.get("name") or prev.get("org"),
                "github": p.get("githubRepo") or prev.get("github"),
                "summary": " ".join((p.get("summary") or "").split()),
                "title": p.get("title"),
                "authors": [a.get("name", "") for a in p.get("authors", [])],
            }
        time.sleep(0.5)
    return out


def norm_name(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    parts = [p for p in re.split(r"[\s.\-]+", s) if p]
    full = " ".join(parts)
    short = f"{parts[0]} {parts[-1]}" if len(parts) >= 2 else full
    return full, short


def build_matchers():
    nb = config("notable")
    names = set()
    for n in nb["researchers"]:
        names.update(norm_name(n))
    orgs = {t: [o.lower() for o in nb["orgs"][t]] for t in ("frontier", "academic")}
    return names, orgs


def notable(authors, names):
    return [a for a in authors if set(norm_name(a)) & names]


def org_tier(texts, orgs):
    blob = " | ".join(t.lower() for t in texts if t)
    if blob:
        for tier in ("frontier", "academic"):
            for o in orgs[tier]:
                if re.search(r"(^|[^a-z])" + re.escape(o) + r"([^a-z]|$)", blob):
                    return tier, o
    return None, None


def score(p):
    s, flags = 0.0, []
    if p.get("hot_rank"):
        s += 1.0 * max(0.0, 1 - (p["hot_rank"] - 1) / 200)
        s += 0.15 * max(0, p.get("hot_days", 0) - 1)
    up = p.get("hf_upvotes") or 0
    if up:
        s += 0.8 * min(1.0, math.log1p(up) / math.log1p(100))
    if p.get("notable_authors"):
        s += 0.5
    s += {"frontier": 0.4, "academic": 0.2}.get(p.get("org_tier"), 0.0)
    if len(p.get("authors", [])) >= LARGE_TEAM:
        s += 0.15
    if p.get("has_code"):
        s += 0.1
    if p.get("venue"):
        s += 0.1
    if SURVEY_RE.search(p["title"]):
        s -= 0.3
        flags.append("survey")
    if POSITION_RE.search(p["title"]):
        s -= 0.15
        flags.append("position")
    return round(s, 3), flags


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today_et().isoformat())
    ap.add_argument("--size", type=int, default=40)
    a = ap.parse_args()
    d = parse_date(a.date)
    start, end = paper_window(d)
    src = config("sources")
    cats = src["arxiv_categories"]
    log(f"Digest {d} ({edition(d)}): papers announced {start:%a %b %d %H:%M} -> {end:%a %b %d %H:%M} ET")

    listing = listing_sweep(cats)
    in_window = {pid: p for pid, p in listing.items()
                 if start <= dt.datetime.fromisoformat(p["announced"]) <= end}
    log(f"  {len(in_window)} listed papers announced in window")
    hot_best, hot_days, hot_note = hot_snapshots(d, start)
    hf_dates = sorted({(start + dt.timedelta(days=i)).date() for i in range((end - start).days + 1)} | {d})
    hf = hf_daily(hf_dates)

    names, orgs = build_matchers()
    pre = {pid for pid, p in in_window.items() if pid in hot_best or pid in hf or notable(p["authors"], names)
           or len(p["authors"]) >= LARGE_TEAM}  # big-team tech reports often come from major labs
    pre |= {pid for pid in set(hot_best) | set(hf) if pid not in listing}  # outside our categories / listing
    log(f"  looking up metadata for {len(pre)} papers with signals")
    meta = arxiv_by_ids(pre)

    already, _ = featured_ids(d)
    cand = []
    for pid in pre:
        m, l, h = meta.get(pid), listing.get(pid), hf.get(pid, {})
        if not m and not l:
            continue
        p = dict(m or {"id": pid, "title": l["title"], "abstract": h.get("summary", ""), "authors": l["authors"],
                       "affiliations": [], "comment": "", "primary_category": (l["subjects"] or [""])[0],
                       "categories": l["subjects"], "submitted": None})
        if not p.get("abstract"):
            p["abstract"] = h.get("summary", "")
        if l and l["authors"]:
            p["authors"] = l["authors"]
        p["announced"] = l["announced"] if l else (
            arxiv_announce_time(dt.datetime.fromisoformat(p["submitted"])).isoformat() if p.get("submitted") else None)
        if not p["announced"] or not (start <= dt.datetime.fromisoformat(p["announced"]) <= end):
            continue
        if p.get("submitted") and dt.datetime.fromisoformat(p["submitted"]) < start - OLD_CROSSLIST_SLACK:
            continue  # an old paper that was merely cross-listed into a category this week
        if not any(c in cats or c.startswith(("cs.", "stat.", "eess.")) for c in p["categories"]):
            continue
        p["hot_rank"] = hot_best.get(pid)
        p["hot_days"] = hot_days.get(pid, 0)
        p["hf_upvotes"] = h.get("upvotes")
        p["hf_org"] = h.get("org")
        p["github"] = h.get("github") or p.get("github")
        p["notable_authors"] = notable(p["authors"], names)
        p["org_tier"], p["org_match"] = org_tier([p.get("hf_org")] + p.get("affiliations", []), orgs)
        p["has_code"] = bool(p.get("github") or CODE_RE.search(p["abstract"] + " " + p.get("comment", "")))
        p["venue"] = bool(VENUE_RE.search(p.get("comment", "")) and ACCEPT_RE.search(p.get("comment", "")))
        p["already_featured"] = pid in already
        p["score"], p["flags"] = score(p)
        cand.append(p)

    cand.sort(key=lambda p: -p["score"])
    pool = [p for p in cand if not p["already_featured"]]
    pick, seen = [], set()

    def take(ps, n):
        for p in ps[:n]:
            if p["id"] not in seen and len(pick) < a.size:
                pick.append(p)
                seen.add(p["id"])

    take(sorted([p for p in pool if p["hot_rank"]], key=lambda p: p["hot_rank"]), 10)
    take(sorted([p for p in pool if p["hf_upvotes"]], key=lambda p: -p["hf_upvotes"]), 10)
    take([p for p in pool if p["notable_authors"] or p["org_tier"] == "frontier"], 8)
    take(pool, a.size)
    pick.sort(key=lambda p: -p["score"])

    WORK.mkdir(exist_ok=True)
    info = {"date": d.isoformat(), "edition": edition(d), "window": [start.isoformat(), end.isoformat()],
            "n_listed_in_window": len(in_window), "n_with_signals": len(cand),
            "n_hot": sum(1 for p in cand if p["hot_rank"]), "n_hf": sum(1 for p in cand if p["hf_upvotes"]),
            "hot_note": hot_note, "excluded_already_featured": sorted(already & {p["id"] for p in cand})}
    (WORK / f"papers_{d}.json").write_text(json.dumps({"meta": info, "candidates": cand}, indent=1, default=str))

    lines = [f"# Paper shortlist for {d} ({edition(d)})",
             f"Window (arXiv announcement time): {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} ET",
             f"Announced in window: {info['n_listed_in_window']} | with any signal: {info['n_with_signals']} | "
             f"on alphaXiv Hot: {info['n_hot']} | on HF Daily: {info['n_hf']}"
             + (f" | NOTE: {hot_note}" if hot_note else ""),
             f"Already featured in last 7 days (excluded): {', '.join(info['excluded_already_featured']) or 'none'}", ""]
    for i, p in enumerate(pick, 1):
        sig = [f"score {p['score']}", f"announced {p['announced'][:10]}", p["primary_category"]]
        if p["hot_rank"]:
            sig.append(f"alphaXiv hot #{p['hot_rank']}" + (f" ({p['hot_days']} days)" if p["hot_days"] > 1 else ""))
        if p["hf_upvotes"]:
            sig.append(f"HF {p['hf_upvotes']} upvotes")
        if p["org_match"] or p.get("hf_org"):
            sig.append(f"org: {p.get('hf_org') or p['org_match']}")
        if p["notable_authors"]:
            sig.append("notable: " + ", ".join(p["notable_authors"][:3]))
        if len(au := p["authors"]) >= LARGE_TEAM:
            sig.append(f"large team ({len(au)} authors)")
        if p["has_code"]:
            sig.append("code")
        if p["venue"]:
            sig.append("venue")
        sig += p["flags"]
        au = p["authors"]
        au_s = ", ".join(au[:3]) + (f", ... {au[-1]}" if len(au) > 3 else "") + f" (n={len(au)})"
        lines += [f"## [{i}] {p['id']} — {p['title']}", " | ".join(sig), f"Authors: {au_s}"]
        if p.get("comment"):
            lines.append(f"Comment: {p['comment'][:200]}")
        lines += [f"Abstract: {p['abstract'] or '(unavailable)'}", ""]
    md = "\n".join(lines)
    (WORK / f"shortlist_{d}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
