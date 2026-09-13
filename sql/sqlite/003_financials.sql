-- Financial statements and daily fundamentals snapshots: append-only, point-in-time.
--
-- Like 002_canonical.sql this file is documentation and a test reference. The runtime
-- does NOT read it: SQLiteBackend._create_schema() executes FINANCIALS_SCHEMA_SQL from
-- nse_scraper/db/canonical_schema.py on every open(), and
-- alembic/versions/20260913_0003_financial_statements.py carries the same DDL as a
-- reversible migration. tests/test_sqlite_backend.py asserts all three stay in step.
--
-- financial_statements
--   One row per (ticker, statement, period type, period end, line item, DISPLAYED VALUE).
--   Source: stockanalysis.com /financials/{income-statement,balance-sheet,
--   cash-flow-statement,ratios}/ (annual and ?p=quarterly). Values are stored exactly as
--   displayed (`value_raw`) plus a parsed `value` and a `unit` (millions_kes, kes for
--   per-share rows, percent, ratio, millions for share counts); nothing is scaled here.
--   Because the displayed value is part of the unique key, a restated figure is a NEW
--   row with its own first_seen_at and the earlier row is kept: an analysis "as of"
--   a date can be limited to rows with first_seen_at <= that date. Re-scraping an
--   unchanged page only refreshes last_seen_at.
--
-- fundamental_snapshots
--   The per-view metric JSON (overview / performance / dividends / price / profile)
--   captured once per ticker per calendar day. stockanalysis_stocks keeps only the
--   latest values; this table is what gives market cap, yield and payout a history.
--
-- Nothing here is dropped or altered. The migration is purely additive.
CREATE TABLE IF NOT EXISTS financial_statements (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_symbol      TEXT NOT NULL REFERENCES instruments (ticker_symbol),
    source_ticker      TEXT NOT NULL,
    statement          TEXT NOT NULL,
    period_type        TEXT NOT NULL,
    fiscal_period_end  TEXT NOT NULL,
    fiscal_label       TEXT NOT NULL,
    line_item          TEXT NOT NULL,
    label              TEXT NOT NULL,
    row_key            TEXT,
    value              REAL,
    value_raw          TEXT NOT NULL,
    unit               TEXT NOT NULL,
    currency           TEXT NOT NULL DEFAULT 'KES',
    data_source        TEXT NOT NULL DEFAULT 'stockanalysis',
    source_url         TEXT NOT NULL,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    UNIQUE (ticker_symbol, statement, period_type, fiscal_period_end, line_item, value_raw)
);
CREATE INDEX IF NOT EXISTS ix_financial_statements_ticker_period
    ON financial_statements (ticker_symbol, statement, fiscal_period_end);
CREATE INDEX IF NOT EXISTS ix_financial_statements_first_seen
    ON financial_statements (first_seen_at);

CREATE TABLE IF NOT EXISTS fundamental_snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_symbol  TEXT NOT NULL REFERENCES instruments (ticker_symbol),
    source_ticker  TEXT NOT NULL,
    snapshot_date  TEXT NOT NULL,
    view           TEXT NOT NULL,
    metrics        TEXT NOT NULL,
    stock_price    REAL,
    scraped_at     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (ticker_symbol, snapshot_date, view)
);
CREATE INDEX IF NOT EXISTS ix_fundamental_snapshots_ticker_date
    ON fundamental_snapshots (ticker_symbol, snapshot_date DESC);
