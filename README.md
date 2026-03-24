# NSE Stock Scraper

Scrapy project that collects NSE market data and writes to Supabase.

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

## Logs and Verification

After each run:

- `reports/run-YYYY-MM-DD_HHMMSS.log`
- `reports/task-runner.log`

Successful runs include:

- `RUN_STATUS SUCCESS`

Failure runs include:

- `RUN_STATUS FAILED ...`

## Project Layout

```text
nse-stock-scraper/
├── deployment/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── cron/
│       └── weekday-cron.example
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
