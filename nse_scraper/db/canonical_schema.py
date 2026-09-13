"""DDL for the canonical stock-observation and fundamentals tables.

Lives in the package (not under sql/) because the Docker image does not ship sql/;
``SQLiteBackend._create_schema()`` executes this on every open() so a fresh database is
complete without any extra files. ``sql/sqlite/002_canonical.sql`` is the human-readable
copy and ``alembic/versions/20260912_0002_canonical_observations.py`` the reversible
migration; ``tests/test_sqlite_backend.py`` asserts all three describe the same tables.

Design notes are in sql/sqlite/002_canonical.sql and docs/CANONICAL_SCHEMA.md.
"""

CANONICAL_TABLES = (
    "instruments",
    "instrument_aliases",
    "stock_observations",
    "stock_observation_conflicts",
    "import_runs",
)

CANONICAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS instruments (
    ticker_symbol    TEXT PRIMARY KEY,
    company_name     TEXT NOT NULL,
    instrument_type  TEXT NOT NULL DEFAULT 'ordinary',
    parent_ticker    TEXT,
    sector           TEXT,
    sector_source    TEXT,
    first_seen_date  TEXT,
    last_seen_date   TEXT,
    is_active        INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_instruments_sector ON instruments (sector);
CREATE INDEX IF NOT EXISTS ix_instruments_type   ON instruments (instrument_type);

CREATE TABLE IF NOT EXISTS instrument_aliases (
    source_ticker    TEXT PRIMARY KEY,
    canonical_ticker TEXT NOT NULL REFERENCES instruments (ticker_symbol),
    reason           TEXT NOT NULL,
    evidence         TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_symbol    TEXT NOT NULL REFERENCES instruments (ticker_symbol),
    trade_date       TEXT NOT NULL,
    source_ticker    TEXT NOT NULL,
    company_name     TEXT,
    close_price      REAL NOT NULL,
    previous_close   REAL,
    day_low          REAL,
    day_high         REAL,
    year_low         REAL,
    year_high        REAL,
    change_abs       REAL,
    change_pct       REAL,
    volume           INTEGER,
    adjusted_price   REAL,
    data_source      TEXT NOT NULL,
    source_file      TEXT,
    source_row       INTEGER,
    source_date_raw  TEXT,
    quality_flags    TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (ticker_symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_stock_observations_trade_date  ON stock_observations (trade_date);
CREATE INDEX IF NOT EXISTS ix_stock_observations_ticker_date ON stock_observations (ticker_symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS ix_stock_observations_source      ON stock_observations (data_source);

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
"""

# --- fundamentals (2026-09-13) -------------------------------------------------------
# Financial statements and the daily fundamentals snapshot. Both are APPEND-ONLY and
# point-in-time: a value is stored with the moment it was first seen and is never
# updated in place, so an analysis "as of" a past date can be limited to what was
# actually known then. sql/sqlite/003_financials.sql is the human-readable copy and
# alembic/versions/20260913_0003_financial_statements.py the reversible migration;
# tests/test_sqlite_backend.py asserts all three describe the same tables.

FINANCIALS_TABLES = (
    "financial_statements",
    "fundamental_snapshots",
)

FINANCIALS_SCHEMA_SQL = """
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
"""
