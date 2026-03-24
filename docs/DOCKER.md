# Docker + Cron Operations

## One-shot Docker Run

This repo uses a single job service named `scraper-job`.

```bash
docker compose -f deployment/docker-compose.yml build scraper-job
docker compose -f deployment/docker-compose.yml run --rm scraper-job
```

The service runs `scripts/run_daily_job.sh`, which executes both spiders and writes logs in `reports/`.

## Environment Source

Docker Compose reads the root `.env` file directly:

- `DB_BACKEND=supabase`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_TABLE`
- `STOCKANALYSIS_TABLE`

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
```
