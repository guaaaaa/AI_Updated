"""Raw monthly data for the field-wide trend model (no LLM usage). Cached in work/field/ (git-ignored).

  arxiv : every new paper of the month in our categories, from the arXiv monthly listing pages
          (/list/<cat>/YYYY-MM; titles, authors, subjects; ids of that month only, deduplicated)
  hf    : Hugging Face Daily Papers for every day of the month (title, abstract, upvotes) -- the attention layer
  news  : reputable-outlet AI headlines for the month, from date-bounded Google News searches (3-day windows,
          the queries in config/sources.json) -- the industry layer

Usage: python3 pipeline/field_data.py --from 2024-11 --to 2026-10 [--only arxiv,hf,news] [--force]
"""
import argparse
import datetime as dt
import gzip
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORK, config, http_get, month_days  # noqa: E402

CACHE = WORK / "field"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def months(a, b):
    y, m = map(int, a.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def shift(mid, k):
    y, m = map(int, mid.split("-"))
    t = y * 12 + (m - 1) + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def _load(path):
    return json.loads(gzip.decompress(path.read_bytes())) if path.exists() else None


def _save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()))
    tmp.replace(path)


# ---------------------------------------------------------------- arXiv monthly listings
def arxiv_month(mid, force=False, complete=True):
    """-> [{id, t, a, c}] for papers first submitted in month `mid` (YYYY-MM) in our categories."""
    path = CACHE / "arxiv" / f"{mid}.json.gz"
    if not force and path.exists():
        return _load(path)
    from fetch_papers import parse_entries  # lazy: pulls in BeautifulSoup
    prefix = mid[2:4] + mid[5:7] + "."
    papers = {}
    for cat in config("sources")["arxiv_categories"]:
        skip, total = 0, None
        while total is None or skip < total:
            page = http_get(f"https://arxiv.org/list/{cat}/{mid}?skip={skip}&show=2000", timeout=120)
            m = re.search(r"Total of (\d+) entries", page)
            total = int(m.group(1)) if m else 0
            got = parse_entries(page, None)
            for pid, p in got.items():
                if pid.startswith(prefix) and pid not in papers:
                    papers[pid] = {"id": pid, "t": p["title"], "a": p["authors"], "c": p["subjects"]}
            if not got:
                break
            skip += 2000
            time.sleep(1)
        log(f"  arXiv {mid} {cat}: total {total} (union {len(papers)})")
    out = sorted(papers.values(), key=lambda p: p["id"])
    if complete:
        _save(path, out)
    return out


# ---------------------------------------------------------------- Hugging Face Daily Papers (attention)
def hf_month(mid, force=False, complete=True):
    path = CACHE / "hf" / f"{mid}.json.gz"
    if not force and path.exists():
        return _load(path)
    first, last = month_days(mid)
    out, d = {}, first
    while d <= min(last, dt.date.today()):
        try:
            items = json.loads(http_get(f"https://huggingface.co/api/daily_papers?date={d.isoformat()}&limit=100", timeout=60))
        except Exception as e:
            log(f"  WARNING HF {d}: {e}")
            items = []
        for it in items:
            p = it.get("paper", {})
            pid = p.get("id", "")
            if not re.match(r"^\d{4}\.\d{4,5}$", pid):
                continue
            prev = out.get(pid)
            up = p.get("upvotes") or 0
            if prev is None or up > prev["up"]:
                out[pid] = {"id": pid, "t": " ".join((p.get("title") or "").split()),
                            "s": " ".join((p.get("summary") or "").split())[:1500], "up": up, "d": d.isoformat()}
        d += dt.timedelta(days=1)
        time.sleep(0.3)
    res = sorted(out.values(), key=lambda p: p["id"])
    log(f"  HF {mid}: {len(res)} papers")
    if complete:
        _save(path, res)
    return res


# ---------------------------------------------------------------- news headlines (industry)
def news_month(mid, force=False, complete=True):
    path = CACHE / "news" / f"{mid}.json.gz"
    if not force and path.exists():
        return _load(path)
    from fetch_news import canon, parse_feed
    src = config("sources")
    reputable = {p.lower() for p in src["reputable_publishers"]}
    first, last = month_days(mid)
    seen, out = set(), []
    start = first
    while start <= last:
        end = min(last, start + dt.timedelta(days=2))
        after, before = (start - dt.timedelta(days=1)).isoformat(), (end + dt.timedelta(days=1)).isoformat()
        for q in src["google_news_queries"]:
            qs = urllib.parse.quote(f"{q} after:{after} before:{before}")
            try:
                got = parse_feed(http_get(f"https://news.google.com/rss/search?q={qs}&hl=en-US&gl=US&ceid=US:en",
                                          timeout=40, retries=3))
            except Exception as e:
                log(f"  WARNING news {mid} {q} {start}: {e}")
                got = []
            for it in got:
                pub = (it.get("publisher") or "").strip()
                t = it.get("time")
                if pub.lower() not in reputable or t is None or not (first <= t.date() <= last):
                    continue
                title = re.sub(r"\s+-\s+[^-]+$", "", it["title"]).strip()
                key = (re.sub(r"\W+", " ", title.lower()).strip(), canon(pub))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"t": title, "p": canon(pub), "ts": t.isoformat()[:10]})
            time.sleep(1.0)
        start = end + dt.timedelta(days=1)
    out.sort(key=lambda h: h["ts"])
    log(f"  news {mid}: {len(out)} reputable headlines")
    if complete:
        _save(path, out)
    return out


SOURCES = {"arxiv": arxiv_month, "hf": hf_month, "news": news_month}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--only", default="arxiv,hf,news")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for mid in months(a.start, a.end):
        for name in a.only.split(","):
            try:
                n = len(SOURCES[name](mid, a.force))
                print(f"{mid} {name}: {n}", flush=True)
            except Exception as e:
                print(f"{mid} {name}: FAILED {e}", flush=True)


if __name__ == "__main__":
    main()
