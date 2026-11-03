# AI Updated

A daily digest of the most important AI news and papers, curated and explained by Claude every morning
(Monday–Saturday, 7:30 ET): **up to 2 news stories and 5 papers per day, ~250–350 words each**, with tag and
calendar filters. On top of it, a **Trends dashboard**: a monthly synthesis of where research and the industry are
heading, grounded in statistics on every new arXiv paper and news story, plus an automatic Week in review.

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

## Trends

The Trends dashboard (`#/trends`) is about the **whole field**, not our picks:
- **Field model** (`pipeline/field_data.py`, `pipeline/field_stats.py`, no AI usage): every new arXiv paper in our
  categories (monthly listings, 24+ months of history), Hugging Face Daily Papers upvotes (attention) and
  reputable-outlet AI news stories. 56 research directions (`config/directions.json`) and industry categories and
  companies (`config/industry.json`) are tracked month by month. A direction counts as **rising** or **fading** only if
  its 3-month share moved significantly against the previous 3 months, held for 2+ months, spans 15+ teams and is not
  contradicted by the same period a year earlier.
- **Monthly summary** (1st of the month, [`RUNBOOK_SUMMARY.md`](RUNBOOK_SUMMARY.md)): Claude interprets the field
  report in a Research part and an Industry part (350–500 words each). Every trend claim must cite field-level
  evidence; our digest items may only illustrate. Validated by `pipeline/validate_summary.py`.
- **Week in review** (`pipeline/week_review.py`, automatic, no AI usage): the week's most-upvoted papers and
  most-covered stories, with no trend claims. A week is too short to show a direction.
- **Dashboard views:** the six fields as index tiles (share of new papers over the past year), a leaderboard of all directions (24-month sparklines, 3-month and 1-year change, attention),
  growth since a year ago (indexed, log scale), a momentum map (size vs growth quadrants), a heat map, emerging
  terms and industry categories. Each chart is titled with a finding computed from the numbers.
- **Direction and field pages** (`#/trends/direction/<id>`, `#/trends/field/<slug>`), styled like a stock page: the
  current value and its change, a chart with 1W / 1M / 3M / 6M / 1Y / 2Y ranges (each point averages 1, 5, 10, 21,
  42 or 63 announcement days, so longer ranges are smoother; drag across it to read any day), measured as share of
  new papers, papers per day or share of Hugging Face upvotes, with daily volume bars, key statistics, the field's
  directions as ticker rows, the most-upvoted papers and our featured items. Changes smaller than chance variation
  (|z| < 2) are marked "within noise".
- **Daily field series** (`pipeline/field_daily.py`, `data/state/field_daily/`): new papers per arXiv announcement
  day for every direction and field, plus Hugging Face upvotes. Each daily run rewrites the last five announcement
  days from the arXiv pastweek listing (exact days); history comes from the monthly listings, with each paper's day
  inferred from arXiv API submission times and the announcement schedule (99% on the right day when checked against
  exact listings; holidays are not modelled, which leaves shares unchanged).

## Customize

- Tags and news categories: `config/taxonomy.json`
- Feeds, search queries, arXiv categories: `config/sources.json`
- Notable researchers/labs (a tiebreaker signal): `config/notable.json`
- Selection and writing rules: `RUNBOOK.md` (digests), `RUNBOOK_SUMMARY.md` (trend summaries)
- Research directions and industry categories for the trend model: `config/directions.json`, `config/industry.json`

## Run locally

```bash
pip install beautifulsoup4
python3 pipeline/fetch_papers.py --date 2026-11-02   # needs ALPHAXIV_API_KEY for the Hot feed
python3 pipeline/fetch_news.py --date 2026-11-02
python3 pipeline/field_daily.py --update             # last five announcement days (fetch_papers.py does this too)
python3 pipeline/build_index.py                      # regenerate index, trends and page data
python3 -m http.server   # then open http://localhost:8000
```
