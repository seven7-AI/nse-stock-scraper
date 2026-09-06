# Docker + Cron Operations

## One-shot Docker Run

This repo uses a single job service named `scraper-job`.

```bash
docker compose -f deployment/docker-compose.yml build scraper-job
docker compose -f deployment/docker-compose.yml run --rm scraper-job
```

The service runs `scripts/run_daily_job.sh`, which executes both spiders and writes logs in `reports/`.

## Persistent Volumes

The job is a one-shot container (`run --rm`), so anything written inside it is destroyed on
exit. Three host directories are bind-mounted to survive that:

| Host | Container | Holds |
|------|-----------|-------|
| `reports/` | `/app/reports` | run logs, quality stats, fallback JSONL |
| `httpcache/` | `/app/httpcache` | Scrapy HTTP cache (disabled during the daily run) |
| `data/` | `/app/data` | **the SQLite database** |

These directories must exist on the host before the first run. Docker creates a missing
bind-mount source as `root`, and the container runs as uid 1000, so it would then be unable
to write. `reports/.gitkeep` and `data/.gitkeep` are committed to keep them present in a
fresh clone.

## Environment Source

Docker Compose reads the root `.env` file directly, and overrides the storage settings in
`docker-compose.yml` so a container always writes to the mounted volume:

- `DB_BACKEND=sqlite` (set in compose)
- `SQLITE_DB_PATH=/app/data/nse_scraper.sqlite3` (set in compose)
- `STOCK_TABLE`, `STOCKANALYSIS_TABLE`
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_TABLE` — only when `DB_BACKEND=supabase`

## Daily Schedule

Install cron at `09:00` daily in `Africa/Nairobi`:

```bash
bash scripts/install_daily_cron.sh
```

The script writes this entry:

```cron
CRON_TZ=Africa/Nairobi
0 9 * * * cd /path/to/nse-stock-scraper && bash scripts/run_daily_with_git.sh
```

## Validate Setup

```bash
crontab -l
docker compose -f deployment/docker-compose.yml run --rm scraper-job
ls reports/
ls -la data/            # nse_scraper.sqlite3 should exist and have a fresh mtime
tail -5 reports/task-runner.log
```

A run that stored data ends with `RUN_STATUS SUCCESS` and reports `db_ok > 0` in
`reports/stats/<spider>-latest.json`. If `db_failed` is non-zero, check that `data/` is
writable by uid 1000 and look in `reports/local_fallback/` for the rejected payloads.
