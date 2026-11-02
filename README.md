# AI Updated

A daily digest of the most important AI news and papers, curated and explained by Claude every morning
(Monday–Saturday, 7:30 ET): **up to 2 news stories and 5 papers per day, ~250–350 words each**, with tag and
calendar filters. On top of it, a **Trends dashboard** with weekly (Sunday) and monthly (1st of the month)
syntheses of where research and the industry are heading, checked against statistics on every new arXiv paper.

**Site:** https://guaaaaa.github.io/AI_Updated/

## How it works

1. A Claude Code **cloud scheduled task** starts a fresh session every Monday–Saturday at 7:30 ET (no laptop
   needed) and follows [`RUNBOOK.md`](RUNBOOK.md).
2. `pipeline/fetch_papers.py` scans every paper announced on arXiv in the window (cs.AI, cs.LG, cs.CL,
   cs.CV, cs.RO, cs.MA, cs.NE, stat.ML), attaches signals — alphaXiv Hot rank (MCP), Hugging Face upvotes,
   notable authors/labs, released code — and shortlists ~40.
3. `pipeline/fetch_news.py` collects headlines from official lab blogs, reputable press (via Google News
   search) and Hacker News for the last 72 hours.
4. Claude screens, reads the finalists in full from arXiv, selects with the rubric in `RUNBOOK.md`
   (importance + diversity), writes the summaries, and `pipeline/assemble.py` + `pipeline/validate.py`
   enforce the format, word counts, tag taxonomy, time windows and de-duplication.
5. `pipeline/publish.py` pushes to `master` and waits until GitHub Pages serves the new digest.

**Windows:** papers announced in the last 72 hours (Saturday: best of the past 7 days); news from the last
72 hours. Nothing is repeated within 7 days.

## Trend summaries

Two more scheduled tasks follow [`RUNBOOK_SUMMARY.md`](RUNBOOK_SUMMARY.md): **weekly** on Sunday (that week's
Monday–Saturday digests) and **monthly** on the 1st (the previous month).
- `pipeline/prepare_summary.py` builds the evidence brief: previous summaries, our digest items,
  high-attention papers we skipped, the most-covered news stories, and **field-wide arXiv statistics**
  (`pipeline/arxiv_stats.py`: topic-group shares and rising/fading title terms across *all* new papers in our
  categories, vs the previous four weeks or month).
- Claude writes a Research part and an Industry part (350–500 words each), where every paragraph cites its
  evidence. `pipeline/assemble_summary.py` and `pipeline/validate_summary.py` check the format, word counts and
  references; `publish.py --summary weekly/<id>` publishes it.
- The dashboard (`#/trends`, `assets/trends.js`) shows the day at a glance, the latest weekly and monthly
  summaries, charts (topic-group trends, a topic heat map, rising and fading terms, everything featured), and
  the archive.

## Customize

- Tags and news categories: `config/taxonomy.json`
- Feeds, search queries, arXiv categories: `config/sources.json`
- Notable researchers/labs (a tiebreaker signal): `config/notable.json`
- Selection and writing rules: `RUNBOOK.md` (digests), `RUNBOOK_SUMMARY.md` (trend summaries)
- Topic keywords for the field statistics: `config/topic_lexicon.json`

## Run locally

```bash
pip install beautifulsoup4
python3 pipeline/fetch_papers.py --date 2026-11-02   # needs ALPHAXIV_API_KEY for the Hot feed
python3 pipeline/fetch_news.py --date 2026-11-02
python3 -m http.server   # then open http://localhost:8000
```
