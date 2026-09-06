import logging
from datetime import datetime, timezone
import json
import os
import re
import sqlite3

logger = logging.getLogger(__name__)

# The five per-view JSONB/JSON columns on stockanalysis_stocks. Order matters only for
# readability; membership is what the omit-rather-than-null rule keys on.
METRICS_COLUMNS = (
    "overview_metrics",
    "performance_metrics",
    "dividends_metrics",
    "price_metrics",
    "profile_metrics",
)

# Backends create_backend() accepts. Callers that need to decide whether storage is
# possible at all (the pipelines, and the stockanalysis spider's pipeline switch) test
# against this rather than hardcoding a backend name -- hardcoding "supabase" is what
# would have silently disabled storage the moment the default changed.
SUPPORTED_BACKENDS = ("sqlite", "supabase")

# Table names come from configuration and cannot be bound as SQL parameters, so they are
# validated instead of trusted.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_record(record):
    normalized = dict(record)
    created_at = normalized.get("created_at")
    if created_at is None:
        normalized["created_at"] = datetime.now(timezone.utc)
    elif isinstance(created_at, datetime) and created_at.tzinfo is None:
        normalized["created_at"] = created_at.replace(tzinfo=timezone.utc)
    # Ensure scraped_at exists for historical tracking
    scraped_at = normalized.get("scraped_at")
    if scraped_at is None:
        normalized["scraped_at"] = normalized["created_at"]
    elif isinstance(scraped_at, datetime) and scraped_at.tzinfo is None:
        normalized["scraped_at"] = scraped_at.replace(tzinfo=timezone.utc)
    return normalized


def _iso(value):
    """ISO-8601 string for a datetime, or the value unchanged if it is already text."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _float_or_none(value):
    return float(value) if value is not None else None


def _quote_identifier(name):
    if not _IDENTIFIER_RE.match(name or ""):
        raise ValueError("Unsafe SQL identifier: {!r}".format(name))
    return '"{}"'.format(name)


class _BaseBackend:
    """Behaviour shared by every storage backend.

    The local JSONL fallback and the price-history append rule are storage-agnostic: they
    are what let a failed write stay replayable and what keeps one row per ticker from
    turning into a row per scrape. Both backends use these rather than each carrying a
    copy that could drift.
    """

    # Local fallback directory for failed writes (relative to CWD).
    local_fallback_dir = "reports/local_fallback"

    def _ensure_local_dir(self):
        if not self.local_fallback_dir:
            return
        try:
            os.makedirs(self.local_fallback_dir, exist_ok=True)
        except Exception:
            logger.exception("Failed to create local fallback directory %s", self.local_fallback_dir)

    def _write_local_fallback(self, kind, payload):
        """Write a failed payload to local JSONL for later inspection/replay."""
        if not self.local_fallback_dir:
            return
        self._ensure_local_dir()
        try:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filename = f"{kind}_fallback-{date_str}.jsonl"
            path = os.path.join(self.local_fallback_dir, filename)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, default=str) + "\n")
        except Exception:
            logger.exception("Failed to write local fallback record for %s", kind)

    @staticmethod
    def _extend_price_history(price_history, scraped_at, stock_price, stock_change):
        """Append one observation, but only when price or change actually moved.

        This is what makes price_history a change log rather than a row-per-scrape series:
        a ticker that does not move for a week gets one entry, not seven.
        """
        entry = {
            "scraped_at": scraped_at,
            "stock_price": _float_or_none(stock_price),
            "stock_change": _float_or_none(stock_change),
        }
        if not isinstance(price_history, list):
            price_history = []
        if (
            not price_history
            or price_history[-1].get("stock_price") != entry["stock_price"]
            or price_history[-1].get("stock_change") != entry["stock_change"]
        ):
            price_history.append(entry)
        return price_history


class SupabaseBackend(_BaseBackend):
    def __init__(self, supabase_url, supabase_key, supabase_table, stockanalysis_table="stockanalysis_stocks"):
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY are required when DB_BACKEND=supabase")
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.supabase_table = supabase_table
        self.stockanalysis_table = stockanalysis_table
        self.client = None

    def open(self):
        from supabase import create_client

        self.client = create_client(self.supabase_url, self.supabase_key)
        logger.info("Supabase backend ready")

    def close(self):
        return None

    def upsert_stockanalysis_stock(self, record):
        """Upsert one normalized stock record (all tab data) into stockanalysis_stocks, updating existing records."""
        scraped_at = record.get("scraped_at")
        if scraped_at is None:
            scraped_at = datetime.now(timezone.utc)
        scraped_at = _iso(scraped_at)

        # Get existing record to preserve price_history
        existing = None
        try:
            response = self.client.table(self.stockanalysis_table).select("price_history, stock_price, stock_change").eq("ticker_symbol", record["ticker_symbol"]).execute()
            if response.data:
                existing = response.data[0]
        except Exception:
            existing = None

        price_history = self._extend_price_history(
            existing.get("price_history", []) if existing else [],
            scraped_at,
            record.get("stock_price"),
            record.get("stock_change"),
        )

        payload = {
            "ticker_symbol": record["ticker_symbol"],
            "company_name": record["company_name"],
            "rank": record.get("rank"),
            "stock_price": _float_or_none(record.get("stock_price")),
            "stock_change": _float_or_none(record.get("stock_change")),
            "scraped_at": scraped_at,
            "overview_metrics": record.get("overview_metrics"),
            "performance_metrics": record.get("performance_metrics"),
            "dividends_metrics": record.get("dividends_metrics"),
            "price_metrics": record.get("price_metrics"),
            "profile_metrics": record.get("profile_metrics"),
            "price_history": price_history,
        }
        # A view we did not scrape must not erase what was stored last time. An
        # omitted key is left untouched by the ON CONFLICT UPDATE, whereas sending
        # None writes a NULL -- which is how the four views lost to the retired
        # screener API were being blanked on every run.
        for metrics_key in METRICS_COLUMNS:
            if payload[metrics_key] is None:
                del payload[metrics_key]
        # Use upsert to update existing records or insert new ones.
        # On Supabase failure, write a local fallback record. Returns True when the
        # row actually reached Supabase so callers can distinguish a healthy write
        # from a silent fallback (see nse_scraper/extensions.py).
        try:
            self.client.table(self.stockanalysis_table).upsert(payload, on_conflict="ticker_symbol").execute()
            return True
        except Exception:
            logger.exception("Supabase upsert_stockanalysis_stock failed; writing local fallback")
            self._write_local_fallback("stockanalysis_stocks", payload)
            return False

    def upsert_stock(self, record):
        payload = _normalize_record(record)
        scraped_at = payload.get("scraped_at")
        if scraped_at is None:
            scraped_at = payload.get("created_at", datetime.now(timezone.utc))
        scraped_at_iso = _iso(scraped_at)

        # Get existing record to preserve price_history
        existing = None
        try:
            response = self.client.table(self.supabase_table).select("price_history, stock_price, stock_change").eq("ticker_symbol", payload["ticker_symbol"]).execute()
            if response.data:
                existing = response.data[0]
        except Exception:
            existing = None

        price_history = self._extend_price_history(
            existing.get("price_history", []) if existing else [],
            scraped_at_iso,
            payload["stock_price"],
            payload.get("stock_change"),
        )

        serialized = {
            "ticker_symbol": payload["ticker_symbol"],
            "stock_name": payload["stock_name"],
            "stock_price": float(payload["stock_price"]),
            "stock_change": _float_or_none(payload.get("stock_change")),
            "scraped_at": scraped_at_iso,
            "created_at": _iso(payload["created_at"]),
            "price_history": price_history,
        }
        # Use upsert to update existing records or insert new ones.
        # On Supabase failure, write a local fallback record. Returns True when the
        # row actually reached Supabase so callers can distinguish a healthy write
        # from a silent fallback (see nse_scraper/extensions.py).
        try:
            self.client.table(self.supabase_table).upsert(serialized, on_conflict="ticker_symbol").execute()
            return True
        except Exception:
            logger.exception("Supabase upsert_stock failed; writing local fallback")
            self._write_local_fallback("stock_data", serialized)
            return False

    def get_latest_by_ticker(self, ticker_symbol):
        response = (
            self.client.table(self.supabase_table)
            .select("ticker_symbol,stock_name,stock_price,stock_change,created_at")
            .eq("ticker_symbol", ticker_symbol)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]


class SQLiteBackend(_BaseBackend):
    """Local SQLite storage, the runtime replacement for Supabase.

    Preserves the four behaviours the Supabase backend was relied on for: one row per
    ticker, price_history that appends only on a real move, an unscraped view never
    blanking a stored column, and a replayable JSONL record of any failed write.

    JSON columns are stored as TEXT and stay queryable through SQLite's JSON1 functions
    (``json_extract``, ``json_array_length``).
    """

    def __init__(self, db_path, stock_table="stock_data", stockanalysis_table="stockanalysis_stocks"):
        if not db_path:
            raise ValueError("SQLITE_DB_PATH is required when DB_BACKEND=sqlite")
        self.db_path = db_path
        self.stock_table = stock_table
        self.stockanalysis_table = stockanalysis_table
        # Validate early so a bad table name fails at construction, not mid-crawl.
        self._stock_sql = _quote_identifier(stock_table)
        self._stockanalysis_sql = _quote_identifier(stockanalysis_table)
        self.connection = None

    def open(self):
        directory = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(directory, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        # WAL keeps a reader from blocking the writer and survives an unclean exit far
        # better than the rollback journal -- worth it for a file on a bind mount.
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()
        logger.info("SQLite backend ready: %s", self.db_path)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _create_schema(self):
        """Create tables and indexes if they are absent. Safe to run on every open."""
        # executescript() commits any pending transaction before it runs, so it is called
        # directly rather than inside a `with connection` block.
        self.connection.executescript(
            """
                CREATE TABLE IF NOT EXISTS {stock} (
                    ticker_symbol TEXT PRIMARY KEY,
                    stock_name    TEXT NOT NULL,
                    stock_price   REAL NOT NULL,
                    stock_change  REAL,
                    scraped_at    TEXT NOT NULL,
                    created_at    TEXT NOT NULL,
                    price_history TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS ix_{stock_name}_scraped_at
                    ON {stock} (scraped_at DESC);

                CREATE TABLE IF NOT EXISTS {sa} (
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
                CREATE INDEX IF NOT EXISTS ix_{sa_name}_scraped_at
                    ON {sa} (scraped_at DESC);
                CREATE INDEX IF NOT EXISTS ix_{sa_name}_rank
                    ON {sa} (rank);
            """.format(
                stock=self._stock_sql,
                stock_name=self.stock_table,
                sa=self._stockanalysis_sql,
                sa_name=self.stockanalysis_table,
            )
        )
        self.connection.commit()

    def _existing_price_history(self, table_sql, ticker_symbol):
        row = self.connection.execute(
            "SELECT price_history FROM {} WHERE ticker_symbol = ?".format(table_sql),
            (ticker_symbol,),
        ).fetchone()
        if row is None:
            return []
        try:
            history = json.loads(row["price_history"] or "[]")
        except (TypeError, ValueError):
            return []
        return history if isinstance(history, list) else []

    def _upsert(self, table_sql, payload, json_columns, immutable_on_update=()):
        """INSERT ... ON CONFLICT DO UPDATE, built from the keys actually present.

        Columns missing from ``payload`` appear in neither the INSERT nor the UPDATE SET,
        which is how a view that was not scraped this run keeps the value stored last run.
        Sending an explicit None instead would write NULL and blank it -- the exact bug
        that silently emptied four views for weeks under the previous backend.
        """
        columns = list(payload)
        placeholders = ", ".join("?" for _ in columns)
        values = [
            json.dumps(payload[column]) if column in json_columns else payload[column]
            for column in columns
        ]
        updatable = [
            column
            for column in columns
            if column != "ticker_symbol" and column not in immutable_on_update
        ]
        assignments = ", ".join('"{0}" = excluded."{0}"'.format(c) for c in updatable)
        statement = 'INSERT INTO {table} ({cols}) VALUES ({vals}) ON CONFLICT(ticker_symbol) DO UPDATE SET {sets}'.format(
            table=table_sql,
            cols=", ".join('"{}"'.format(c) for c in columns),
            vals=placeholders,
            sets=assignments,
        )
        with self.connection as connection:
            connection.execute(statement, values)

    def upsert_stockanalysis_stock(self, record):
        """Upsert one normalized stock record (all tab data) into stockanalysis_stocks."""
        scraped_at = record.get("scraped_at")
        if scraped_at is None:
            scraped_at = datetime.now(timezone.utc)
        scraped_at = _iso(scraped_at)
        now_iso = datetime.now(timezone.utc).isoformat()

        payload = None
        try:
            price_history = self._extend_price_history(
                self._existing_price_history(self._stockanalysis_sql, record["ticker_symbol"]),
                scraped_at,
                record.get("stock_price"),
                record.get("stock_change"),
            )
            payload = {
                "ticker_symbol": record["ticker_symbol"],
                "company_name": record["company_name"],
                "rank": record.get("rank"),
                "stock_price": _float_or_none(record.get("stock_price")),
                "stock_change": _float_or_none(record.get("stock_change")),
                "scraped_at": scraped_at,
                "overview_metrics": record.get("overview_metrics"),
                "performance_metrics": record.get("performance_metrics"),
                "dividends_metrics": record.get("dividends_metrics"),
                "price_metrics": record.get("price_metrics"),
                "profile_metrics": record.get("profile_metrics"),
                "price_history": price_history,
            }
            # See _upsert: an absent key is preserved, an explicit None would blank it.
            for metrics_key in METRICS_COLUMNS:
                if payload[metrics_key] is None:
                    del payload[metrics_key]

            # created_at records first sight and is never rewritten; updated_at moves on
            # every write. This mirrors the Postgres DEFAULT NOW() column plus the
            # tr_stockanalysis_stocks_updated_at trigger it replaces.
            payload["created_at"] = now_iso
            payload["updated_at"] = now_iso
            self._upsert(
                self._stockanalysis_sql,
                payload,
                json_columns=METRICS_COLUMNS + ("price_history",),
                immutable_on_update=("created_at",),
            )
            return True
        except Exception:
            logger.exception("SQLite upsert_stockanalysis_stock failed; writing local fallback")
            if payload is not None:
                payload.pop("created_at", None)
                payload.pop("updated_at", None)
            self._write_local_fallback("stockanalysis_stocks", payload if payload is not None else dict(record))
            return False

    def upsert_stock(self, record):
        payload = _normalize_record(record)
        scraped_at = payload.get("scraped_at")
        if scraped_at is None:
            scraped_at = payload.get("created_at", datetime.now(timezone.utc))
        scraped_at_iso = _iso(scraped_at)

        serialized = None
        try:
            price_history = self._extend_price_history(
                self._existing_price_history(self._stock_sql, payload["ticker_symbol"]),
                scraped_at_iso,
                payload["stock_price"],
                payload.get("stock_change"),
            )
            serialized = {
                "ticker_symbol": payload["ticker_symbol"],
                "stock_name": payload["stock_name"],
                "stock_price": float(payload["stock_price"]),
                "stock_change": _float_or_none(payload.get("stock_change")),
                "scraped_at": scraped_at_iso,
                "created_at": _iso(payload["created_at"]),
                "price_history": price_history,
            }
            # created_at is refreshed on conflict here, matching what the Supabase upsert
            # did: it sent created_at in the payload, so ON CONFLICT UPDATE overwrote it.
            self._upsert(
                self._stock_sql,
                serialized,
                json_columns=("price_history",),
            )
            return True
        except Exception:
            logger.exception("SQLite upsert_stock failed; writing local fallback")
            self._write_local_fallback("stock_data", serialized if serialized is not None else dict(payload))
            return False

    def get_latest_by_ticker(self, ticker_symbol):
        row = self.connection.execute(
            "SELECT ticker_symbol, stock_name, stock_price, stock_change, created_at "
            "FROM {} WHERE ticker_symbol = ?".format(self._stock_sql),
            (ticker_symbol,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)


def create_backend(
    backend_name,
    stock_table="stock_data",
    supabase_url=None,
    supabase_key=None,
    supabase_table="stock_data",
    stockanalysis_table="stockanalysis_stocks",
    sqlite_path=None,
):
    backend = (backend_name or "").strip().lower()
    if backend == "sqlite":
        return SQLiteBackend(
            db_path=sqlite_path,
            stock_table=stock_table,
            stockanalysis_table=stockanalysis_table,
        )
    if backend == "supabase":
        return SupabaseBackend(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            supabase_table=supabase_table,
            stockanalysis_table=stockanalysis_table,
        )
    raise ValueError("Unsupported DB_BACKEND. Use: sqlite, supabase")
