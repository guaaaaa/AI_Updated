"""Stage 1 of news selection (no LLM): pull headlines from primary-source feeds,
reputable press (via Google News RSS search) and Hacker News, keep those inside the
72h window, dedupe, and print one compact chronological list (~4k tokens). Claude does
the story grouping; breadth of independent coverage is the main cheap importance signal.

Usage: python pipeline/fetch_news.py --date 2026-11-02
Writes work/news_<date>.json and work/news_<date>.md (what Claude reads).
"""
import argparse
import datetime as dt
import email.utils
import html
import json
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET_XML
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (UTC, WORK, config, http_get, news_window, parse_date,  # noqa: E402
                    recent_digests, today_et)

ATOM = "{http://www.w3.org/2005/Atom}"
STOP = set("the a an and or of to in on for with by at from as is are be its it this that new how why what who will can "
           "after over into than about says say said report reports launches launch unveils announces".split())
GENERAL_FEEDS = {"Bloomberg Technology", "NVIDIA Blog", "SemiAnalysis"}  # need AI-keyword filtering


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def parse_time(s):
    if not s:
        return None
    s = s.strip()
    try:
        t = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def strip_html(x):
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(x or "")).split())


def parse_feed(xml_text):
    """RSS 2.0 or Atom -> [{title, url, time, publisher, desc}]"""
    xml_text = re.sub(r"^[^<]+", "", xml_text)
    root = ET_XML.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        src = it.find("source")
        items.append({"title": (it.findtext("title") or "").strip(), "url": (it.findtext("link") or "").strip(),
                      "time": parse_time(it.findtext("pubDate")),
                      "publisher": src.text.strip() if src is not None and src.text else None,
                      "desc": strip_html(it.findtext("description"))[:600]})
    for e in root.iter(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        items.append({"title": " ".join((e.findtext(f"{ATOM}title") or "").split()),
                      "url": link.get("href") if link is not None else "",
                      "time": parse_time(e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated")),
                      "publisher": None,
                      "desc": strip_html(e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content"))[:600]})
    return items


def ai_related(title, kws):
    t = title.lower()
    return any(re.search(r"(^|[^a-z])" + re.escape(k) + r"([^a-z]|$)", t) for k in kws)


CANON = {"blog.google": "Google", "Google AI Blog": "Google", "Google Research": "Google", "Google DeepMind": "Google",
         "Bloomberg.com": "Bloomberg", "Bloomberg Technology": "Bloomberg", "WIRED": "Wired", "Wired AI": "Wired",
         "WSJ": "The Wall Street Journal", "AP News": "Associated Press", "NVIDIA Blog": "NVIDIA",
         "Ars Technica AI": "Ars Technica", "TechCrunch AI": "TechCrunch", "The Verge AI": "The Verge",
         "MIT Technology Review AI": "MIT Technology Review", "Financial Times AI": "Financial Times"}


def canon(pub):
    return CANON.get(pub, pub)


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-\.]+", title.lower()) if w not in STOP and len(w) > 2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today_et().isoformat())
    a = ap.parse_args()
    d = parse_date(a.date)
    start, end = news_window(d)
    src = config("sources")
    kws = src["hn_ai_keywords"]
    reputable = {p.lower() for p in src["reputable_publishers"]}
    log(f"News window: {start:%a %b %d %H:%M} -> {end:%a %b %d %H:%M} ET")
    inwin = lambda t: t is not None and start <= t <= end
    items = []

    # 1) primary-source + press feeds
    for f in src["news_feeds"]:
        try:
            got = parse_feed(http_get(f["url"], timeout=40, retries=2))
        except Exception as e:
            log(f"  WARNING feed {f['name']} failed: {e}")
            continue
        n = 0
        for it in got:
            if not inwin(it["time"]):
                continue
            if f["name"] in GENERAL_FEEDS and not ai_related(it["title"], kws):
                continue
            items.append({**it, "publisher": f["name"], "tier": f["tier"], "via": "feed"})
            n += 1
        log(f"  feed {f['name']}: {n} in window")

    # 2) Google News search (reputable publishers only)
    after = (start.date() - dt.timedelta(days=1)).isoformat()
    before = (end.date() + dt.timedelta(days=1)).isoformat()
    for q in src["google_news_queries"]:
        qs = urllib.parse.quote(f"{q} after:{after} before:{before}")
        url = f"https://news.google.com/rss/search?q={qs}&hl=en-US&gl=US&ceid=US:en"
        try:
            got = parse_feed(http_get(url, timeout=40, retries=2))
        except Exception as e:
            log(f"  WARNING google news '{q}' failed: {e}")
            continue
        n = 0
        for it in got:
            pub = (it.get("publisher") or "").strip()
            if not inwin(it["time"]) or pub.lower() not in reputable:
                continue
            title = re.sub(r"\s+-\s+[^-]+$", "", it["title"])
            items.append({**it, "title": title, "publisher": pub, "tier": "press", "via": f"google:{q}", "desc": ""})
            n += 1
        log(f"  google news '{q}': {n} reputable in window")
        time.sleep(1)

    # 3) Hacker News
    hn = []
    try:
        url = ("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=300&numericFilters="
               f"created_at_i>{int(start.timestamp())},created_at_i<{int(end.timestamp())},points>60")
        for h in json.loads(http_get(url, timeout=40))["hits"]:
            if ai_related(h.get("title", ""), kws):
                hn.append({"title": h["title"], "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                           "time": dt.datetime.fromtimestamp(h.get("created_at_i", 0), UTC).isoformat(),
                           "points": h.get("points", 0), "comments": h.get("num_comments", 0),
                           "hn": f"https://news.ycombinator.com/item?id={h['objectID']}"})
        hn.sort(key=lambda x: -x["points"])
        log(f"  hacker news: {len(hn)} AI stories with >60 points")
    except Exception as e:
        log(f"  WARNING hacker news failed: {e}")

    # dedupe identical headlines (same title from the same outlet); Claude groups stories itself
    uniq = {}
    for it in sorted(items, key=lambda x: x["time"]):
        it["publisher"] = canon(it["publisher"])
        uniq.setdefault((re.sub(r"\W+", " ", it["title"].lower()).strip(), it["publisher"]), it)
    heads = list(uniq.values())

    recent_titles = [(j["date"], n["title"], n["story_key"]) for j in recent_digests(d) for n in j.get("news", [])]

    WORK.mkdir(exist_ok=True)
    dump = {"date": d.isoformat(), "window": [start.isoformat(), end.isoformat()], "hn": hn[:40],
            "headlines": [{**i, "time": i["time"].isoformat()} for i in heads]}
    (WORK / f"news_{d}.json").write_text(json.dumps(dump, indent=1))

    tz = end.tzinfo
    L = [f"# News candidates for {d}", f"Window: {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} ET",
         f"{len(heads)} headlines from primary sources and reputable outlets. Group them into stories yourself; "
         "breadth of independent coverage is a strong (not decisive) importance signal.", ""]
    if recent_titles:
        L.append("## Already covered in the last 7 days (do not repeat unless materially new)")
        L += [f"- {dd}: {t} [story_key={k}]" for dd, t, k in recent_titles]
        L.append("")
    L.append("## A. Primary-source posts (official blogs; many are minor customer stories)")
    def when(t):  # feeds with date-only stamps show as 00:00 UTC: flag them as approximate
        u = t.astimezone(UTC)
        return f"{u:%a %b %d} (date only — verify time)" if (u.hour, u.minute, u.second) == (0, 0, 0) else f"{t.astimezone(tz):%a %H:%M}"

    for it in heads:
        if it["tier"] == "primary":
            desc = " ".join(it.get("desc", "").split()[:20])
            L.append(f"- {when(it['time'])} | {it['publisher']}: {it['title']}  <{it['url']}>"
                     + (f"\n    {desc}…" if desc else ""))
    L += ["", "## B. Press & newsletter headlines (chronological; Google News links omitted, search by headline)"]
    press = [it for it in heads if it["tier"] != "primary"][-140:]  # newest 140 headlines max
    for it in press:
        if True:
            u = "" if "news.google.com" in it["url"] else f"  <{it['url']}>"
            L.append(f"- {when(it['time'])} | {it['publisher']}: {it['title']}{u}")
    L += ["", "## C. Hacker News (AI, top by points)"]
    L += [f"- {dt.datetime.fromisoformat(h['time']).astimezone(tz):%a %H:%M} | {h['points']} pts / {h['comments']} comments: "
          f"{h['title']}  <{h['url']}>" for h in hn[:10]]
    md = "\n".join(L)
    (WORK / f"news_{d}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
