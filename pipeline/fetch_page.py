"""Fetch a web page and print its readable text (fallback when WebFetch is unavailable).

Honest User-Agent; if a site answers with a bot check (403/429), it reports that and moves on:
do not try to get around it — use the site's RSS entry and other reputable coverage instead.

Usage: python pipeline/fetch_page.py URL [URL ...] [--max-words 1500]
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ensure_bs4, http_get  # noqa: E402

BeautifulSoup = ensure_bs4()



def readable(page, max_words):
    soup = BeautifulSoup(page, "html.parser")
    meta = {}
    for key in ("og:title", "article:published_time", "og:site_name", "description", "og:description"):
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            meta[key] = tag["content"].strip()
    title = meta.get("og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    for junk in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe"]):
        junk.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [" ".join(p.get_text(" ").split()) for p in root.find_all(["h1", "h2", "h3", "p", "li"])]
    paras = [p for p in paras if len(p.split()) > 3]
    text = "\n".join(paras) if paras else " ".join(root.get_text(" ").split())
    words = text.split(" ")
    if len(words) > max_words:
        text = " ".join(words[:max_words]) + " [...]"
    head = [f"TITLE: {title}"]
    if len(text.split()) < 80:
        head.append("NOTE: very little text extracted; the page probably renders with JavaScript. Use other sources.")
    if meta.get("article:published_time"):
        head.append(f"PUBLISHED: {meta['article:published_time']}")
    if meta.get("og:site_name"):
        head.append(f"SITE: {meta['og:site_name']}")
    return "\n".join(head) + "\n\n" + text


def pdf_text(url, max_words):
    import subprocess
    import tempfile
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "ai-updated-digest/0.1"})
    data = urllib.request.urlopen(req, timeout=60).read()
    if not data.startswith(b"%PDF"):
        return None
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        txt = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    w = " ".join(txt.split()).split(" ")
    return "TITLE: (PDF document)\n\n" + " ".join(w[:max_words]) + (" [...]" if len(w) > max_words else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--max-words", type=int, default=1500)
    a = ap.parse_args()
    for url in a.urls:
        print(f"\n==================== {url} ====================")
        try:
            if url.lower().split("?")[0].endswith(".pdf"):
                print(pdf_text(url, a.max_words) or "UNAVAILABLE (not a PDF)")
                continue
            page = http_get(url, headers={"Accept": "text/html"}, timeout=40, retries=2)
            if page.startswith("%PDF"):
                page = pdf_text(url, a.max_words)
                print(page or "UNAVAILABLE")
                continue
            print(readable(page, a.max_words))
        except Exception as e:
            msg = str(e)
            blocked = re.search(r"HTTP Error (403|429)", msg)
            print(f"UNAVAILABLE ({'blocked by the site; use its RSS entry / other coverage' if blocked else msg[:200]})")


if __name__ == "__main__":
    main()
