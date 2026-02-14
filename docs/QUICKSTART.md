# Quick Start

## 1) Install dependencies

```bash
pip install -r requirements.txt
```

## 2) Configure environment

```bash
cp config/.env.example .env
```

Set `DB_BACKEND` to one of:
- `mongo`
- `postgres`
- `supabase`

Then fill only the vars needed for the selected backend.

## 3) Run the scraper

```bash
scrapy crawl afx_scraper
```

Optional JSON preview:

```bash
scrapy crawl afx_scraper -o test.json
```

## 4) PostgreSQL migrations (optional)

When using `DB_BACKEND=postgres`:

```bash
alembic upgrade head
```

## 5) Manual placeholder utility

`stock_notification.py` is now a non-sending placeholder helper that reads latest stock data and logs threshold checks.

```bash
python nse_scraper/stock_notification.py
```

## Useful checks

```bash
# Scrapy debug logs
scrapy crawl afx_scraper --loglevel=DEBUG

# Run tests
make test
```
