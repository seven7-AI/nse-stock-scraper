# NSE Stock Scraper

Scrapy project that collects NSE market data and writes to Supabase.

For a full walkthrough of the architecture and the data flow from the cron entry to the
stored row, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What Runs Daily

- `afx_scraper`
- `stockanalysis_scraper` (runs with cache disabled)

Both spiders are executed by `scripts/run_daily_job.sh`, which writes logs to `reports/`.

## Environment

This project uses the root `.env` file directly.

Required variables:

- `DB_BACKEND=supabase`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_TABLE` (default: `stock_data`)
- `STOCKANALYSIS_TABLE` (default: `stockanalysis_stocks`)

Optional:

- `LOG_LEVEL=INFO`
- `DOWNLOAD_TIMEOUT` (default: `30`) — seconds before a request is abandoned
- `AFX_PROXY_URL` — route `afx_scraper` through an outbound proxy (see below)
- `STOCKANALYSIS_MAX_SYMBOLS` (default: `16`, `0` = no cap) — symbols enriched per run; runs rotate through the list so every ticker is refreshed every few days
- `STOCKANALYSIS_SYMBOL_PAGES` (default: `quote,dividend`) — which per-symbol pages to fetch; add `company` to also collect `country`, at ~50% more requests
- `STOCKANALYSIS_DOWNLOAD_DELAY` (default: `2`) — seconds between requests to stockanalysis.com

Data-quality thresholds (default `0`, i.e. the gate reports but never fails):

- `MIN_ITEMS_AFX_SCRAPER`
- `MIN_ITEMS_STOCKANALYSIS_SCRAPER`

## Data Quality Gate

Scrapy exits `0` even when a spider scrapes nothing, so exit codes alone cannot tell a
healthy run from a silently empty one. After each crawl the `DataQualityGate` extension
writes `reports/stats/<spider>-latest.json` (plus a timestamped copy) with the item
count, database write counts and a `quality_ok` flag. `scripts/run_daily_job.sh` reads
it and reports `RUN_STATUS FAILED` when a spider scrapes fewer than `MIN_ITEMS_<SPIDER>`
items, or when every database write fell back to `reports/local_fallback/`.

Thresholds default to `0` so CI and ad-hoc runs are unaffected; set real values in
`.env`. Raise them as data sources are fixed rather than setting aspirational values,
or the job reports FAILED every day.

## Data Sources

`stockanalysis_scraper` reads the overview view from the list page's embedded payload.
The `api.stockanalysis.com/api/screener/*` endpoints that used to supply the other four
views were retired (they now return 404), so `performance`, `dividends`, `price` and
`profile` are rebuilt from per-symbol pages — roughly 3 extra requests per ticker. Note
that only the 1-year return (`tr1y`) is still published for NSE tickers; `tr1m`, `tr6m`,
`trYTD`, `tr5y` and `tr10y` are not available from any server-rendered source.

**The site rate-limits bulk crawling of per-symbol pages.** A full-catalogue run (126
requests) drew 353 `403` responses against only 36 successes. Three things follow, and
changing any of them will bring the blocking back:

- `403` is **not** retried — retrying an active rate limit multiplies the requests and
  deepens the block.
- Each run enriches only `STOCKANALYSIS_MAX_SYMBOLS` tickers, rotating daily, so the
  catalogue is covered every few days at ~32 requests per run instead of 126.
- Requests run 1-at-a-time with a 2s floor and autothrottle on top.

This is a good fit for the data: the enriched fields (dividends, profile, 52-week range)
move slowly, while `price` and `change` still refresh daily for **every** ticker from the
single list-page request. If 403s reappear, lower `STOCKANALYSIS_MAX_SYMBOLS` or raise
`STOCKANALYSIS_DOWNLOAD_DELAY`.

`afx.kwayisi.org` currently refuses connections from the production host on every one of
its addresses. Set `AFX_PROXY_URL=http://host:port` to route only that spider through a
proxy; leaving it empty keeps behaviour unchanged.

## Known Outages

- **Supabase project unreachable.** `SUPABASE_URL` no longer resolves in DNS, so every
  write fails and falls back to `reports/local_fallback/*.jsonl`. Restore the project or
  update `SUPABASE_URL`/`SUPABASE_KEY`, then replay the fallback files.
- **`afx_scraper` returns nothing** — see `AFX_PROXY_URL` above.
- **`performance` view is partial** — only `tr1y` is published for NSE tickers.

## Run Locally (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scrapy crawl afx_scraper
python -m scrapy crawl stockanalysis_scraper -s HTTPCACHE_ENABLED=False
```

## Run with Docker (one-shot job)

```bash
docker compose -f deployment/docker-compose.yml build scraper-job
docker compose -f deployment/docker-compose.yml run --rm scraper-job
```

## Daily Cron (09:00 Africa/Nairobi)

Install the cron entry:

```bash
bash scripts/install_daily_cron.sh
```

This installs:

- `CRON_TZ=Africa/Nairobi`
- `0 9 * * * cd <repo> && bash scripts/run_daily_with_git.sh`

To inspect current cron entries:

```bash
crontab -l
```

To check the entry is still installed (exits non-zero if not):

```bash
make cron-verify
```

> **The entry can be removed without warning.** `install_daily_cron.sh` only ever
> appends, but any other project running `crontab <file>` replaces the *whole* user
> crontab. That is what silently removed this job on 2026-07-05, and no run happened
> for the following three weeks. Run `make cron-verify` after any crontab change made
> by another project.

The installer prints the intended fire time in both `Africa/Nairobi` and host-local
time. Historically runs fired at 09:00 host-local rather than 09:00 Nairobi, so compare
against the first observed run in `reports/task-runner.log` and adjust `CRON_HOUR` in
the script if this cron ignores `CRON_TZ`.

## Logs and Verification

After each run:

- `reports/run-YYYY-MM-DD_HHMMSS.log`
- `reports/task-runner.log`
- `reports/stats/<spider>-latest.json` (item counts and the quality verdict)

Successful runs include:

- `RUN_STATUS SUCCESS`

Failure runs include:

- `RUN_STATUS FAILED ...`
- `QUALITY <spider> FAILED items=... min=...` when a spider scraped too little

The git step logs its own outcome, so a commit or push that fails is visible rather
than silently swallowed:

- `GIT_COMMIT_STATUS SUCCESS|FAILED`
- `GIT_PUSH_STATUS SUCCESS|FAILED`

## Project Layout

```text
nse-stock-scraper/
├── deployment/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── cron/
│       └── daily-cron.example
├── scripts/
│   ├── run_daily_job.sh
│   ├── run_daily_with_git.sh
│   └── install_daily_cron.sh
├── nse_scraper/
├── docs/
├── config/
├── reports/
└── .env
```

## Notes

- Windows PowerShell scheduling scripts were removed.
- Scheduler is now Linux cron + Docker.
- Runtime is Supabase-only.
