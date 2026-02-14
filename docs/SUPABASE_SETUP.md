# Supabase setup

Use Supabase as the storage backend by switching env and creating the table once.

## 1. Create the table in Supabase

In the [Supabase Dashboard](https://supabase.com/dashboard): open your project → **SQL Editor** → **New query**, then run:

```sql
CREATE TABLE IF NOT EXISTS stock_data (
    ticker_symbol VARCHAR(20) PRIMARY KEY,
    stock_name VARCHAR(255) NOT NULL,
    stock_price DOUBLE PRECISION NOT NULL,
    stock_change DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_stock_data_created_at ON stock_data (created_at DESC);
```

Run the query. The table name must be `stock_data` (no spaces).

## 2. Enable Row Level Security (optional)

If you use the **service role** key (recommended for this scraper), RLS is bypassed. If you use the **anon** key, enable RLS and add policies as needed for the `stock_data` table.

## 3. Switch backend in `.env`

Set these in your `.env` (project root):

```bash
DB_BACKEND=supabase
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your_service_role_key
SUPABASE_TABLE=stock_data
```

- Use the **Project URL** from Supabase (Settings → API).
- Use the **service_role** key (Settings → API → Project API keys) so the scraper can insert/update.
- `SUPABASE_TABLE` must be exactly `stock_data` (the table created above).

## 4. Run the scraper

From the project root:

```bash
scrapy crawl afx_scraper
```

## Switching back to MongoDB or Postgres

Change only `DB_BACKEND` and the matching env vars:

- **MongoDB**: `DB_BACKEND=mongo` and set `MONGODB_URI`, `MONGODB_DATABASE`.
- **Postgres**: `DB_BACKEND=postgres` and set `SQL_DATABASE_URL`.

No code changes required.
