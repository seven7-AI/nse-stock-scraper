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

Run the StockAnalysis scraper:

```bash
scrapy crawl stockanalysis_scraper -o stockanalysis_output.jsonl
```

This outputs per-view records for `overview`, `performance`, `dividends`, `price`, and `profile`.

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

Set `DB_BACKEND` in `.env` to one of `mongo`, `postgres`, or `supabase`, and configure only the variables for that backend. For Supabase, create the `stock_data` table first; see [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md). For the StockAnalysis spider with Supabase, set `STOCKANALYSIS_TABLE=stockanalysis_stocks` and run the SQL in `sql/003_create_stockanalysis_stocks.sql`.

## Windows Daily Task (9:00 PM)

Use `scripts/daily_stock_job.ps1` to run both spiders daily on this Windows machine at 9 PM:
- `afx_scraper`
- `stockanalysis_scraper` (forced fresh run with `HTTPCACHE_ENABLED=False`)

The script:
- Runs both spiders using `.venv\Scripts\python.exe`
- Writes daily outputs under `reports/`
- Generates `reports/report-YYYY-MM-DD.txt` and `reports/latest-report.txt`
- Commits and pushes report/run artifacts with:
  - `chore(report): daily afx+stockanalysis run YYYY-MM-DD`
- Opens the report in Notepad only when an interactive desktop session exists

### Prerequisites

- A virtual environment exists in one of: `.venv`, `env`, or `venv`
- `.env` contains valid backend credentials (for Supabase, include `SUPABASE_URL`, `SUPABASE_KEY`, `STOCKANALYSIS_TABLE`)
- Git is authenticated for non-interactive push (for example, Git Credential Manager or PAT configured)

### Manual Dry Run

From project root:

```powershell
# First run on a new machine/venv (installs requirements if needed)
powershell -ExecutionPolicy Bypass -File ".\scripts\daily_stock_job.ps1" -BootstrapDeps

# Normal run
powershell -ExecutionPolicy Bypass -File ".\scripts\daily_stock_job.ps1"
```

Optional flags:

```powershell
# Skip opening Notepad
powershell -ExecutionPolicy Bypass -File ".\scripts\daily_stock_job.ps1" -NoNotepad

# Run and commit locally but skip push
powershell -ExecutionPolicy Bypass -File ".\scripts\daily_stock_job.ps1" -NoGitPush
```

### Register Scheduled Task (Run Whether Logged In Or Not)

**First, delete the existing task if it has issues:**
```powershell
schtasks /Delete /TN "NSE-Daily-Scrapers-9PM" /F
```

**Then create it properly using PowerShell (Run as Administrator):**
```powershell
$batchFile = "D:\2026 Projects\nse-stock-scraper\scripts\run_daily_job.bat"
$action = New-ScheduledTaskAction -Execute $batchFile -WorkingDirectory "D:\2026 Projects\nse-stock-scraper"
$trigger = New-ScheduledTaskTrigger -Daily -At "21:00"
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "NSE-Daily-Scrapers-9PM" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Daily stock scraper run at 9 PM"
```

**Alternative using schtasks (if PowerShell method doesn't work):**
```powershell
$batchFile = "D:\2026 Projects\nse-stock-scraper\scripts\run_daily_job.bat"
schtasks /Create /TN "NSE-Daily-Scrapers-9PM" /SC DAILY /ST 21:00 /TR "$batchFile" /RL HIGHEST /F /RU "SYSTEM" /RP ""
```

**Note:** The task is configured for 9 PM (21:00). To change the time, modify `-At "21:00"` or `/ST 21:00` (use 24-hour format).

### Verify

- `schtasks /Query /TN "NSE-Daily-Scrapers-9PM" /V /FO LIST`
- Confirm latest report exists in `reports/`
- Confirm commit and push completed on `origin/main`
- Confirm task result is `0x0` for successful runs

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

