"""Validate -> rebuild index -> commit -> push to master -> wait for the GitHub Pages
deploy of that commit -> confirm the live site serves the new digest or summary.

Usage: python pipeline/publish.py --date 2026-11-02 [--message "..."] [--no-push]
       python pipeline/publish.py --summary weekly/2026-W45      (or monthly/2026-11)
Exit code 0 only when the content is verifiably live. Two jobs publishing the same morning is fine:
a push conflict on the generated files (data/index.json, data/trends.json, data/weeks/) is resolved by regenerating them.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DAYS, ROOT, SUMMARIES, config  # noqa: E402

GENERATED = {"data/index.json", "data/trends.json", "data/daily.json"}
is_generated = lambda f: f in GENERATED or f.startswith(("data/weeks/", "data/directions/", "data/fields/"))  # rebuilt by build_index.py


def sh(*cmd, check=True):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"FAILED: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def rebase_onto(branch):
    """Rebase on the remote branch; regenerate index/trends if they are the only conflicts."""
    sh("git", "fetch", "origin", branch, check=False)
    r = subprocess.run(["git", "rebase", f"origin/{branch}"], cwd=ROOT, capture_output=True, text=True)
    for _ in range(10):
        if r.returncode == 0:
            return True
        conflicted = set(sh("git", "diff", "--name-only", "--diff-filter=U", check=False).split())
        if not conflicted or not all(is_generated(f) for f in conflicted):
            sh("git", "rebase", "--abort", check=False)
            print(f"rebase conflict outside generated files: {sorted(conflicted)}")
            return False
        for f in conflicted:
            sh("git", "checkout", "--ours", f, check=False)
        sh(sys.executable, "pipeline/build_index.py")
        sh("git", "add", *GENERATED, "data/weeks", "data/directions", "data/fields")
        r = subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=ROOT,
                           capture_output=True, text=True, env={**__import__("os").environ, "GIT_EDITOR": "true"})
    return False


def push(branch):
    for attempt in range(4):
        r = subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            return
        print(f"push failed (attempt {attempt + 1}): {r.stderr.strip()[:300]}")
        rebase_onto(branch)
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
    ap.add_argument("--date")
    ap.add_argument("--summary", help="weekly/<YYYY-Www> or monthly/<YYYY-MM>")
    ap.add_argument("--message")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    if bool(a.date) == bool(a.summary):
        raise SystemExit("give exactly one of --date or --summary")
    site = config("site")
    py = sys.executable
    check = [py, "pipeline/validate.py", a.date] if a.date else [py, "pipeline/validate_summary.py", a.summary]
    v = subprocess.run(check, cwd=ROOT, capture_output=True, text=True)
    print(v.stdout)
    if v.returncode:
        raise SystemExit("FAILED: validation errors — fix them and re-run publish.py")
    print(sh(py, "pipeline/build_index.py"))
    if a.no_push:
        return
    sh("git", "add", "data")
    if sh("git", "status", "--porcelain", "data", check=False):
        kind, _, sid = (a.summary or "").partition("/")
        sh("git", "commit", "-m", a.message or (f"Digest {a.date}" if a.date else f"{kind.capitalize()} summary {sid}"))
    push(site["branch"])
    sha = sh("git", "rev-parse", "HEAD")
    print(f"pushed {sha[:8]} to {site['branch']}; waiting for GitHub Pages deploy...")
    concl, run_url = wait_pages_run(site["repo"], sha)
    print(f"pages run: {concl} {run_url or ''}")
    if concl not in (None, "success"):
        raise SystemExit(f"FAILED: Pages deploy {concl}. Inspect: gh api repos/{site['repo']}/actions/runs?head_sha={sha}")
    if a.date:
        rel, page = f"data/days/{a.date}.json", f"#/day/{a.date}"
    else:
        kind, _, sid = a.summary.partition("/")
        rel, page = f"data/summaries/{kind}/{sid}.json", f"#/trends/{'week' if kind == 'weekly' else 'month'}/{sid}"
    expect = json.loads((ROOT / rel).read_text())["generated_at"]
    if not wait_live(f"{site['url']}{rel}", expect):
        raise SystemExit(f"FAILED: {site['url']}{rel} does not serve the new content after 15 min")
    print(f"LIVE ✓ {site['url']}{page}")


if __name__ == "__main__":
    main()
