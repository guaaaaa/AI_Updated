"""One-call start of the daily run: fetch news + papers, print both shortlists.

Runs fetch_news.py and fetch_papers.py (no LLM usage; ~2-3 min), prints any source WARNINGs,
plus fetch_jobs.py (the job board's daily snapshot) in parallel -- its problems are warnings only;
then the news candidates followed by the paper shortlist — so the run needs one tool call, not four.
Usage: python3 pipeline/prepare.py --date 2026-11-02
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(script, date):
    r = subprocess.run([sys.executable, str(ROOT / "pipeline" / script), "--date", date],
                       capture_output=True, text=True, cwd=ROOT)
    warns = [l for l in r.stderr.splitlines() if "WARNING" in l or "Traceback" in l or "Error" in l]
    if r.returncode:
        warns.append(f"{script} exited with code {r.returncode}: {r.stderr.strip().splitlines()[-1:] }")
    return r.stdout, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    d = ap.parse_args().date
    jobs = subprocess.Popen([sys.executable, str(ROOT / "pipeline" / "fetch_jobs.py"), "--date", d],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT)
    news, w1 = run("fetch_news.py", d)
    papers, w2 = run("fetch_papers.py", d)
    try:
        _, jerr = jobs.communicate(timeout=900)
        w3 = [f"jobs: {l.strip()}" for l in jerr.splitlines() if "WARNING" in l or "Traceback" in l or "Error" in l]
        if jobs.returncode:
            w3.append(f"fetch_jobs.py exited with code {jobs.returncode} (the job board keeps yesterday's data)")
    except subprocess.TimeoutExpired:
        jobs.kill()
        w3 = ["fetch_jobs.py timed out (the job board keeps yesterday's data)"]
    warns = w1 + w2 + w3
    print("SOURCE WARNINGS: " + ("none" if not warns else "\n  " + "\n  ".join(warns)))
    print("\n" + news.strip() + "\n\n" + "=" * 100 + "\n\n" + papers.strip())


if __name__ == "__main__":
    main()
