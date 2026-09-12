"""Idempotent load of the yearly archive into the canonical tables.

Idempotency comes from the schema, not from bookkeeping: stock_observations is UNIQUE on
(ticker_symbol, trade_date) and every insert is INSERT OR IGNORE. A second run of the
same file therefore inserts nothing and reports rows_already_present == rows_read.

Nothing is silently dropped:
  * a row that cannot be stored at all (no ticker, no date, no price) is counted as
    rejected and its reason kept on the import_runs row;
  * a row whose (ticker, date) already exists with a DIFFERENT close price is written to
    stock_observation_conflicts with a pointer to the row that was kept.
"""

import json
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

from nse_scraper.db.canonical_schema import CANONICAL_SCHEMA_SQL
from nse_scraper.historical import lineage, normalize, readers, sectors
from nse_scraper.historical.repairs import DateRepairer

logger = logging.getLogger(__name__)

ARCHIVE_SOURCE_PREFIX = "nse_archive"
BATCH_SIZE = 5000

OBSERVATION_COLUMNS = (
    "ticker_symbol", "trade_date", "source_ticker", "company_name",
    "close_price", "previous_close", "day_low", "day_high", "year_low", "year_high",
    "change_abs", "change_pct", "volume", "adjusted_price",
    "data_source", "source_file", "source_row", "source_date_raw", "quality_flags",
    "created_at", "updated_at",
)

_INSERT_OBSERVATION = (
    "INSERT OR IGNORE INTO stock_observations ({}) VALUES ({})".format(
        ", ".join(OBSERVATION_COLUMNS), ", ".join("?" for _ in OBSERVATION_COLUMNS)
    )
)

_INSERT_CONFLICT = """
    INSERT OR IGNORE INTO stock_observation_conflicts (
        ticker_symbol, trade_date, source_ticker, company_name,
        close_price, previous_close, day_low, day_high, year_low, year_high,
        change_abs, change_pct, volume, adjusted_price,
        data_source, source_file, source_row, source_date_raw,
        conflict_reason, kept_observation_id, created_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


class FileImportResult:
    def __init__(self, source_file):
        self.source_file = source_file
        self.rows_read = 0
        self.rows_inserted = 0
        self.rows_already_present = 0
        self.rows_quarantined = 0
        self.rows_rejected = 0
        self.rejections = Counter()
        self.repairs = Counter()
        self.flags = Counter()

    def as_dict(self):
        return {
            "source_file": self.source_file,
            "rows_read": self.rows_read,
            "rows_inserted": self.rows_inserted,
            "rows_already_present": self.rows_already_present,
            "rows_quarantined": self.rows_quarantined,
            "rows_rejected": self.rows_rejected,
            "rejections": dict(self.rejections),
            "repairs": dict(self.repairs),
            "flags": dict(self.flags),
        }


class HistoricalImporter:
    """Load NSE_data_all_stocks_*.csv into stock_observations, idempotently."""

    def __init__(self, db_path, archive_dir):
        self.db_path = db_path
        self.archive_dir = archive_dir
        self.connection = None
        self._dry_run = False

    def _commit(self):
        """Commit unless dry-running, in which case every write is rolled back at the end."""
        if not self._dry_run:
            self.connection.commit()

    # -- lifecycle ------------------------------------------------------------------
    def open(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(CANONICAL_SCHEMA_SQL)
        self.connection.commit()

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    # -- public ---------------------------------------------------------------------
    def run(self, years=None, dry_run=False):
        """Import every yearly file (or the given years). Returns a list of FileImportResult."""
        paths = readers.list_price_files(self.archive_dir)
        if years:
            wanted = set(years)
            paths = [p for p in paths if readers.year_of(p) in wanted]
        if not paths:
            raise FileNotFoundError("no NSE_data_all_stocks_*.csv under {}".format(self.archive_dir))

        self._dry_run = dry_run
        try:
            self._seed_aliases()
            self._seed_instruments(paths)
            results = [self._import_file(path, dry_run=dry_run) for path in paths]
            if not dry_run:
                self._refresh_instrument_spans()
        finally:
            if dry_run:
                # A dry run must leave the database byte-for-byte as it found it.
                self.connection.rollback()
            self._dry_run = False
        return results

    # -- reference data -------------------------------------------------------------
    def _seed_aliases(self):
        now = _now()
        for alias in lineage.TICKER_ALIASES:
            # The canonical instrument must exist before the FK is satisfied; a
            # placeholder name is refreshed from observations at the end of the run.
            self.connection.execute(
                "INSERT OR IGNORE INTO instruments (ticker_symbol, company_name, instrument_type, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (alias.canonical_ticker, alias.canonical_ticker,
                 lineage.classify(alias.canonical_ticker)[0], now, now),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO instrument_aliases "
                "(source_ticker, canonical_ticker, reason, evidence, created_at) VALUES (?,?,?,?,?)",
                (alias.source_ticker, alias.canonical_ticker, alias.reason, alias.evidence, now),
            )
        self._commit()

    def _seed_instruments(self, paths):
        """One instruments row per canonical ticker seen in the files, sector attached."""
        sector_map = sectors.build_sector_map(self.archive_dir)
        seen = set()
        latest_name = {}  # canonical -> (date, name)
        for path in paths:
            for raw in readers.read_price_file(path):
                code = normalize.normalize_ticker(raw.code)
                if not code:
                    continue
                canonical = lineage.resolve(code)
                seen.add(canonical)
                date = normalize.parse_date(raw.date_raw) or ""
                name = normalize.normalize_name(raw.name)
                if name and (canonical not in latest_name or date >= latest_name[canonical][0]):
                    latest_name[canonical] = (date, name)

        now = _now()
        for canonical in sorted(seen):
            instrument_type, parent = lineage.classify(canonical)
            name = latest_name.get(canonical, ("", ""))[1]
            if not name:
                # Five rights issues carry a blank NAME on every row. Derive from the
                # parent rather than store an empty name; the derivation is visible.
                parent_name = latest_name.get(parent, ("", ""))[1] if parent else ""
                name = "{} ({})".format(parent_name or parent or canonical, instrument_type)
            sector, sector_source = sector_map.get(canonical, (None, None))
            if sector is None and parent is not None:
                # Rights and preference shares carry their parent's sector.
                sector, sector_source = sector_map.get(parent, (None, None))
            self.connection.execute(
                "INSERT INTO instruments (ticker_symbol, company_name, instrument_type, parent_ticker, "
                "sector, sector_source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(ticker_symbol) DO UPDATE SET "
                "company_name = excluded.company_name, instrument_type = excluded.instrument_type, "
                "parent_ticker = excluded.parent_ticker, "
                "sector = COALESCE(excluded.sector, instruments.sector), "
                "sector_source = COALESCE(excluded.sector_source, instruments.sector_source), "
                "updated_at = excluded.updated_at",
                (canonical, name, instrument_type, parent, sector, sector_source, now, now),
            )
        self._commit()

    def _refresh_instrument_spans(self):
        self.connection.execute(
            "UPDATE instruments SET "
            "first_seen_date = (SELECT MIN(trade_date) FROM stock_observations o WHERE o.ticker_symbol = instruments.ticker_symbol), "
            "last_seen_date  = (SELECT MAX(trade_date) FROM stock_observations o WHERE o.ticker_symbol = instruments.ticker_symbol), "
            "updated_at = ?",
            (_now(),),
        )
        self._commit()

    # -- observations ---------------------------------------------------------------
    def _import_file(self, path, dry_run):
        result = FileImportResult(os.path.basename(path))
        year = readers.year_of(path)
        data_source = "{}:{}".format(ARCHIVE_SOURCE_PREFIX, year)
        run_id = None if dry_run else self._start_run(path, data_source)

        repairer = DateRepairer(result.source_file)
        seen_in_file = defaultdict(list)  # (ticker, date) -> [source_row, ...]
        now = _now()
        batch = []

        for raw in readers.read_price_file(path):
            result.rows_read += 1
            record = self._normalize(raw, year, data_source, repairer, result, now)
            if record is None:
                continue
            key = (record["ticker_symbol"], record["trade_date"])
            if key in seen_in_file:
                # Same (ticker, date) twice in one file: the first is kept, this one is
                # quarantined once the batch holding the first has been written.
                seen_in_file[key].append(record)
                continue
            seen_in_file[key] = [record]
            batch.append(record)
            if len(batch) >= BATCH_SIZE:
                self._write_batch(batch, result, dry_run)
                batch = []
        self._write_batch(batch, result, dry_run)

        for key, records in seen_in_file.items():
            for duplicate in records[1:]:
                self._quarantine(duplicate, "duplicate_in_file", key, result, dry_run)

        if not dry_run:
            self._finish_run(run_id, result)
            self._commit()
        logger.info("imported %s: %s", result.source_file, result.as_dict())
        return result

    def _normalize(self, raw, year, data_source, repairer, result, now):
        code = normalize.normalize_ticker(raw.code)
        if not code:
            result.rows_rejected += 1
            result.rejections["missing_ticker"] += 1
            return None
        parsed_date = normalize.parse_date(raw.date_raw)
        if parsed_date is None:
            result.rows_rejected += 1
            result.rejections["unparseable_date"] += 1
            return None
        close = normalize.parse_number(raw.close)
        if close is None or close <= 0:
            result.rows_rejected += 1
            result.rejections["missing_or_nonpositive_close"] += 1
            return None

        trade_date, repair = repairer.apply(parsed_date)
        flags = []
        if repair is not None:
            flags.append("date_repaired")
            result.repairs[repair.correct_date] += 1
        if int(trade_date[:4]) != year:
            flags.append("year_mismatch")
        volume = normalize.parse_volume(raw.volume)
        if volume is None and not normalize.is_missing(raw.volume):
            flags.append("unparseable_volume")
        change_abs = normalize.parse_number(raw.change_abs)
        if change_abs is None and not normalize.is_missing(raw.change_abs):
            flags.append("unparseable_change")
        change_pct = normalize.parse_percent(raw.change_pct)
        if change_pct is None and not normalize.is_missing(raw.change_pct):
            flags.append("unparseable_change_pct")
        for flag in flags:
            result.flags[flag] += 1

        return {
            "ticker_symbol": lineage.resolve(code),
            "trade_date": trade_date,
            "source_ticker": code,
            "company_name": normalize.normalize_name(raw.name) or None,
            "close_price": close,
            "previous_close": normalize.parse_number(raw.previous),
            "day_low": normalize.parse_number(raw.day_low),
            "day_high": normalize.parse_number(raw.day_high),
            "year_low": normalize.parse_number(raw.year_low),
            "year_high": normalize.parse_number(raw.year_high),
            "change_abs": change_abs,
            "change_pct": change_pct,
            "volume": volume,
            "adjusted_price": normalize.parse_number(raw.adjusted),
            "data_source": data_source,
            "source_file": raw.source_file,
            "source_row": raw.source_row,
            "source_date_raw": raw.date_raw,
            "quality_flags": json.dumps(flags),
            "created_at": now,
            "updated_at": now,
        }

    def _write_batch(self, batch, result, dry_run):
        if not batch:
            return
        if dry_run:
            # Report what WOULD happen without writing: count keys already stored.
            for record in batch:
                if self._existing(record["ticker_symbol"], record["trade_date"]) is None:
                    result.rows_inserted += 1
                else:
                    result.rows_already_present += 1
            return
        # Fast path: one executemany for the whole batch. If every row landed, done.
        # Otherwise (a re-run, or a genuine collision) replay the batch row by row so
        # each ignored insert can be classified as already-present or conflicting.
        rows = [tuple(record[c] for c in OBSERVATION_COLUMNS) for record in batch]
        before = self.connection.total_changes
        self.connection.executemany(_INSERT_OBSERVATION, rows)
        landed = self.connection.total_changes - before
        if landed == len(batch):
            result.rows_inserted += landed
            self._commit()
            return

        for record in batch:
            cursor = self.connection.execute(
                _INSERT_OBSERVATION, tuple(record[c] for c in OBSERVATION_COLUMNS)
            )
            if cursor.rowcount == 1:
                result.rows_inserted += 1
                continue
            existing = self._existing(record["ticker_symbol"], record["trade_date"])
            if existing is not None and existing["close_price"] == record["close_price"]:
                result.rows_already_present += 1
            else:
                self._quarantine(
                    record, "conflicts_with_existing_observation",
                    (record["ticker_symbol"], record["trade_date"]), result, dry_run=False,
                    kept_id=existing["id"] if existing else None,
                )
        self._commit()

    def _existing(self, ticker, trade_date):
        return self.connection.execute(
            "SELECT id, close_price FROM stock_observations WHERE ticker_symbol = ? AND trade_date = ?",
            (ticker, trade_date),
        ).fetchone()

    def _quarantine(self, record, reason, key, result, dry_run, kept_id=None):
        if dry_run:
            result.rows_quarantined += 1
            return
        if kept_id is None:
            kept = self._existing(*key)
            kept_id = kept["id"] if kept else None
        cursor = self.connection.execute(
            _INSERT_CONFLICT,
            (
                record["ticker_symbol"], record["trade_date"], record["source_ticker"],
                record["company_name"], record["close_price"], record["previous_close"],
                record["day_low"], record["day_high"], record["year_low"], record["year_high"],
                record["change_abs"], record["change_pct"], record["volume"],
                record["adjusted_price"], record["data_source"], record["source_file"],
                record["source_row"], record["source_date_raw"], reason, kept_id, _now(),
            ),
        )
        # Counted only when actually stored: a re-run re-detects the same source line
        # and the unique index ignores it, so the count stays honest.
        if cursor.rowcount == 1:
            result.rows_quarantined += 1
        else:
            result.rows_already_present += 1

    # -- import_runs ----------------------------------------------------------------
    def _start_run(self, path, data_source):
        cursor = self.connection.execute(
            "INSERT INTO import_runs (data_source, source_file, file_sha256, started_at) VALUES (?,?,?,?)",
            (data_source, os.path.basename(path), readers.file_sha256(path), _now()),
        )
        self._commit()
        return cursor.lastrowid

    def _finish_run(self, run_id, result):
        self.connection.execute(
            "UPDATE import_runs SET finished_at = ?, rows_read = ?, rows_inserted = ?, "
            "rows_already_present = ?, rows_quarantined = ?, rows_rejected = ?, notes = ? WHERE id = ?",
            (
                _now(), result.rows_read, result.rows_inserted, result.rows_already_present,
                result.rows_quarantined, result.rows_rejected,
                json.dumps({"rejections": dict(result.rejections), "repairs": dict(result.repairs),
                            "flags": dict(result.flags)}),
                run_id,
            ),
        )
