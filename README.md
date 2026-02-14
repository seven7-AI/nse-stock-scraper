# Daily Stock Price Scraper

📚 **[Documentation Index](docs/INDEX.md)** | 🚀 **[Quick Start](docs/QUICKSTART.md)** | 🐳 **[Docker Guide](docs/DOCKER.md)** | 📋 **[Project Structure](docs/PROJECT_STRUCTURE.md)**

## Overview

This project uses Scrapy to extract live stock prices from the Nairobi Securities Exchange source at [AFX](https://afx.kwayisi.org/nse/).

It supports three storage backends with the same logical schema:
- MongoDB (default)
- PostgreSQL (SQLAlchemy + Alembic)
- Supabase (PostgREST client)

The common stock record shape is:
- `ticker_symbol` (unique identifier)
- `stock_name`
- `stock_price`
- `stock_change`
- `created_at`

## Prerequisites

- Python 3.11+ and `pip`
- One configured backend:
  - MongoDB URI, or
  - PostgreSQL connection URL, or
  - Supabase URL + service role key

## Installation

```bash
git clone https://github.com/KenMwaura1/nse-stock-scraper
cd nse-stock-scraper
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy and edit an env template from the project root:

```bash
cp config/.env.example .env
```

Required variables depend on your backend:

- `DB_BACKEND` - `mongo`, `postgres`, or `supabase`
- `STOCK_TABLE` - logical table/collection name (default `stock_data`)

MongoDB mode:
- `MONGODB_URI`
- `MONGODB_DATABASE`

PostgreSQL mode:
- `SQL_DATABASE_URL` (example: `postgresql+psycopg2://postgres:postgres@localhost:5432/nse_data`)
- `SQL_ECHO` (`true`/`false`)

Supabase mode:
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_TABLE`

## Running the Scraper

From the project root:

```bash
scrapy crawl afx_scraper
```

Preview as JSON:

```bash
scrapy crawl afx_scraper -o test.json
```

## Database Migrations (PostgreSQL)

Alembic is included for PostgreSQL schema management.

```bash
# uses SQL_DATABASE_URL from environment when set
alembic upgrade head
```

Included SQL scripts:
- `sql/001_create_stock_data.sql`
- `sql/002_upsert_stock_data.sql`

## Placeholder Utility (No Messaging)

`nse_scraper/stock_notification.py` is kept as a non-sending placeholder utility.
It queries the selected backend and logs threshold checks only. No SMS integration and no scheduler integration are included.

Run it manually:

```bash
python nse_scraper/stock_notification.py
```

## Switching backends

Set `DB_BACKEND` in `.env` to one of `mongo`, `postgres`, or `supabase`, and configure only the variables for that backend. For Supabase, create the `stock_data` table first; see [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md).

## Docker

Use the Docker template:

```bash
cp config/.env.docker .env
docker-compose up --build
```

Docker compose includes:
- `mongodb` service
- `postgres` service
- `scraper` service

Select backend via `DB_BACKEND` in `.env`.

## Troubleshooting

### Backend connection issues
- Ensure backend-specific env vars are set
- Verify credentials, host, and ports
- For MongoDB Atlas, allow your IP in network access

### Scraper parsing issues
- Run with debug logs:
  - `scrapy crawl afx_scraper --loglevel=DEBUG`
- Verify selectors against the current AFX HTML

### PostgreSQL migration issues
- Confirm `SQL_DATABASE_URL` is valid
- Run `alembic current` and `alembic history`

## License

[MIT](https://choosealicense.com/licenses/mit/)

