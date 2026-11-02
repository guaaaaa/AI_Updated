# AI Updated

A daily digest of the most important AI news and papers, curated and explained by Claude every morning at
7:30 ET: **up to 2 news stories and 5 papers per day, ~300–400 words each**, with tag and calendar filters.

**Site:** https://guaaaaa.github.io/AI_Updated/

## How it works

1. A Claude Code **cloud scheduled task** starts a fresh session every day at 7:30 ET (no laptop needed)
   and follows [`RUNBOOK.md`](RUNBOOK.md).
2. `pipeline/fetch_papers.py` scans every paper announced on arXiv in the window (cs.AI, cs.LG, cs.CL,
   cs.CV, cs.RO, cs.MA, cs.NE, stat.ML), attaches signals — alphaXiv Hot rank (MCP), Hugging Face upvotes,
   notable authors/labs, released code — and shortlists ~40.
3. `pipeline/fetch_news.py` collects headlines from official lab blogs, reputable press (via Google News
   search) and Hacker News for the last 72 hours.
4. Claude screens, reads the finalists in full from arXiv, selects with the rubric in `RUNBOOK.md`
   (importance + diversity), writes the summaries, and `pipeline/assemble.py` + `pipeline/validate.py`
   enforce the format, word counts, tag taxonomy, time windows and de-duplication.
5. `pipeline/publish.py` pushes to `master` and waits until GitHub Pages serves the new digest.

**Windows:** papers announced in the last 72 hours (weekends: best of the past 7 days); news from the last
72 hours. Nothing is repeated within 7 days.

## Customize

- Tags and news categories: `config/taxonomy.json`
- Feeds, search queries, arXiv categories: `config/sources.json`
- Notable researchers/labs (a tiebreaker signal): `config/notable.json`
- Selection and writing rules: `RUNBOOK.md`

## Run locally

```bash
pip install beautifulsoup4
python3 pipeline/fetch_papers.py --date 2026-11-02   # needs ALPHAXIV_API_KEY for the Hot feed
python3 pipeline/fetch_news.py --date 2026-11-02
python3 -m http.server   # then open http://localhost:8000
```
