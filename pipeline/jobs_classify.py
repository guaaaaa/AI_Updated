"""Rules that turn a raw posting into job-board fields (no LLM usage): role (config/jobs.json), countries (US / CA),
seniority, salary (annual, in the posting's currency), years of experience asked, PhD mention, remote, equity."""
import functools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG  # noqa: E402


@functools.lru_cache(maxsize=1)
def roles():
    out = []
    for r in json.loads((CONFIG / "jobs.json").read_text())["roles"]:
        c = lambda ps: re.compile("|".join(f"(?:{p})" for p in ps), re.I) if ps else None
        out.append({**r, "rx": c(r["title"]), "ex": c(r.get("exclude")), "drx": c(r.get("dept"))})
    return out


def _norm(t):
    return " ".join(re.sub(r"[_/|()\[\],;:–—-]+", " ", t or "").split())


GENERIC = re.compile(r"^(member of (the )?technical staff|engineer|software engineer|researcher|mts)\b", re.I)


def classify_title(title, dept=""):
    """-> role id or None (not a role we track: sales, recruiting, legal, operations...)."""
    t = _norm(title)
    for r in roles():
        if r["rx"].search(t) and not (r["ex"] and r["ex"].search(t)):
            if GENERIC.match(t) and dept:   # a generic title: the team decides (research engineer vs software engineer)
                for r2 in roles():
                    if r2.get("drx") and r2["drx"].search(dept):
                        return r2["id"]
            return r["id"]
    return None


def roles_in_text(text, rs=None):
    """Every role mentioned anywhere in a free-text ad (Hacker News threads)."""
    t = _norm(text)
    return {r["id"] for r in (rs or roles()) if r["rx"].search(t) and not (r["ex"] and r["ex"].search(t))}


# ---------------------------------------------------------------- location
US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD "
             "TN TX UT VT VA WA WV WI WY DC").split()
US_RX = re.compile(r"\b(united states|u\.s\.a?\.?|usa|us[- ]remote|remote[- ,(]*(us|usa|united states)|new york|nyc|san francisco|bay area|seattle|boston|"
                   r"austin|los angeles|chicago|palo alto|mountain view|menlo park|redmond|denver|atlanta|washington,? d\.?c|miami|san jose|san diego|"
                   r"sunnyvale|santa clara|san mateo|redwood city|bellevue|kirkland|cupertino|fremont|foster city|emeryville|south san francisco|santa monica|culver city|hawthorne|el segundo|mclean|reston|herndon|huntsville|cambridge,? ma|pittsburgh|philadelphia|portland|salt lake|dallas|houston|raleigh|"
                   r"boulder|ann arbor|phoenix|minneapolis|detroit|nashville|columbus|baltimore|arlington|irvine|oakland|berkeley|brooklyn|"
                   r"california|texas|massachusetts|washington state|colorado|illinois|virginia|georgia|florida|michigan|pennsylvania|ohio|"
                   r"oregon|north carolina|new jersey|arizona|utah|minnesota|maryland|washington)\b", re.I)
US_CODE = re.compile(r"\b(US|USA)\b")
US_ABBR = re.compile(r"(?:,|\s-)\s*(" + "|".join(US_STATES) + r")\b")
CA_RX = re.compile(r"\b(canada|canadian|toronto|vancouver|montr[eé]al|ottawa|calgary|edmonton|waterloo|kitchener|qu[eé]bec|winnipeg|halifax|"
                   r"ontario|british columbia|alberta|manitoba|nova scotia|saskatchewan|new brunswick|mississauga|markham|burnaby|victoria,? bc)\b", re.I)
CA_ABBR = re.compile(r",\s*(ON|BC|QC|AB|MB|NS|SK|NB|NL|PE)\b")
NA_RX = re.compile(r"\b(north america|americas)\b", re.I)


def countries(locs):
    """locs: location strings; 'country:XX' marks an ISO country field (so 'CA' there is Canada, not California)."""
    out = set()
    for l in locs or []:
        if l.startswith("country:"):
            code = l[8:].strip().upper()
            out |= {"US"} if code in ("US", "USA", "UNITED STATES") else {"CA"} if code in ("CA", "CAN", "CANADA") else set()
            continue
        if CA_RX.search(l) or CA_ABBR.search(l):
            out.add("CA")
        if US_RX.search(l) or US_ABBR.search(l) or US_CODE.search(l):
            out.add("US")
        if NA_RX.search(l):
            out |= {"US", "CA"}
    return out


def north_america(text):
    t = (text or "")[:1500]
    return bool(US_RX.search(t) or US_ABBR.search(t) or CA_RX.search(t) or re.search(r"\bremote\b", t, re.I) and not re.search(
        r"\b(europe|eu only|uk only|india|emea|apac|germany|berlin|london)\b", t, re.I))


# ---------------------------------------------------------------- seniority, requirements, pay
INTERN = re.compile(r"\b(intern(ship)?|co-?op|summer (associate|analyst|student)|student researcher|working student)\b", re.I)
JUNIOR = re.compile(r"\b(new grad\w*|graduate|entry[- ]level|junior|jr\.?|early[- ]career|university grad|apprentice|resident|residency|"
                    r"(engineer|scientist|developer|analyst) (i|1)$|associate(?! (director|principal|partner|general counsel|vice)))\b", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp|vice president|chief|distinguished|fellow|architect|"
                    r"(engineer|scientist|developer) (iii|iv|v|3|4|5))\b", re.I)


def seniority(title):
    t = _norm(title)
    return "intern" if INTERN.search(t) else "junior" if JUNIOR.search(t) else "senior" if SENIOR.search(t) else "mid"


YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b(?:\s+of)?(?:\s+\w+){0,3}?\s+(?:experience|exp\b)", re.I)
PHD = re.compile(r"\bph\.?\s?d\.?\b|\bdoctorate\b|\bdoctoral degree\b", re.I)
EQUITY = re.compile(r"\b(equity|stock options?|rsus?|restricted stock|ownership stake)\b", re.I)
REMOTE = re.compile(r"\bremote\b", re.I)
MONEY = r"(?:(US|USD|CA|CAD|C)\s?)?\$\s?(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*(k|K)?"
PAY = re.compile(MONEY + r"\s*(?:USD|CAD)?\s*(?:-|–|—|to)\s*" + MONEY + r"\s*(USD|CAD)?\s*(?:per |/ ?|an? )?(hour|hr|year|yr|annum|annually)?", re.I)


def years_required(text):
    ys = [int(m.group(1)) for m in YEARS.finditer(text or "") if 0 < int(m.group(1)) <= 20]
    return ys[0] if ys else None   # the first requirement stated is the headline one


def _amount(num, k):
    v = float(num.replace(",", "")) if num.count(",") or num.count(".") != 1 or len(num.split(".")[-1]) != 3 else float(num.replace(".", ""))
    return v * 1000 if k else v


def pay_from_text(text, ctry):
    """First '$X - $Y' range in a description -> [min, max, currency, 'year'] (hourly rates annualized at 2080 h)."""
    for m in PAY.finditer(text or ""):
        lo, hi = _amount(m.group(2), m.group(3)), _amount(m.group(5), m.group(6))
        unit = (m.group(8) or "").lower()
        hourly = unit in ("hour", "hr") or (hi < 400 and not m.group(3))
        if hourly:
            lo, hi = lo * 2080, hi * 2080
        if not (15_000 <= lo <= hi <= 2_000_000):
            continue
        tags = " ".join(filter(None, [m.group(1), m.group(4), m.group(7)])).upper()
        cur = "CAD" if re.search(r"\bCA|CAD|\bC\b", tags) else "USD" if re.search(r"US", tags) else ("CAD" if ctry == {"CA"} else "USD")
        return [round(lo), round(hi), cur, "year"]
    return None


def annual(pay):
    """Normalize an ATS pay field [min, max, currency, interval] to annual figures."""
    if not pay:
        return None
    lo, hi, cur, iv = pay
    try:
        lo, hi = float(lo), float(hi or lo)
    except (TypeError, ValueError):
        return None
    iv = (iv or "").lower()
    mult = 2080 if "hour" in iv else 12 if "month" in iv else 52 if "week" in iv else 1
    lo, hi = lo * mult, hi * mult
    if not (15_000 <= lo <= hi <= 2_000_000):
        return None
    return [round(lo), round(hi), (cur or "USD").upper()[:3], "year"]


def describe(post, emp_sector=""):
    """Raw ATS posting -> board fields, or None when it is not a tracked role in the US or Canada."""
    role = classify_title(post["title"], post.get("dept") or "")
    if not role:
        return None
    ctry = countries(post.get("locs"))
    if not ctry:
        return None
    text = post.get("text") or ""
    pay = annual(post.get("pay")) or pay_from_text(text, ctry)
    remote = post.get("remote")
    if remote is None:
        remote = any(REMOTE.search(l) for l in post.get("locs") or [])
    return {"role": role, "ctry": "|".join(sorted(ctry)), "level": seniority(post["title"]), "remote": int(bool(remote)),
            "yrs": years_required(text), "phd": int(bool(PHD.search(text))) if text else None,
            "equity": int(bool(EQUITY.search(text))) if text else None, "pay": pay}
