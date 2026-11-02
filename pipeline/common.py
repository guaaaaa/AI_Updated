"""Shared helpers: paths, time windows, HTTP, digest history."""
import datetime as dt
import gzip
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
DAYS = DATA / "days"
STATE = DATA / "state"
WORK = ROOT / "work"  # scratch output, git-ignored

ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
UA = "ai-updated-digest/0.1 (+https://guaaaaa.github.io/AI_Updated/)"

RUN_HOUR, RUN_MINUTE = 7, 30  # nominal digest time (ET); window end
WEEKDAY_WINDOW_H = 72
WEEKEND_PAPER_WINDOW_H = 168
NEWS_WINDOW_H = 72
DEDUP_LOOKBACK_DAYS = 7


def ensure_bs4():
    """Fresh cloud sessions may lack BeautifulSoup: install it on first use."""
    try:
        import bs4  # noqa: F401
    except ImportError:
        import subprocess
        import sys
        for cmd in ([sys.executable, "-m", "pip", "install", "-q", "beautifulsoup4"],
                    [sys.executable, "-m", "pip", "install", "-q", "--user", "--break-system-packages", "beautifulsoup4"]):
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                break
        import importlib
        import site
        importlib.invalidate_caches()
        if hasattr(site, "getusersitepackages") and site.getusersitepackages() not in sys.path:
            sys.path.append(site.getusersitepackages())
    from bs4 import BeautifulSoup
    return BeautifulSoup


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def config(name):
    return load_json(CONFIG / f"{name}.json")


def parse_date(s):
    return dt.date.fromisoformat(s)


def today_et():
    return dt.datetime.now(ET).date()


def is_weekend(d):
    return d.weekday() >= 5


def edition(d):
    """Mon-Fri 'weekday' (72h papers); Saturday 'weekend' (best of the week, 7-day papers).
    Sundays carry no digest (weekly-summary day); the one legacy Sunday digest keeps 'weekend'."""
    return "weekend" if is_weekend(d) else "weekday"


LEGACY_SUNDAY_DIGESTS = {"2026-11-01"}  # published before Sundays became weekly-summary days


def is_digest_day(d):
    return d.weekday() != 6 or d.isoformat() in LEGACY_SUNDAY_DIGESTS


# ---------------------------------------------------------------- weeks and months (summaries)
SUMMARIES = DATA / "summaries"


def week_id(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_days(wid):
    """'2026-W44' -> (monday, saturday, sunday). Digests Mon-Sat; the summary is published Sunday."""
    y, w = wid.split("-W")
    mon = dt.date.fromisocalendar(int(y), int(w), 1)
    return mon, mon + dt.timedelta(days=5), mon + dt.timedelta(days=6)


def month_days(mid):
    """'2026-10' -> (first, last) day of that month."""
    y, m = map(int, mid.split("-"))
    first = dt.date(y, m, 1)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - dt.timedelta(days=1)


def snapshot_update(d, key, value):
    """Persist part of a day's broader evidence (shortlist, headline pool) for weekly/monthly summaries."""
    path = STATE / "daily" / f"{d.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    j = load_json(path, {}) or {}
    j["date"], j[key] = d.isoformat(), value
    path.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def window_end(d):
    return dt.datetime(d.year, d.month, d.day, RUN_HOUR, RUN_MINUTE, tzinfo=ET)


def paper_window(d):
    hours = WEEKEND_PAPER_WINDOW_H if is_weekend(d) else WEEKDAY_WINDOW_H
    end = window_end(d)
    return end - dt.timedelta(hours=hours), end


def news_window(d):
    end = window_end(d)
    return end - dt.timedelta(hours=NEWS_WINDOW_H), end


def arxiv_announce_time(submitted_utc):
    """When a v1 submission first became public on arXiv (ET), per arXiv's schedule.

    Cutoff 14:00 ET; announcements 20:00 ET Sun-Thu. Thu 14:00-Fri 14:00 -> Sunday;
    Fri 14:00-Mon 14:00 -> Monday. Holidays are ignored (rare, small error).
    """
    t = submitted_utc.astimezone(ET)
    wd, before_cutoff = t.weekday(), t.hour < 14
    day = t.date()
    if wd in (0, 1, 2, 3):  # Mon-Thu
        if before_cutoff:
            target = day
        elif wd == 3:  # Thu after cutoff -> Sunday
            target = day + dt.timedelta(days=3)
        else:
            target = day + dt.timedelta(days=1)
    elif wd == 4:  # Fri
        target = day + dt.timedelta(days=2 if before_cutoff else 3)
    else:  # Sat/Sun -> Monday
        target = day + dt.timedelta(days=7 - wd)
    return dt.datetime(target.year, target.month, target.day, 20, 0, tzinfo=ET)


def earliest_submission_for(start):
    """Earliest v1 submission time whose announcement is >= start (hour resolution)."""
    t = start - dt.timedelta(days=4)
    while arxiv_announce_time(t) < start and t < start:
        t += dt.timedelta(hours=1)
    return t - dt.timedelta(hours=1)


def http_get(url, headers=None, timeout=60, retries=5, backoff=4, data=None):
    h = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    h.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            code = getattr(e, "code", None)
            if code in (400, 401, 403, 404, 410):
                break
            if code in (429, 503):  # rate limited: honour Retry-After, else back off hard
                ra = e.headers.get("Retry-After") if getattr(e, "headers", None) else None
                wait = int(ra) if ra and ra.isdigit() else 20 * (attempt + 1)
                time.sleep(min(wait, 120))
            else:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def recent_digests(d, lookback=DEDUP_LOOKBACK_DAYS):
    """Digests published in the `lookback` days before date d (exclusive)."""
    out = []
    for i in range(1, lookback + 1):
        day = d - dt.timedelta(days=i)
        j = load_json(DAYS / f"{day.isoformat()}.json")
        if j:
            out.append(j)
    return out


def featured_ids(d, lookback=DEDUP_LOOKBACK_DAYS):
    papers, stories = set(), set()
    for j in recent_digests(d, lookback):
        papers.update(p["id"] for p in j.get("papers", []))
        stories.update(n["story_key"] for n in j.get("news", []))
    return papers, stories


def word_count(text):
    return len(text.split())
