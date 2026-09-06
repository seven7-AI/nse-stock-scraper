-- Canonical SQLite schema for the NSE scraper (DB_BACKEND=sqlite).
--
-- This file is documentation and a test reference. The runtime does NOT read it:
-- SQLiteBackend._create_schema() in nse_scraper/db/backends.py issues the same statements
-- on every open(), so a fresh database is created automatically and the Docker image
-- needs no extra files. tests/test_sqlite_backend.py asserts the two stay in step.
--
-- Differences from the Postgres/Supabase schema in sql/001 and sql/003, and why:
--   * JSONB          -> TEXT holding JSON. SQLite has no JSONB type; the JSON1 functions
--                       (json_extract, json_array_length) work on TEXT, so queries are
--                       equivalent. GIN indexes have no SQLite counterpart and are dropped.
--   * TIMESTAMPTZ    -> TEXT holding ISO-8601. This is what was already being stored:
--                       the application has always written .isoformat() strings.
--   * updated_at     -> set by the application in the ON CONFLICT DO UPDATE clause rather
--                       than by a trigger, avoiding recursive-update surprises.
--   * DOUBLE PRECISION -> REAL (SQLite REAL is a 64-bit IEEE float, same precision).
--
-- One row per ticker_symbol. Never migrate this to a row-per-scrape model: history lives
-- in the price_history JSON array, appended only when price or change actually moves.

CREATE TABLE IF NOT EXISTS stock_data (
    ticker_symbol TEXT PRIMARY KEY,
    stock_name    TEXT NOT NULL,
    stock_price   REAL NOT NULL,
    stock_change  REAL,
    scraped_at    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    price_history TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS ix_stock_data_scraped_at ON stock_data (scraped_at DESC);

CREATE TABLE IF NOT EXISTS stockanalysis_stocks (
    ticker_symbol       TEXT PRIMARY KEY,
    company_name        TEXT NOT NULL,
    rank                INTEGER,
    stock_price         REAL,
    stock_change        REAL,
    scraped_at          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    overview_metrics    TEXT,
    performance_metrics TEXT,
    dividends_metrics   TEXT,
    price_metrics       TEXT,
    profile_metrics     TEXT,
    price_history       TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_scraped_at ON stockanalysis_stocks (scraped_at DESC);
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_rank       ON stockanalysis_stocks (rank);
