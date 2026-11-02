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
from common import WORK, ensure_bs4, http_get  # noqa: E402

BeautifulSoup = ensure_bs4()


CONCL_RE = re.compile(r"conclu|discussion|limitation|future work|summary", re.I)
def is_concl(h):  # small-caps PDFs render "CONCLUSION" as "C ONCLUSION"
    return bool(CONCL_RE.search(h.replace(" ", "")))


RELATED_RE = re.compile(r"related work|prior work|background|literature", re.I)


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
    tables = []
    for fig in soup.find_all("figure", class_="ltx_table"):
        cap = fig.find("figcaption")
        rows = []
        for tr in fig.find_all("tr"):
            cells = [text_of(td) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(" | ".join(c for c in cells))
        if rows:
            tables.append((text_of(cap) if cap else "Table", rows))
    caps = [text_of(c) for c in soup.find_all("figcaption")]
    for f in soup.find_all(["figure"]):
        f.decompose()
    sections = []
    for sec in soup.find_all("section", class_="ltx_section"):
        h = sec.find(["h2", "h3"])
        head = text_of(h) if h else ""
        if h:
            h.decompose()
        paras = [p for p in sec.find_all(class_="ltx_para") if not p.find_parent(class_="ltx_para")]  # no nested dupes
        body = " ".join(text_of(p) for p in paras)
        sections.append((head, body))
    return {
        "title": text_of(title) if title else "",
        "authors": words(text_of(authors), 160) if authors else "",
        "abstract": text_of(abstract) if abstract else "",
        "sections": sections,
        "captions": caps,
        "tables": tables,
        "source": f"https://arxiv.org/html/{pid}",
    }


PDF_HEAD_RE = re.compile(r"^\s*((?:\d+|[IVX]+)(?:\.\d+)?\.?)\s+([A-Z][A-Za-z0-9 ,:&\-\u2013()/]{2,70})\s*$")
PDF_ABS_RE = re.compile(r"^\s*Abstract\s*$", re.I)


def from_pdf(pid):
    """PDF fallback: split pdftotext output into numbered top-level sections."""
    import urllib.request
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "p.pdf"
        req = urllib.request.Request(f"https://arxiv.org/pdf/{pid}", headers={"User-Agent": "ai-updated-digest/0.1"})
        pdf.write_bytes(urllib.request.urlopen(req, timeout=90).read())
        txt = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
    txt = re.split(r"\n\s*(?:References|REFERENCES|Bibliography)\s*\n", txt)[0]
    txt = re.split(r"\n\s*(?:Appendix|APPENDIX|Appendices|Supplementary Material)\s*\n", txt)[0]
    lines = txt.splitlines()
    freq = {}
    for ln in lines:
        t = ln.strip()
        if t:
            freq[t] = freq.get(t, 0) + 1
    repeated = lambda t: freq.get(t, 0) >= 3 or t.lower() in ("preprint", "under review", "arxiv")
    front, sections, cur, abstract = [], [], None, ""
    expect, i = 1, 0
    title_ok = lambda t: 2 < len(t) <= 70 and t[:1].isupper() and not t.endswith(".") and len(t.split()) <= 9
    while i < len(lines):
        ln = lines[i].strip()
        head = None
        m = PDF_HEAD_RE.match(ln)
        if m and m.group(1).rstrip(".") == str(expect) and not repeated(m.group(2).strip()):  # "3 Method"
            head = f"{expect} {m.group(2).strip()}"
        elif ln == str(expect) or ln == f"{expect}.":            # "3" then "Method" on a later line
            j = i + 1
            while j < len(lines) and not lines[j].strip() and j - i < 3:
                j += 1
            if j < len(lines) and title_ok(lines[j].strip()) and not repeated(lines[j].strip()):
                head, i = f"{expect} {lines[j].strip()}", j
        if head and sections and is_concl(sections[-1][0]) and not is_concl(head):
            head = None  # after the conclusion, numbered lines are figure/table debris
        if head:
            cur = [head, []]
            sections.append(cur)
            expect += 1
        elif cur is None:
            front.append(ln)
        else:
            cur[1].append(ln)
        i += 1
    front_text = " ".join(" ".join(front).split())
    am = re.search(r"\bAbstract\b[.:]?\s*(.*)", front_text, re.I)
    if am:
        abstract, authors = am.group(1)[:2500], front_text[:am.start()]
    else:
        authors = front_text[:800]
    secs = [(h, " ".join(" ".join(b).split())) for h, b in sections]
    secs = [(h, b) for h, b in secs if len(b.split()) > 20]
    if len(secs) < 2:  # heading detection failed: fall back to one block
        secs = [("Full text (PDF)", " ".join(txt.split()))]
    secs = [(h, " ".join(w for w in b.split(" ") if w)) for h, b in secs]
    return {"title": "", "authors": words(authors, 160), "abstract": abstract, "sections": secs, "tables": [],
            "captions": re.findall(r"((?:Figure|Fig\.|Table) \d+[:.][^\n]{20,300})", txt)[:20],
            "source": f"https://arxiv.org/pdf/{pid}"}


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
        concl = [s for s in secs[1:] if is_concl(s[0])]
        if concl:
            out.append(f"\n## {concl[-1][0]}\n{words(concl[-1][1], 400)}")
        elif len(secs) > 1:
            out.append(f"\n## {secs[-1][0]}\n{words(secs[-1][1], 400)}")
    else:
        # Water-fill the word budget: every section gets an equal share (short sections keep all their
        # words, long intros/related work get trimmed), so results and conclusions are never cut off.
        tables = doc.get("tables") or []
        tbl_txt = []
        for cap, rows in tables[:6]:
            tbl_txt.append(f"- {words(cap, 30)}\n    " + "\n    ".join(words(r, 40) for r in rows[:14]))
        tbl_block = "\n".join(tbl_txt)
        budget = max_words - 550 - min(1200, len(tbl_block.split()))  # room for captions + tables
        lens = [len(b.split()) for _, b in secs]
        if sum(lens) <= budget:
            cap = max(lens or [0])
        else:
            lo, hi = 0, max(lens)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if sum(min(n, mid) for n in lens) <= budget:
                    lo = mid
                else:
                    hi = mid - 1
            cap = lo
        for (h, b), n in zip(secs, lens):
            cut = RELATED_RE.search(h.replace(" ", "").replace("W", " W")) and n > 150
            out.append(f"\n## {h}\n{words(b, min(cap, 150) if cut else cap)}")
        if tbl_block:
            kept, n = [], 0
            for line in tbl_block.splitlines():  # cap by whole lines so rows stay readable
                n += len(line.split())
                if n > 1200:
                    kept.append("    [more rows omitted]")
                    break
                kept.append(line)
            out.append("\nTABLES (cells joined by |):\n" + "\n".join(kept))
        if doc["captions"]:
            out.append("\nCAPTIONS:\n" + "\n".join(f"- {words(c, 45)}" for c in doc["captions"][:12]))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--mode", choices=["brief", "full"], default="brief")
    ap.add_argument("--max-words", type=int, default=5500)
    a = ap.parse_args()
    cache = WORK / "papers"
    cache.mkdir(parents=True, exist_ok=True)
    for pid in a.ids:
        try:
            doc = from_html(pid)
        except Exception as e:
            print(f"(HTML unavailable for {pid}: {e}; using PDF)", file=sys.stderr)
            doc = from_pdf(pid)
        if not doc["abstract"] or not doc["title"]:  # some HTML renderings lack title/abstract markup
            try:
                from fetch_papers import abs_page
                meta = abs_page(pid)
                doc["title"] = doc["title"] or meta["title"]
                doc["abstract"] = doc["abstract"] or meta["abstract"]
                doc["authors"] = doc["authors"] or ", ".join(meta["authors"])
            except Exception as e:
                print(f"(abs page lookup failed for {pid}: {e})", file=sys.stderr)
        txt = render(doc, a.mode, a.max_words)
        (cache / f"{pid}.{a.mode}.txt").write_text(txt)
        print(f"\n==================== {pid} ({a.mode}, {len(txt.split())} words) ====================\n{txt}")


if __name__ == "__main__":
    main()
