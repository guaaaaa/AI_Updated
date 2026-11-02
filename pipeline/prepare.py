"""One-call start of the daily run: fetch news + papers, print both shortlists.

Runs fetch_news.py and fetch_papers.py (no LLM usage; ~2-3 min), prints any source WARNINGs,
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
    news, w1 = run("fetch_news.py", d)
    papers, w2 = run("fetch_papers.py", d)
    warns = w1 + w2
    print("SOURCE WARNINGS: " + ("none" if not warns else "\n  " + "\n  ".join(warns)))
    print("\n" + news.strip() + "\n\n" + "=" * 100 + "\n\n" + papers.strip())


if __name__ == "__main__":
    main()
