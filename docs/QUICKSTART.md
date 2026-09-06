# Quickstart

## 1) Configure environment

```bash
cp config/.env.example .env
```

The defaults are ready to run — SQLite needs no credentials:

- `DB_BACKEND=sqlite`
- `SQLITE_DB_PATH=data/nse_scraper.sqlite3`

The database file is created on first run. To use Supabase instead, set
`DB_BACKEND=supabase` plus `SUPABASE_URL` and `SUPABASE_KEY`.

## 2) Build and run one job

```bash
docker compose -f deployment/docker-compose.yml build scraper-job
docker compose -f deployment/docker-compose.yml run --rm scraper-job
```

## 3) Install daily schedule

```bash
bash scripts/install_daily_cron.sh
crontab -l
```

The schedule runs every day at `09:00` in `Africa/Nairobi`.

## 4) Check the data landed

```bash
python3 -c "
import sqlite3
c = sqlite3.connect('data/nse_scraper.sqlite3')
print('rows:', c.execute('SELECT COUNT(*) FROM stockanalysis_stocks').fetchone()[0])
print('last scrape:', c.execute('SELECT MAX(scraped_at) FROM stockanalysis_stocks').fetchone()[0])
"
```

A healthy run also writes `RUN_STATUS SUCCESS` to `reports/task-runner.log` and
`"quality_ok": true` to `reports/stats/<spider>-latest.json`.
