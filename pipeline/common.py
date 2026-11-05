"""Shared helpers: paths, time windows, HTTP, digest history.

Domains (config/domains.json): every script works on one domain, chosen with --domain <id> (any script; removed from
sys.argv here) or the AIU_DOMAIN environment variable, default "ai". The choice is exported so child scripts inherit
it. AI keeps the original layout (data/days, data/state, config/*.json, work/); another domain lives in data/<id>/,
config/domains/<id>/ and work/<id>/. data/state/ (field model, jobs) is shared.
"""
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
STATE = DATA / "state"          # shared state: field model, jobs (and AI's per-day snapshots)


def _argv_domain():
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--domain" and i + 1 < len(sys.argv):
            v = sys.argv[i + 1]
            del sys.argv[i:i + 2]
            return v
        if a.startswith("--domain="):
            del sys.argv[i]
            return a.split("=", 1)[1]
    return None


DOMAINS = json.loads((CONFIG / "domains.json").read_text(encoding="utf-8"))["domains"]
DOMAIN = _argv_domain() or os.environ.get("AIU_DOMAIN") or "ai"
if DOMAIN not in {d["id"] for d in DOMAINS}:
    raise SystemExit(f"unknown domain {DOMAIN!r}; see config/domains.json")
os.environ["AIU_DOMAIN"] = DOMAIN
DOM = next(d for d in DOMAINS if d["id"] == DOMAIN)


def domain_paths(did):
    if did == "ai":
        return {"data": DATA, "days": DATA / "days", "summaries": DATA / "summaries", "state": STATE,
                "work": ROOT / "work", "config": CONFIG}
    base = DATA / did
    return {"data": base, "days": base / "days", "summaries": base / "summaries", "state": base / "state",
            "work": ROOT / "work" / did, "config": CONFIG / "domains" / did}


_P = domain_paths(DOMAIN)
DDATA, DAYS, DSTATE, WORK, DCONFIG = _P["data"], _P["days"], _P["state"], _P["work"], _P["config"]   # WORK is git-ignored

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


DOMAIN_CONFIGS = ("sources", "taxonomy", "notable")   # per domain; everything else in config/ is shared


def config(name):
    if DOMAIN != "ai" and name in DOMAIN_CONFIGS:
        return load_json(DCONFIG / f"{name}.json", {} if name == "notable" else None)
    return load_json(CONFIG / f"{name}.json")


def parse_date(s):
    return dt.date.fromisoformat(s)


def today_et():
    return dt.datetime.now(ET).date()


def is_weekend(d):
    return d.weekday() >= 5


def edition(d):
    """Mon-Fri 'weekday' (72h papers); Saturday 'weekend' (best of the week, 7-day papers).
    Sundays carry no digest (the automatic Week in review covers the week); the one legacy Sunday digest keeps 'weekend'."""
    return "weekend" if is_weekend(d) else "weekday"


LEGACY_SUNDAY_DIGESTS = {"2026-11-01"}  # published before Sundays became weekly-summary days


def is_digest_day(d):
    return d.weekday() != 6 or d.isoformat() in LEGACY_SUNDAY_DIGESTS


# ---------------------------------------------------------------- weeks and months (summaries)
SUMMARIES = _P["summaries"]


def week_id(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_days(wid):
    """'2026-W44' -> (monday, saturday, sunday). Digests run Mon-Sat; the Week in review covers them."""
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
    path = DSTATE / "daily" / f"{d.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    j = load_json(path, {}) or {}
    j["date"], j[key] = d.isoformat(), value
    path.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def window_end(d):
    return dt.datetime(d.year, d.month, d.day, RUN_HOUR, RUN_MINUTE, tzinfo=ET)


def paper_window(d):
    hours = DOM.get("paper_window_h") or (WEEKEND_PAPER_WINDOW_H if is_weekend(d) else WEEKDAY_WINDOW_H)
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


def other_tabs(d, lookback=3):
    """News and papers the other domains published from `lookback` days before d up to d itself."""
    out = []
    for dm in DOMAINS:
        if dm["id"] == DOMAIN:
            continue
        days = domain_paths(dm["id"])["days"]
        for i in range(lookback + 1):
            j = load_json(days / f"{(d - dt.timedelta(days=i)).isoformat()}.json")
            for n in (j or {}).get("news", []):
                out.append({"tab": dm["name"], "date": j["date"], "kind": "news", "title": n["title"], "key": n.get("story_key")})
            for x in (j or {}).get("papers", []):
                out.append({"tab": dm["name"], "date": j["date"], "kind": "paper", "title": x["title"], "key": x.get("id")})
    return out


# Subject routing for sources that cover every field (Nature, Science, PNAS, general science news): papers and
# headlines about living things go to the Biology tab, the rest to Science. Each item lands on exactly one side.
_NOT_LIFE = re.compile(r"\b(?:solar|fuel|battery|unit|electrochemical|photovoltaic|perovskite|memory|load)[ -]cells?\b|"
                       r"\bneural (?:networks?|nets?|operators?)\b|\bcell ?phones?\b|\bevolution of (?:the )?(?:universe|galax\w*|stars?)\b", re.I)
_LIFE = re.compile(r"\b(?:cells?|cellular|proteins?|proteom\w*|genes?|genetic\w*|genom\w*|dna|rna|mrna|crispr|enzym\w*|neuron\w*|"
                   r"neural|brains?|cortex|cortical|synap\w*|species|evolution\w*|ecolog\w*|ecosystems?|biodiversity|fossil\w*|"
                   r"dinosaur\w*|primates?|mammal\w*|birds?|insects?|fish|frogs?|plants?|crops?|bacteri\w*|microb\w*|virus\w*|viral|"
                   r"pathogen\w*|infect\w*|immun\w*|antibod\w*|tumou?rs?|cancers?|patients?|clinical|diseases?|mice|mouse|murine|"
                   r"rats?|zebrafish|drosophila|yeast|organoids?|embryo\w*|stem cells?|tissues?|metabol\w*|hormon\w*|microbiome\w*|"
                   r"receptors?|antibiotic\w*|vaccin\w*|therap\w*|drugs?|hominins?|neanderthals?|animals?|organisms?|biolog\w*|"
                   r"biomolec\w*|biomedic\w*|chromosom\w*|epigen\w*|transcription\w*|peptides?|pregnan\w*|sperm|placenta\w*|"
                   r"obesity|diabet\w*|alzheimer\w*|dementia|heart|blood|liver|kidneys?|lungs?|gut|photosynth\w*|corals?|whales?|"
                   r"bees?|ants|bats?|mosquito\w*|parasit\w*|fung\w*|algae|algal|medic\w*|health\w*|\w*cellular|\w+proteins?|glyco\w*|cytoplasm\w*|epitheli\w*|muscles?|myo\w+|tendons?|bones?|skeletal|teeth|tooth|dental|cerebell\w*|neuro\w+|gestation\w*|preterm|births?|organogenesis|urogenital|(?:multi|bi)?allel\w*|incompatib\w*|lysine|inflamm\w*|pyroptosis|allosteric|kinases?|reductases?|polymerases?|synthases?|proteases?|ligases?|oxidases?|phyto\w*|epidem\w*|cholera|malaria|tubercul\w*|covid\w*|sars|gwas|natural selection|carotid|arter\w*|cardi\w*|vascular|electroenceph\w*|eeg|biomarkers?|breastfe\w*|roots|root growth|leaf|leaves|nutrition\w*|antigen\w*|t cells?|leukemia|lymph\w*|pollinat\w*|taxa|fauna|flora|wildlife|conservation biology)\b", re.I)
_PHYS = re.compile(r"\b(?:quantum|qubits?|photon\w*|lasers?|galax\w*|stars?|stellar|planet\w*|exoplanet\w*|black holes?|cosmic|"
                   r"cosmolog\w*|universe|supernova\w*|telescopes?|particles?|neutrinos?|superconduct\w*|magnet\w*|electrons?|"
                   r"electronic|semiconduct\w*|crystal\w*|lattices?|topolog\w*|cataly\w*|polymers?|batter(?:y|ies)|solar|"
                   r"perovskites?|alloys?|graphene|climate|oceans?|ocean\w+|atmospher\w*|earthquakes?|seismic|volcan\w*|glacier\w*|"
                   r"ice sheets?|sea ice|sea level|carbon dioxide|co2|aerosols?|weather|monsoons?|sediment\w*|minerals?|mantle|"
                   r"tecton\w*|plasmas?|nuclear fusion|fusion (?:energy|power|reactors?)|nuclear|photovolta\w*|thermodynam\w*|fluids?|turbulen\w*|optic\w*|metamaterials?|mathemat\w*|"
                   r"theorems?|phonons?|atoms?|atomic|gravit\w*|dark matter|dark energy|asteroids?|comets?|moons?|lunar|mars|"
                   r"jupiter|saturn|spacecraft|satellites?|orbit\w*|hydrogen|metals?|metallic|oxides?|electrolytes?|wildfires?|"
                   r"droughts?|floods?|hurricanes?|cyclones?|permafrost|rainfall|physic\w*|chemi\w*|molecules?|materials?)\b", re.I)


def life_science(text):
    """True when a title (+ abstract) is mainly about living things."""
    t = _NOT_LIFE.sub(" ", text or "")
    life, phys = len(_LIFE.findall(t)), len(_PHYS.findall(t))
    return life >= max(1, phys)   # ties go to Biology: an organism studied in a physical setting is still biology


def subject_ok(text, subject):
    """subject: "life" keeps life-science items, "nonlife" drops them, anything else keeps all."""
    if subject == "life":
        return life_science(text)
    if subject == "nonlife":
        return not life_science(text)
    return True


def word_count(text):
    return len(text.split())
