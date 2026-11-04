# Updated

Daily digests of the most important news and research, curated and explained by Claude every morning
(Monday–Saturday): one tab per **domain**, each item explained in ~250–350 words, with tag and calendar filters.

| Domain | Daily items | Sources | Runbook |
|---|---|---|---|
| **AI** | ≤2 news + ≤5 papers | arXiv (alphaXiv Hot, Hugging Face), lab blogs, reputable press | [`RUNBOOK.md`](RUNBOOK.md) |
| **Business** | ≤5 news + ≤1 research | Fed, Bank of Canada, BEA, ECB, business press, NBER working papers | [`RUNBOOK_BUSINESS.md`](RUNBOOK_BUSINESS.md) |
| **Science** | ≤3 news + ≤3 papers | NASA, NIH, NSF, science press, Nature, Science, Cell, NEJM, The Lancet, PNAS and others | [`RUNBOOK_SCIENCE.md`](RUNBOOK_SCIENCE.md) |

AI also has a **Trends** view (a monthly synthesis grounded in statistics on every new arXiv paper and news story,
stock-style direction and field pages, an automatic Week in review), and there is a cross-domain **Jobs** board.
Domains are listed in `config/domains.json`; each has its own sources and taxonomy in `config/domains/<id>/`
(AI keeps `config/*.json`) and its own data in `data/<id>/` (AI keeps `data/days/`). Every pipeline script takes
`--domain <id>` (default `ai`).

**Site:** https://guaaaaa.github.io/AI_Updated/ (`#/ai`, `#/business`, `#/science`, `#/jobs`)

## How it works (AI; the other domains follow the same steps with `fetch_research.py` for papers)

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

## Jobs

The job board (`#/jobs`) rates AI and tech jobs in the **US and Canada** from the job market itself; research only
enters through a labelled heuristic. No AI usage: everything is fetched and counted by `pipeline/`.
- **Roles** (`config/jobs.json`): 21 roles, with titles that differ on paper but are the same work fused (e.g. ML,
  LLM, applied-AI and NLP engineers and applied scientists are one role). Each maps to US SOC and Canadian NOC codes
  and an Indeed category. Rules in `pipeline/jobs_classify.py` read the title (and the team for generic titles like
  "Member of Technical Staff"), the location, seniority, posted pay, years asked, PhD, remote and equity.
- **Daily snapshot** (`pipeline/fetch_jobs.py`, run by the AI `prepare.py`): the public job boards (Greenhouse,
  Ashby, Lever, plus Workday and amazon.jobs for big tech: NVIDIA, Amazon, Salesforce, Intel, Cisco, Capital One,
  RBC, TD and others) of 238 employers (`config/employers.json`, found by `pipeline/ats.py --probe` from
  `config/employer_candidates.txt`). Open postings live in `data/state/jobs/open.tsv`; each day adds a line of role
  metrics to `data/state/jobs/daily/`. New and closed postings are counted only on boards seen the day before, and
  openings are chain-linked over boards that answered both days, so outages and newly added employers never look
  like hiring swings. Snapshots started on Nov 4, 2026 and cannot be backfilled.
- **Official statistics** (`pipeline/jobs_history.py --official`): BLS occupational employment and median wages
  (US; set `BLS_API_KEY` for more than the keyless daily allowance) and Job Bank 3-year employment outlooks
  (Canada, by economic region).
- **History** (`pipeline/jobs_history.py`): Hacker News "Who is hiring?" ads since Dec 2012 and "Who wants to be
  hired?" posts since 2014 (role shares and seekers per ad), Indeed Hiring Lab's postings index by category since
  Feb 2020 (CC BY 4.0), and the Anthropic Economic Index's AI and robot exposure by occupation.
- **Role pages** (`#/jobs/<id>`) work like the field pages: openings, new postings, pay, startup demand (Hacker News)
  and the Indeed market index, each with its own ranges (up to 5Y / all for the long series), a US / Canada switch,
  key statistics, how the role scores, "what moves this job" (signed research weights x direction momentum),
  who's hiring and the latest postings.
- **Score**: each criterion ranks the roles against each other -- demand trend, openings, pay, ease of entry, low
  competition, stability, AI outlook (research tailwind) and flexibility -- and visitors weight them with sliders.
  Work-life balance has no reliable open data, so it is not scored.

## Customize

- Tags and news categories: `config/taxonomy.json`
- Feeds, search queries, arXiv categories: `config/sources.json`
- Notable researchers/labs (a tiebreaker signal): `config/notable.json`
- Selection and writing rules: `RUNBOOK.md` (digests), `RUNBOOK_SUMMARY.md` (trend summaries)
- Research directions and industry categories for the trend model: `config/directions.json`, `config/industry.json`
- Job board roles, title rules and research weights: `config/jobs.json`; employers: add lines to
  `config/employer_candidates.txt`, then `python3 pipeline/ats.py --probe`

## Run locally

```bash
pip install beautifulsoup4
python3 pipeline/fetch_papers.py --date 2026-11-02   # needs ALPHAXIV_API_KEY for the Hot feed
python3 pipeline/fetch_news.py --date 2026-11-02
python3 pipeline/field_daily.py --update             # last five announcement days (fetch_papers.py does this too)
python3 pipeline/build_index.py                      # regenerate index, trends and page data
python3 -m http.server   # then open http://localhost:8000
```
