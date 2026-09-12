-- Canonical stock observations: one row per (ticker, trading day), 2007 -> today.
--
-- Like 001_schema.sql this file is documentation and a test reference. The runtime
-- does NOT read it: SQLiteBackend._create_schema() issues the same statements on every
-- open(), and alembic/versions/20260912_0002_canonical_observations.py carries the
-- same DDL as a reversible migration. tests/test_sqlite_backend.py asserts all three
-- stay in step.
--
-- Why a new table rather than altering stock_data / stockanalysis_stocks:
--   * those two are keyed on ticker_symbol alone -- one row per ticker, history
--     compressed into a price_history JSON array. nse-be reads that shape today and it
--     keeps working untouched;
--   * a timeline needs (ticker, date) as its identity, which is a different table, not
--     a different primary key on the same one.
--
-- Nothing here is dropped or altered. The migration is purely additive.

-- Reference data: one row per instrument, keyed on the CANONICAL ticker (ABSA, not BBK).
CREATE TABLE IF NOT EXISTS instruments (
    ticker_symbol    TEXT PRIMARY KEY,
    company_name     TEXT NOT NULL,
    -- ordinary | preference | rights | index | etf | reit
    instrument_type  TEXT NOT NULL DEFAULT 'ordinary',
    -- KPLC for KPLC-P4 / KPLC-P7 / KPLC-R; NULL for an ordinary share
    parent_ticker    TEXT,
    -- Official NSE sector label. NULL means "no source classifies it" -- never a guess.
    sector           TEXT,
    -- Which sector file supplied the label, e.g. 'NSE_data_stock_market_sectors_2022.csv'
    sector_source    TEXT,
    first_seen_date  TEXT,
    last_seen_date   TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_instruments_sector ON instruments (sector);
CREATE INDEX IF NOT EXISTS ix_instruments_type   ON instruments (instrument_type);

-- Ticker lineage: what a source called an instrument -> what we call it.
-- Every alias carries the evidence that justified it.
CREATE TABLE IF NOT EXISTS instrument_aliases (
    source_ticker    TEXT PRIMARY KEY,
    canonical_ticker TEXT NOT NULL REFERENCES instruments (ticker_symbol),
    -- rebrand | merger | listing_code_change
    reason           TEXT NOT NULL,
    evidence         TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

-- THE SOURCE OF TRUTH. One row per canonical ticker per trading day.
CREATE TABLE IF NOT EXISTS stock_observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_symbol    TEXT NOT NULL REFERENCES instruments (ticker_symbol),
    trade_date       TEXT NOT NULL,                 -- ISO-8601 date
    source_ticker    TEXT NOT NULL,                 -- exactly what the source said (BBK)
    company_name     TEXT,                          -- as the source spelled it that day
    close_price      REAL NOT NULL,
    previous_close   REAL,
    day_low          REAL,
    day_high         REAL,
    year_low         REAL,                          -- archive "12m Low"  / scraper low52
    year_high        REAL,                          -- archive "12m High" / scraper high52
    change_abs       REAL,                          -- sign preserved
    change_pct       REAL,                          -- stored as given, never recomputed
    volume           INTEGER,
    adjusted_price   REAL,                          -- archive "Adjust", semantics undocumented
    -- nse_archive:2009 | nse_scraper
    data_source      TEXT NOT NULL,
    source_file      TEXT,
    source_row       INTEGER,
    -- The date string as it appeared in the source. Differs from trade_date only on
    -- rows that were repaired, so a repair is always auditable.
    source_date_raw  TEXT,
    -- JSON array of strings: date_repaired, volume_missing, change_missing, ...
    quality_flags    TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (ticker_symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_stock_observations_trade_date  ON stock_observations (trade_date);
CREATE INDEX IF NOT EXISTS ix_stock_observations_ticker_date ON stock_observations (ticker_symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS ix_stock_observations_source      ON stock_observations (data_source);

-- Rows that could not be stored without overwriting an existing observation for the
-- same (ticker, trade_date) and could not be attributed to another date. Nothing is
-- silently discarded: it lands here with the reason and a pointer to the row kept.
CREATE TABLE IF NOT EXISTS stock_observation_conflicts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_symbol        TEXT NOT NULL,
    trade_date           TEXT NOT NULL,
    source_ticker        TEXT NOT NULL,
    company_name         TEXT,
    close_price          REAL,
    previous_close       REAL,
    day_low              REAL,
    day_high             REAL,
    year_low             REAL,
    year_high            REAL,
    change_abs           REAL,
    change_pct           REAL,
    volume               INTEGER,
    adjusted_price       REAL,
    data_source          TEXT NOT NULL,
    source_file          TEXT,
    source_row           INTEGER,
    source_date_raw      TEXT,
    conflict_reason      TEXT NOT NULL,
    kept_observation_id  INTEGER REFERENCES stock_observations (id),
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_observation_conflicts_ticker_date ON stock_observation_conflicts (ticker_symbol, trade_date);
-- A conflict is identified by the exact source line, so re-running the import
-- re-detects the same 69 rows and inserts nothing.
CREATE UNIQUE INDEX IF NOT EXISTS ux_observation_conflicts_source ON stock_observation_conflicts (source_file, source_row);

-- One row per import invocation per source file, so idempotency is auditable: the
-- second run of the same file reports rows_already_present == rows_read.
CREATE TABLE IF NOT EXISTS import_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    data_source           TEXT NOT NULL,
    source_file           TEXT NOT NULL,
    file_sha256           TEXT NOT NULL,
    started_at            TEXT NOT NULL,
    finished_at           TEXT,
    rows_read             INTEGER NOT NULL DEFAULT 0,
    rows_inserted         INTEGER NOT NULL DEFAULT 0,
    rows_already_present  INTEGER NOT NULL DEFAULT 0,
    rows_quarantined      INTEGER NOT NULL DEFAULT 0,
    rows_rejected         INTEGER NOT NULL DEFAULT 0,
    notes                 TEXT
);
CREATE INDEX IF NOT EXISTS ix_import_runs_file ON import_runs (source_file, started_at DESC);
