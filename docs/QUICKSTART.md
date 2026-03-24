# Quickstart

## 1) Configure environment

```bash
cp config/.env.example .env
```

Set:

- `DB_BACKEND=supabase`
- `SUPABASE_URL`
- `SUPABASE_KEY`

## 2) Build and run one job

```bash
docker compose -f deployment/docker-compose.yml build scraper-job
docker compose -f deployment/docker-compose.yml run --rm scraper-job
```

## 3) Install weekday schedule

```bash
bash scripts/install_weekday_cron.sh
crontab -l
```

The schedule runs every Monday-Friday at `09:00` in `Africa/Nairobi`.
