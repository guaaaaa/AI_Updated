"""Validate -> rebuild index -> commit -> push to master -> wait for the GitHub Pages
deploy of that commit -> confirm the live site serves the new digest.

Usage: python pipeline/publish.py --date 2026-11-02 [--message "..."] [--no-push]
Exit code 0 only when the digest is verifiably live.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DAYS, ROOT, config  # noqa: E402


def sh(*cmd, check=True):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"FAILED: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def push(branch):
    for attempt in range(4):
        r = subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            return
        print(f"push failed (attempt {attempt + 1}): {r.stderr.strip()[:300]}")
        sh("git", "fetch", "origin", branch, check=False)
        sh("git", "rebase", f"origin/{branch}", check=False)
        time.sleep(2 ** (attempt + 1))
    raise SystemExit("FAILED: could not push")


def wait_pages_run(repo, sha, timeout=900):
    """Wait for GitHub's 'pages build and deployment' run for this commit."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = subprocess.run(["gh", "api", f"repos/{repo}/actions/runs?head_sha={sha}&per_page=10"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            runs = [x for x in json.loads(r.stdout).get("workflow_runs", []) if "pages" in x["name"].lower()]
            if runs and runs[0]["status"] == "completed":
                return runs[0]["conclusion"], runs[0]["html_url"]
        else:
            print(f"(gh api unavailable: {r.stderr.strip()[:120]}; relying on live-site check)")
            return None, None
        time.sleep(15)
    return "timeout", None


def wait_live(url, expect, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(f"{url}?cb={int(time.time())}", headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if json.loads(r.read().decode()).get("generated_at") == expect:
                    return True
        except Exception:
            pass
        time.sleep(15)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--message")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    site = config("site")
    py = sys.executable
    v = subprocess.run([py, "pipeline/validate.py", a.date], cwd=ROOT, capture_output=True, text=True)
    print(v.stdout)
    if v.returncode:
        raise SystemExit("FAILED: validation errors — fix them and re-run publish.py")
    print(sh(py, "pipeline/build_index.py"))
    if a.no_push:
        return
    sh("git", "add", "data")
    if sh("git", "status", "--porcelain", "data", check=False):
        sh("git", "commit", "-m", a.message or f"Digest {a.date}")
    push(site["branch"])
    sha = sh("git", "rev-parse", "HEAD")
    print(f"pushed {sha[:8]} to {site['branch']}; waiting for GitHub Pages deploy...")
    concl, run_url = wait_pages_run(site["repo"], sha)
    print(f"pages run: {concl} {run_url or ''}")
    if concl not in (None, "success"):
        raise SystemExit(f"FAILED: Pages deploy {concl}. Inspect: gh api repos/{site['repo']}/actions/runs?head_sha={sha}")
    expect = json.loads((DAYS / f"{a.date}.json").read_text())["generated_at"]
    live = f"{site['url']}data/days/{a.date}.json"
    if not wait_live(live, expect):
        raise SystemExit(f"FAILED: {live} does not serve the new digest after 15 min")
    print(f"LIVE ✓ {site['url']}#/day/{a.date}")


if __name__ == "__main__":
    main()
