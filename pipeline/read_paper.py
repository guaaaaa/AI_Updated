"""Fetch a paper's text from arXiv for Claude to read (token-efficient).

  --mode brief : abstract, author/affiliation block, intro (trimmed), section outline,
                 figure/table captions, conclusion (~1.5-2k words). Use for screening ~10 papers.
  --mode full  : main body (no references/appendix), capped at --max-words. Use for the final 5.

Source: arXiv HTML (https://arxiv.org/html/<id>), falling back to the PDF via pdftotext.
Usage: python pipeline/read_paper.py 2610.39302 --mode brief
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORK, http_get  # noqa: E402

from bs4 import BeautifulSoup  # noqa: E402

CONCL_RE = re.compile(r"conclu|discussion|limitation|future work|summary", re.I)


def words(t, n):
    w = t.split()
    return " ".join(w[:n]) + (" [...]" if len(w) > n else "")


def text_of(el):
    for m in el.find_all("math"):
        alt = m.get("alttext")
        m.replace_with(f" ${alt}$ " if alt else " ")
    for cite in el.find_all(class_="ltx_cite"):
        cite.replace_with(" [cite] ")
    return " ".join(el.get_text(" ").split())


def from_html(pid):
    page = http_get(f"https://arxiv.org/html/{pid}", timeout=60)
    soup = BeautifulSoup(page, "html.parser")
    if not soup.find(class_="ltx_page_main") and not soup.find("article"):
        raise RuntimeError("no HTML rendering")
    title = soup.find(class_="ltx_title_document")
    authors = soup.find(class_="ltx_authors")
    abstract = soup.find(class_="ltx_abstract")
    for junk in soup.find_all(class_=["ltx_bibliography", "ltx_appendix"]):
        junk.decompose()
    caps = [text_of(c) for c in soup.find_all("figcaption")]
    for f in soup.find_all(["figure"]):
        f.decompose()
    sections = []
    for sec in soup.find_all("section", class_="ltx_section"):
        h = sec.find(["h2", "h3"])
        head = text_of(h) if h else ""
        if h:
            h.decompose()
        body = " ".join(text_of(p) for p in sec.find_all(class_="ltx_para"))
        sections.append((head, body))
    return {
        "title": text_of(title) if title else "",
        "authors": words(text_of(authors), 160) if authors else "",
        "abstract": text_of(abstract) if abstract else "",
        "sections": sections,
        "captions": caps,
        "source": f"https://arxiv.org/html/{pid}",
    }


def from_pdf(pid):
    import urllib.request
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "p.pdf"
        req = urllib.request.Request(f"https://arxiv.org/pdf/{pid}", headers={"User-Agent": "ai-updated-digest/0.1"})
        pdf.write_bytes(urllib.request.urlopen(req, timeout=90).read())
        txt = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
    main = re.split(r"\n\s*(References|REFERENCES|Bibliography)\s*\n", txt)[0]
    main = " ".join(main.split())
    return {"title": "", "authors": "", "abstract": "", "sections": [("Full text (PDF)", main)],
            "captions": [], "source": f"https://arxiv.org/pdf/{pid}"}


def render(doc, mode, max_words):
    out = [f"SOURCE: {doc['source']}"]
    if doc["title"]:
        out.append(f"TITLE: {doc['title']}")
    if doc["authors"]:
        out.append(f"AUTHORS/AFFILIATIONS: {doc['authors']}")
    if doc["abstract"]:
        out.append(f"\n{doc['abstract']}")
    secs = doc["sections"]
    if mode == "brief":
        if secs:
            out.append(f"\n## {secs[0][0]}\n{words(secs[0][1], 550)}")
            out.append("\nOUTLINE: " + " | ".join(h for h, _ in secs if h))
        if doc["captions"]:
            out.append("\nCAPTIONS:\n" + "\n".join(f"- {words(c, 55)}" for c in doc["captions"][:12]))
        concl = [s for s in secs[1:] if CONCL_RE.search(s[0])]
        if concl:
            out.append(f"\n## {concl[-1][0]}\n{words(concl[-1][1], 400)}")
        elif len(secs) > 1:
            out.append(f"\n## {secs[-1][0]}\n{words(secs[-1][1], 400)}")
    else:
        budget = max_words
        for h, b in secs:
            if budget <= 0:
                out.append("\n[truncated: word budget reached]")
                break
            out.append(f"\n## {h}\n{words(b, budget)}")
            budget -= len(b.split())
        if doc["captions"]:
            out.append("\nCAPTIONS:\n" + "\n".join(f"- {words(c, 70)}" for c in doc["captions"][:20]))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--mode", choices=["brief", "full"], default="brief")
    ap.add_argument("--max-words", type=int, default=6000)
    a = ap.parse_args()
    cache = WORK / "papers"
    cache.mkdir(parents=True, exist_ok=True)
    for pid in a.ids:
        try:
            doc = from_html(pid)
        except Exception as e:
            print(f"(HTML unavailable for {pid}: {e}; using PDF)", file=sys.stderr)
            doc = from_pdf(pid)
        txt = render(doc, a.mode, a.max_words)
        (cache / f"{pid}.{a.mode}.txt").write_text(txt)
        print(f"\n==================== {pid} ({a.mode}, {len(txt.split())} words) ====================\n{txt}")


if __name__ == "__main__":
    main()
