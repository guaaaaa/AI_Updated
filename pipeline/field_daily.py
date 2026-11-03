"""Daily field series (no LLM usage): for every arXiv announcement day, how many new papers in our categories
match each research direction (and each field = the union of its directions), plus Hugging Face upvotes. This is
the data behind the stock-style direction and field pages (1W ... 2Y ranges, smoothed over more days as the range
grows).

data/state/field_daily/YYYY-MM.json, one file per announcement month:
  {"month", "days": [...], "src": ["api" | "listing", ...], "lo": [...], "hi": [...], "n": [...],
   "dirs": {id: [...]}, "groups": {field: [...]}, "hf_up": [...], "hf_dirs": {id: [...]}, "hf_groups": {...}}
  n = new papers announced that day (our categories, deduplicated); lo/hi = the day's id range.

Two sources of announcement days:
  * history (--backfill): the monthly listings cached in work/field/arxiv/ hold every paper of an id month but no
    dates. arXiv ids are handed out in announcement batches, so each day is a contiguous id range. One arXiv API
    call per 250 sampled ids gives their v1 submission times; arXiv's schedule (14:00 ET cutoff) turns those into
    announcement days ("api"; holidays are not modelled, so a holiday's batch shows on its nominal day).
  * daily runs: fetch_papers.py hands over the pastweek listing, whose day headings are exact ("listing").
    update_from_listing() rewrites the last five announcement days and refreshes their Hugging Face upvotes.

Usage: python3 pipeline/field_daily.py --backfill [--from 2024-08 --to 2026-10]   (history; needs work/field caches)
       python3 pipeline/field_daily.py --update                                    (fetch pastweek + HF, like a run)
"""
import argparse
import bisect
import datetime as dt
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import field_data as FD  # noqa: E402
from common import ET, STATE, WORK, arxiv_announce_time, config, http_get, today_et  # noqa: E402

OUT = STATE / "field_daily"
SAMPLES = 1000          # sampled ids per id month for the history mapping
API_BATCH = 250
ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def directions():
    from field_stats import directions as D   # lazy: field_stats imports this module's neighbours
    return D()


def listing_date(submitted_utc):
    """arXiv listing (mailing) date of a v1 submission: the morning after its 20:00 ET announcement."""
    return (arxiv_announce_time(submitted_utc) + dt.timedelta(hours=4)).date()


# ---------------------------------------------------------------- state files
def _empty_day():
    return {"src": None, "lo": None, "hi": None, "n": 0, "dirs": Counter(), "groups": Counter(),
            "hf_up": 0, "hf_dirs": Counter(), "hf_groups": Counter()}


def load_month(m):
    """-> {date: day dict} for announcement month m (YYYY-MM)."""
    path = OUT / f"{m}.json"
    if not path.exists():
        return {}
    j = json.loads(path.read_text())
    out = {}
    for i, d in enumerate(j["days"]):
        out[dt.date.fromisoformat(d)] = {
            "src": j["src"][i], "lo": j["lo"][i], "hi": j["hi"][i], "n": j["n"][i],
            "dirs": Counter({k: v[i] for k, v in j["dirs"].items() if v[i]}),
            "groups": Counter({k: v[i] for k, v in j["groups"].items() if v[i]}),
            "hf_up": j["hf_up"][i],
            "hf_dirs": Counter({k: v[i] for k, v in j["hf_dirs"].items() if v[i]}),
            "hf_groups": Counter({k: v[i] for k, v in j.get("hf_groups", {}).items() if v[i]})}
    return out


def save_month(m, days):
    D = directions()
    ids, groups = [d["id"] for d in D], sorted({d["group"] for d in D})
    ds = sorted(days)
    col = lambda key, keys: {k: [days[d][key].get(k, 0) for d in ds] for k in keys}
    j = {"month": m, "days": [d.isoformat() for d in ds], "src": [days[d]["src"] for d in ds],
         "lo": [days[d]["lo"] for d in ds], "hi": [days[d]["hi"] for d in ds], "n": [days[d]["n"] for d in ds],
         "dirs": col("dirs", ids), "groups": col("groups", groups), "hf_up": [days[d]["hf_up"] for d in ds],
         "hf_dirs": col("hf_dirs", ids), "hf_groups": col("hf_groups", groups)}
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f".{m}.tmp"
    tmp.write_text(json.dumps(j, separators=(",", ":")))
    tmp.replace(OUT / f"{m}.json")


def load_all():
    out = {}
    for f in sorted(OUT.glob("*.json")) if OUT.exists() else []:
        out.update(load_month(f.stem))
    return out


def save_all(days):
    by = defaultdict(dict)
    for d, v in days.items():
        by[f"{d:%Y-%m}"][d] = v
    for m, v in by.items():
        save_month(m, v)


def count_papers(day, papers, D):
    """papers: [(id, title)] announced that day -> fills n, lo, hi, dirs, groups."""
    day["n"], day["dirs"], day["groups"] = len(papers), Counter(), Counter()
    day["lo"], day["hi"] = (min(p[0] for p in papers), max(p[0] for p in papers)) if papers else (None, None)
    for _, title in papers:
        hit = set()
        for d in D:
            if d["rx"].search(title):
                day["dirs"][d["id"]] += 1
                hit.add(d["group"])
        for g in hit:
            day["groups"][g] += 1


def count_hf(days, hf, D, only=None):
    """hf: [{id, t, up, d}] (Daily Papers). A paper's HF date maps to that announcement day, or the next one."""
    keys = sorted(days)
    targets = set(only) if only is not None else set(keys)
    for k in targets:
        days[k]["hf_up"], days[k]["hf_dirs"], days[k]["hf_groups"] = 0, Counter(), Counter()
    for p in hf:
        i = bisect.bisect_left(keys, dt.date.fromisoformat(p["d"]))
        if i >= len(keys) or keys[i] not in targets:
            continue
        day = days[keys[i]]
        day["hf_up"] += p["up"]
        hit = set()
        for d in D:
            if d["rx"].search(p["t"]):
                day["hf_dirs"][d["id"]] += p["up"]
                hit.add(d["group"])
        for g in hit:
            day["hf_groups"][g] += p["up"]


# ---------------------------------------------------------------- history: id -> announcement day
def api_times(ids):
    """{id: v1 submission time} from the arXiv API, API_BATCH ids per call."""
    got = {}
    for k in range(0, len(ids), API_BATCH):
        chunk = ids[k:k + API_BATCH]
        xml = http_get("https://export.arxiv.org/api/query?id_list=" + ",".join(chunk) + f"&max_results={len(chunk)}",
                       timeout=120)
        for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
            im = re.search(r"<id>https?://arxiv\.org/abs/(\d{4}\.\d{4,5})(?:v\d+)?</id>", e)
            pm = re.search(r"<published>(.*?)</published>", e)
            if im and pm:
                got[im.group(1)] = pm.group(1)
        time.sleep(3)   # arXiv API etiquette
    return got


def id_times(mid, ids, extra=()):
    """Submission times for ~SAMPLES evenly spaced ids of id month `mid` (+ `extra`), cached in work/field/ids/."""
    path = FD.CACHE / "ids" / f"{mid}.json"
    got = json.loads(path.read_text()) if path.exists() else {}
    step = max(1, len(ids) // SAMPLES)
    want = [i for i in dict.fromkeys(ids[::step] + ids[-1:] + list(extra)) if i not in got]
    if want:
        got.update(api_times(want))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(got))
    return got


def _month_floor(mid):
    """Earliest regular submission time in id month `mid`: the cutoff before the month's first processing cutoff."""
    d = dt.date(int(mid[:4]), int(mid[5:]), 1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return dt.datetime(d.year, d.month, d.day, 14, 0, tzinfo=ET)


def _classify(times, mid):
    """Within a batch, ids follow submission time, but each batch starts with papers that were held for moderation
    (older submission times, so their schedule day is too early). A sample is regular when its time is not earlier
    than the last regular one."""
    pts = sorted((i, dt.datetime.fromisoformat(t.replace("Z", "+00:00"))) for i, t in times.items())
    regular, last = [], _month_floor(mid)
    for _, t in pts:
        regular.append(t >= last)
        if t >= last:
            last = t
    return pts, regular


def day_mapper(mid, ids):
    """-> f(id) -> announcement (listing) date for papers of id month `mid`, monotone in id.

    Regular samples take their schedule day; held samples the day of the next regular sample. Checked against exact
    catchup listings for Sep-Oct 2026: 99% of papers on the right day outside holidays. Holidays are not modelled
    (a merged two-day batch is split across its nominal days), which leaves shares unchanged."""
    pts, regular = _classify(id_times(mid, sorted(ids)), mid)
    day, nxt = [None] * len(pts), None
    for k in range(len(pts) - 1, -1, -1):
        if regular[k]:
            nxt = listing_date(pts[k][1])
        day[k] = nxt or listing_date(pts[k][1])
    keys = [p[0] for p in pts]

    def f(pid):
        k = bisect.bisect_right(keys, pid) - 1
        if k < 0:
            return day[0]
        if k >= len(keys) - 1 or day[k] == day[k + 1]:
            return day[k]
        a, b, x = (int(i.split(".")[1]) for i in (keys[k], keys[k + 1], pid))
        return day[k] if x - a <= b - x else day[k + 1]
    return f


def backfill(start, end):
    D = directions()
    papers_by_day = defaultdict(list)
    # exact days where the catchup listings of all our categories are cached (recent backfills)
    exact, cats, per_date = {}, config("sources")["arxiv_categories"], defaultdict(set)
    for f in (WORK / "catchup").glob("*.json") if (WORK / "catchup").exists() else []:
        cat, d = f.stem.rsplit("_", 1)
        per_date[d].add(cat)
        for pid in json.loads(f.read_text()):
            d0 = dt.date.fromisoformat(d)
            exact[pid] = min(exact.get(pid, d0), d0)
    exact_days = {dt.date.fromisoformat(d) for d, c in per_date.items() if set(cats) <= c}
    mids = [m for m in FD.months(start, end) if (FD.CACHE / "arxiv" / f"{m}.json.gz").exists()]
    for mid in mids:
        papers = FD.arxiv_month(mid)
        f = day_mapper(mid, [p["id"] for p in papers])
        for p in papers:
            d, e = f(p["id"]), exact.get(p["id"])
            if e and e in exact_days and abs((e - d).days) <= 5:   # not an old paper cross-listed later
                d = e
            papers_by_day[d].append((p["id"], p["t"]))
        log(f"  {mid}: {len(papers)} papers mapped")
    days = {}
    for d, ps in papers_by_day.items():
        if d.weekday() >= 5:
            continue
        days[d] = _empty_day()
        days[d]["src"] = "listing" if d in exact_days else "api"
        count_papers(days[d], ps, D)
    # the first and last mapped days can be cut by the id-month edges: drop days far below their neighbours
    ks = sorted(days)
    for k in ks[:3] + ks[-3:]:
        near = [days[x]["n"] for x in ks if abs((x - k).days) <= 21 and x != k]
        if near and days[k]["n"] < 0.5 * statistics.median(near):
            log(f"  dropping partial day {k} ({days[k]['n']} papers)")
            del days[k]
    hf = []
    for mid in FD.months(start, FD.shift(end, 1)):
        if (FD.CACHE / "hf" / f"{mid}.json.gz").exists():
            hf += FD.hf_month(mid)
    count_hf(days, hf, D)
    merged = load_all()
    for d, v in days.items():   # exact days from daily runs win over the history mapping
        if merged.get(d, {}).get("src") != "listing":
            merged[d] = v
    save_all(merged)
    log(f"backfill: {len(days)} announcement days {min(days)} -> {max(days)} ({len(merged)} stored)")


# ---------------------------------------------------------------- daily runs: exact days from the pastweek listing
def hf_days(first, last):
    out = {}
    d = first
    while d <= last:
        try:
            items = json.loads(http_get(f"https://huggingface.co/api/daily_papers?date={d.isoformat()}&limit=100", timeout=60))
        except Exception as e:
            log(f"  WARNING field_daily HF {d}: {e}")
            items = []
        for it in items:
            p = it.get("paper", {})
            pid = p.get("id", "")
            if ID_RE.match(pid) and (pid not in out or (p.get("upvotes") or 0) > out[pid]["up"]):
                out[pid] = {"id": pid, "t": " ".join((p.get("title") or "").split()), "up": p.get("upvotes") or 0,
                            "d": d.isoformat()}
        d += dt.timedelta(days=1)
        time.sleep(0.3)
    return list(out.values())


def update_from_listing(listing):
    """listing: fetch_papers.listing_sweep() output {id: {title, announced, ...}} (union of our categories)."""
    D = directions()
    by_day = defaultdict(list)
    for pid, p in listing.items():
        if ID_RE.match(pid) and p.get("announced"):
            by_day[(dt.datetime.fromisoformat(p["announced"]) + dt.timedelta(hours=4)).date()].append((pid, p["title"]))
    if not by_day:
        return
    days = load_all()
    prev = [d for d in days if d < min(by_day)]
    prev_hi = days[max(prev)]["hi"] if prev else None
    recent_n = [days[d]["n"] for d in sorted(days)[-20:]]
    floor = 0.5 * statistics.median(recent_n) if recent_n else 0
    changed = []
    for d in sorted(by_day):
        ps = sorted(by_day[d], reverse=True)
        # the day's new papers are one dense id range; cross-lists of older papers sit far below it
        keep = [ps[0]]
        for p in ps[1:]:
            a, b = keep[-1][0], p[0]
            if a[:4] != b[:4] or int(a[5:]) - int(b[5:]) > 300:
                break
            keep.append(p)
        if prev_hi:
            keep = [p for p in keep if p[0] > prev_hi]
        if len(keep) < floor:
            log(f"  WARNING field_daily: {d} has only {len(keep)} papers (listing incomplete?); kept the old numbers")
            continue
        day = days.get(d) or _empty_day()
        day["src"] = "listing"
        count_papers(day, keep, D)
        days[d] = day
        prev_hi = day["hi"]
        changed.append(d)
    if not changed:
        return
    hf = hf_days(min(changed) - dt.timedelta(days=3), max(changed))
    count_hf(days, hf, D, only=changed)
    save_all({d: days[d] for d in days if f"{d:%Y-%m}" in {f"{c:%Y-%m}" for c in changed}})
    log(f"  field_daily: updated {len(changed)} announcement days {changed[0]} -> {changed[-1]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--from", dest="start", default="2024-08")
    ap.add_argument("--to", dest="end", default=None)
    a = ap.parse_args()
    if a.backfill:
        backfill(a.start, a.end or FD.shift(f"{today_et():%Y-%m}", -1))
    if a.update:
        from fetch_papers import listing_sweep
        update_from_listing(listing_sweep(config("sources")["arxiv_categories"]))


if __name__ == "__main__":
    main()
