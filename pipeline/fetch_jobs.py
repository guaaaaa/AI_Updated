"""Daily job snapshot (no LLM usage): every tracked employer's public job board (config/employers.json) ->
open-postings registry + one line of daily role metrics for the job board.

State (committed, so a fresh run can diff against yesterday):
  data/state/jobs/open.tsv          open US/Canada postings in tracked roles: key, company, role, title, ctry, level,
                                    remote, yrs, phd, equity, cur, pmin, pmax, published, first_seen, url
  data/state/jobs/boards.json       per board: first day seen, last good day, open postings by role and in total
  data/state/jobs/daily/YYYY-MM.jsonl  one line per day: {date, boards_ok, roles: {role: {US|CA|NA: metrics}}}

A posting is "new" the first day we see it on a board we already tracked the day before (a newly added board is a
baseline, not new hiring); "closed" the day it disappears from a board that answered. A board that fails keeps its
postings and is left out of that day's chain ratio, so outages never look like hiring swings. chain = open postings
today / yesterday over boards that answered both days; the index is the running product of chains.

Usage: python3 pipeline/fetch_jobs.py [--date YYYY-MM-DD] [--workers 8]
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ats  # noqa: E402
import jobs_classify as JC  # noqa: E402
from common import CONFIG, STATE, today_et  # noqa: E402

OUT = STATE / "jobs"
COLS = ["key", "company", "role", "title", "ctry", "level", "remote", "yrs", "phd", "equity", "cur", "pmin", "pmax", "published", "first_seen", "url"]
CTRY = ("US", "CA", "NA")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_registry():
    path = OUT / "open.tsv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["key"]: r for r in csv.DictReader(f, delimiter="\t")}


def save_registry(reg):
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / ".open.tsv.tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS, delimiter="\t", extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for k in sorted(reg):
            w.writerow({c: ("" if reg[k].get(c) is None else str(reg[k][c]).replace("\t", " ")) for c in COLS})
    tmp.replace(OUT / "open.tsv")


def row_for(emp, p, desc, today, old=None):
    pay = desc["pay"] or [None, None, None]
    return {"key": f"{emp['ats']}:{emp['token']}:{p['id']}", "company": emp["name"], "role": desc["role"], "title": p["title"].strip()[:140],
            "ctry": desc["ctry"], "level": desc["level"], "remote": desc["remote"], "yrs": desc["yrs"], "phd": desc["phd"],
            "equity": desc["equity"], "cur": pay[2], "pmin": pay[0], "pmax": pay[1], "published": p.get("published") or (old or {}).get("published") or today,
            "first_seen": (old or {}).get("first_seen") or today, "url": (p.get("url") or "")[:300]}


def snapshot(day, workers=8):
    emps = json.loads((CONFIG / "employers.json").read_text())["employers"]
    reg = load_registry()
    bpath = OUT / "boards.json"
    boards = json.loads(bpath.read_text()) if bpath.exists() else {}
    today = day.isoformat()

    def fetch(emp):
        t = time.time()
        try:
            return emp, ats.fetch_board(emp), time.time() - t
        except Exception as e:
            return emp, e, time.time() - t

    results = []
    with cf.ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(fetch, emps))
    ok, failed = [r for r in results if not isinstance(r[1], Exception)], [r[0]["name"] for r in results if isinstance(r[1], Exception)]
    log(f"  jobs: {len(ok)}/{len(emps)} boards answered" + (f"; failed: {', '.join(failed[:12])}" if failed else ""))

    by_board = defaultdict(dict)
    for k, r in reg.items():
        by_board[k.rsplit(":", 1)[0]][k] = r
    new_keys, closed, need_detail, totals = set(), [], [], {}
    for emp, posts, _ in ok:
        bkey = f"{emp['ats']}:{emp['token']}"
        tracked_before = bkey in boards and boards[bkey].get("last_ok")
        seen, total_na = {}, 0
        for p in posts:
            key = f"{bkey}:{p['id']}"
            if JC.countries(p.get("locs")):
                total_na += 1
            old = reg.get(key)
            desc = JC.describe(p)
            if not desc:
                continue
            if old and not p.get("text"):   # Greenhouse listing: keep what the detail fetch parsed
                for f in ("yrs", "phd", "equity"):
                    desc[f] = old.get(f) or None
                if old.get("pmin"):
                    desc["pay"] = [old["pmin"], old["pmax"], old["cur"], "year"]
            seen[key] = row_for(emp, p, desc, today, old)
            if not old:
                if tracked_before:
                    new_keys.add(key)
                if emp["ats"] == "greenhouse":
                    need_detail.append((emp, p, key))
        for key, r in by_board.get(bkey, {}).items():
            if key not in seen:
                start = r.get("published") or r.get("first_seen") or today
                closed.append({**r, "days": max(0, (day - dt.date.fromisoformat(start[:10])).days)})
                reg.pop(key, None)
        reg.update(seen)
        totals[bkey] = total_na

    # Greenhouse descriptions and pay ranges for postings we have not parsed yet
    def detail(item):
        emp, p, key = item
        try:
            return key, p, ats.greenhouse_job(emp["token"], p["id"])
        except Exception:
            return key, p, None
    if need_detail:
        with cf.ThreadPoolExecutor(workers) as ex:
            for key, p, d in ex.map(detail, need_detail):
                if d and key in reg:
                    desc = JC.describe({**p, "text": d["text"], "pay": d["pay"]})
                    if desc:
                        r = reg[key]
                        pay = desc["pay"] or [None, None, None]
                        r.update({"yrs": desc["yrs"], "phd": desc["phd"], "equity": desc["equity"], "cur": pay[2], "pmin": pay[0], "pmax": pay[1]})
        log(f"  jobs: parsed {len(need_detail)} Greenhouse descriptions")

    # ---- daily metrics
    prev_counts = {k: v.get("open", {}) for k, v in boards.items()}
    ok_keys = {f"{e['ats']}:{e['token']}" for e, _, _ in ok}
    common = {k for k in ok_keys if boards.get(k, {}).get("last_ok")}
    cur_counts = defaultdict(Counter)
    for r in reg.values():
        b = r["key"].rsplit(":", 1)[0]
        for c in r["ctry"].split("|"):
            cur_counts[b][f"{r['role']}|{c}"] += 1
        cur_counts[b][f"{r['role']}|NA"] += 1
        for c in r["ctry"].split("|") + ["NA"]:
            cur_counts[b][f"_tracked|{c}"] += 1
    for b, n in totals.items():
        cur_counts[b]["_all|NA"] = n

    rows = defaultdict(list)
    for r in reg.values():
        for c in r["ctry"].split("|") + ["NA"]:
            rows[(r["role"], c)].append(r)
    closed_by = defaultdict(list)
    for r in closed:
        for c in r["ctry"].split("|") + ["NA"]:
            closed_by[(r["role"], c)].append(r)
    new_by = Counter()
    for k in new_keys:
        r = reg[k]
        for c in r["ctry"].split("|") + ["NA"]:
            new_by[(r["role"], c)] += 1

    def share(rs, f, val=lambda v: v == "1"):
        have = [r for r in rs if r.get(f) is not None and str(r.get(f)) != ""]   # 0 is a value, not missing
        return round(sum(1 for r in have if val(str(r[f]))) / len(have), 3) if have else None

    def med(xs):
        return round(statistics.median(xs), 1) if xs else None

    out_roles = {}
    role_ids = [r["id"] for r in JC.roles()] + ["_tracked", "_all"]
    for rid in role_ids:
        out_roles[rid] = {}
        for c in CTRY:
            prev = sum(prev_counts.get(b, {}).get(f"{rid}|{c}", 0) for b in common)
            now = sum(cur_counts[b].get(f"{rid}|{c}", 0) for b in common)
            m = {"open": sum(cur_counts[b].get(f"{rid}|{c}", 0) for b in cur_counts), "chain": round(now / prev, 5) if prev else None}
            if rid.startswith("_"):
                out_roles[rid][c] = m
                continue
            rs = rows.get((rid, c), [])
            cur = "CAD" if c == "CA" else "USD"
            mids = sorted((float(r["pmin"]) + float(r["pmax"])) / 2 for r in rs if r.get("pmin") and r.get("cur") == cur)
            ages = [(day - dt.date.fromisoformat(r["published"][:10])).days for r in rs if r.get("published")]
            comp = Counter(r["company"] for r in rs)
            cl = closed_by.get((rid, c), [])
            m.update({
                "new": new_by.get((rid, c), 0), "closed": len(cl), "closed_days": med([r["days"] for r in cl]),
                "companies": len(comp), "top3": round(sum(n for _, n in comp.most_common(3)) / len(rs), 3) if rs else None,
                "pay_n": len(mids), "pay_mid": round(statistics.median(mids)) if mids else None,
                "pay_p25": round(mids[len(mids) // 4]) if len(mids) >= 4 else None, "pay_p75": round(mids[(3 * len(mids)) // 4]) if len(mids) >= 4 else None,
                "junior": share(rs, "level", lambda v: v in ("intern", "junior")), "senior": share(rs, "level", lambda v: v == "senior"),
                "intern": share(rs, "level", lambda v: v == "intern"), "phd": share(rs, "phd"), "remote": share(rs, "remote"),
                "equity": share(rs, "equity"), "yrs": med([float(r["yrs"]) for r in rs if r.get("yrs")]), "age": med(ages)})
            out_roles[rid][c] = m

    for e, _, _ in ok:
        k = f"{e['ats']}:{e['token']}"
        boards.setdefault(k, {"name": e["name"], "first_day": today})
        boards[k].update({"last_ok": today, "open": dict(cur_counts[k])})
    OUT.mkdir(parents=True, exist_ok=True)
    save_registry(reg)
    bpath.write_text(json.dumps(boards, indent=0, sort_keys=True))
    line = {"date": today, "boards": len(emps), "boards_ok": len(ok), "baseline_boards": len(ok_keys - common), "roles": out_roles}
    dpath = OUT / "daily" / f"{today[:7]}.jsonl"
    dpath.parent.mkdir(parents=True, exist_ok=True)
    kept = [l for l in (dpath.read_text().splitlines() if dpath.exists() else []) if l and json.loads(l)["date"] != today]
    dpath.write_text("\n".join(sorted(kept + [json.dumps(line, separators=(",", ":"))])) + "\n")
    t = out_roles["_tracked"]["NA"]
    log(f"  jobs: {t['open']} open tracked postings (US/CA), {len(new_keys)} new, {len(closed)} closed; chain {t['chain']}")
    return line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=today_et().isoformat())
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    day = dt.date.fromisoformat(a.date)
    snapshot(day, a.workers)
    if day.weekday() == 0 or day.day <= 3:   # history: Hacker News threads (monthly) and Indeed (refreshed weekly)
        import jobs_history
        for step in (jobs_history.hn_update, jobs_history.indeed):
            try:
                step()
            except Exception as e:
                log(f"  WARNING jobs history {step.__name__} failed: {e}")


if __name__ == "__main__":
    main()
