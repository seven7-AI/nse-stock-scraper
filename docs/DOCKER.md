# Docker Guide

## Quick Start

```bash
cp config/.env.docker .env
docker-compose up --build
```

Use `DB_BACKEND` in `.env` to choose storage:
- `mongo`
- `postgres`
- `supabase`

## Services

`docker-compose.yml` starts:
- `mongodb` (MongoDB local service)
- `postgres` (PostgreSQL local service)
- `scraper` (Scrapy app)

The scraper service can connect to any backend based on env configuration.

## Common Commands

```bash
# Run scraper in debug mode
docker-compose run --rm scraper crawl afx_scraper --loglevel=DEBUG

# Run placeholder utility (no messaging)
docker-compose run --rm scraper python nse_scraper/stock_notification.py

# MongoDB shell
docker-compose exec mongodb mongosh

# PostgreSQL shell
docker-compose exec postgres psql -U postgres -d nse_data

# Stop services
docker-compose down
```

## Environment Template

Use `config/.env.docker` as base. Important variables:
- `DB_BACKEND`
- `MONGODB_URI`
- `MONGODB_DATABASE`
- `SQL_DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_KEY`

## PostgreSQL Migrations in Docker

```bash
docker-compose run --rm scraper alembic upgrade head
```

## Notes

- MongoDB and PostgreSQL data are persisted through Docker volumes.
- Supabase mode requires external Supabase credentials in `.env`.
- Scheduler and SMS integrations are intentionally removed.
