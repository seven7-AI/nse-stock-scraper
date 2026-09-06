#!/usr/bin/env python3
"""Migrate the recorded production dataset into SQLite by replaying the local fallback.

Why the fallback and not Supabase: the Supabase project host stopped resolving in DNS on
2026-07-26 and has not returned. Every upsert since has failed, and every failed payload
was appended to ``reports/local_fallback/*.jsonl`` by
``SupabaseBackend._write_local_fallback`` and committed to git by the daily wrapper. Those
files are the only reachable copy of the data, and each line is a *complete* upsert payload
in exactly the shape the backend writes -- so replaying them reproduces the dataset rather
than approximating it.

Replaying chronologically also rebuilds what the outage destroyed. Each stored payload
carries a ``price_history`` of length 1, because the read-back that would have grown the
array failed too. Feeding the files through the live backend in date order runs every
payload past the real append-only-if-price-or-change-moved rule, yielding a genuine
multi-point series per ticker -- more history than Supabase itself held.

The same reasoning applies to metrics: only ~16 tickers are enriched per run, so any single
day has partial ``dividends_metrics``/``profile_metrics``/etc. Because the backend omits
(rather than nulls) a metrics column that is absent from a payload, folding many days
accumulates the union across days instead of the last day's fragment.

This script deliberately calls ``SQLiteBackend`` rather than writing its own SQL, so the
migration path and the runtime path cannot drift apart.

Usage:
    python3 scripts/migrate_fallback_to_sqlite.py --dry-run
    python3 scripts/migrate_fallback_to_sqlite.py --report reports/migration/
"""

import argparse
import collections
import json
import os
import re
import sys
import sqlite3
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nse_scraper.db.backends import METRICS_COLUMNS, SQLiteBackend  # noqa: E402

DEFAULT_SOURCE_DIR = "reports/local_fallback"
DEFAULT_DB_PATH = "data/nse_scraper.sqlite3"

# stockanalysis_stocks_fallback-2026-09-06.jsonl -> ("stockanalysis_stocks", "2026-09-06")
FALLBACK_RE = re.compile(r"^(?P<kind>.+)_fallback-(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")

STOCK_DATA = "stock_data"
STOCKANALYSIS = "stockanalysis_stocks"


def discover_sources(source_dir):
    """Fallback files grouped by table, each sorted oldest-first.

    Ordering is the whole point: replaying out of order would build price_history
    backwards and let an older metrics fragment overwrite a newer one.
    """
    grouped = collections.defaultdict(list)
    for name in sorted(os.listdir(source_dir)):
        match = FALLBACK_RE.match(name)
        if not match:
            continue
        grouped[match.group("kind")].append((match.group("date"), os.path.join(source_dir, name)))
    for kind in grouped:
        grouped[kind].sort(key=lambda pair: pair[0])
    return grouped


def read_payloads(path):
    """Yield payloads in file order.

    Within-file order matters as much as between-file order: the 2026-07-26 file holds two
    runs' worth of rows, so each ticker appears twice and the later line must win.
    """
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError as error:
                print("  ! skipping {}:{} -- {}".format(path, line_number, error))


def replay(backend, grouped, verbose=True):
    """Replay every payload through the live backend. Returns per-kind counters."""
    stats = {}
    for kind, files in sorted(grouped.items()):
        if kind == STOCKANALYSIS:
            write = backend.upsert_stockanalysis_stock
        elif kind == STOCK_DATA:
            write = backend.upsert_stock
        else:
            print("  ! unknown fallback kind {!r}, skipping".format(kind))
            continue

        counter = {"files": len(files), "rows": 0, "ok": 0, "failed": 0, "tickers": set()}
        for date, path in files:
            for payload in read_payloads(path):
                counter["rows"] += 1
                counter["tickers"].add(payload.get("ticker_symbol"))
                if write(payload):
                    counter["ok"] += 1
                else:
                    counter["failed"] += 1
            if verbose:
                print("  {} {} -> {} rows".format(kind, date, counter["rows"]))
        counter["tickers"] = sorted(t for t in counter["tickers"] if t)
        stats[kind] = counter
    return stats


def existing_row_counts(db_path):
    """Rows already present per table, or {} if the database does not exist yet."""
    if not os.path.exists(db_path):
        return {}
    connection = sqlite3.connect(db_path)
    try:
        counts = {}
        for table in (STOCK_DATA, STOCKANALYSIS):
            if _table_exists(connection, table):
                counts[table] = connection.execute(
                    "SELECT COUNT(*) FROM {}".format(table)
                ).fetchone()[0]
        return {table: count for table, count in counts.items() if count}
    finally:
        connection.close()


def reset_tables(db_path):
    """Empty the migrated tables so a re-run reproduces the same result.

    The replay is append-based by design -- it feeds every payload through the live
    backend's price-history rule -- which makes it *not* idempotent against a populated
    database: starting again from the oldest file appends the whole series a second time.
    Clearing first is what makes `--reset` deterministic instead of cumulative.
    """
    if not os.path.exists(db_path):
        return
    connection = sqlite3.connect(db_path)
    try:
        for table in (STOCK_DATA, STOCKANALYSIS):
            if _table_exists(connection, table):
                connection.execute("DELETE FROM {}".format(table))
        connection.commit()
    finally:
        connection.close()


def _table_exists(connection, table):
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def inspect(db_path):
    """Post-migration validation: counts, history depth, metric fill rates, samples."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    result = {}

    for table in (STOCK_DATA, STOCKANALYSIS):
        if not _table_exists(connection, table):
            continue
        summary = {
            "row_count": connection.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0],
            "distinct_tickers": connection.execute(
                "SELECT COUNT(DISTINCT ticker_symbol) FROM {}".format(table)
            ).fetchone()[0],
        }

        depths = connection.execute(
            "SELECT json_array_length(price_history) AS depth, COUNT(*) AS n "
            "FROM {} GROUP BY depth ORDER BY depth".format(table)
        ).fetchall()
        summary["price_history_depths"] = {str(r["depth"]): r["n"] for r in depths}
        summary["price_history_total_points"] = connection.execute(
            "SELECT COALESCE(SUM(json_array_length(price_history)), 0) FROM {}".format(table)
        ).fetchone()[0]

        span = connection.execute(
            "SELECT MIN(scraped_at) AS lo, MAX(scraped_at) AS hi FROM {}".format(table)
        ).fetchone()
        summary["scraped_at_span"] = [span["lo"], span["hi"]]

        if table == STOCKANALYSIS:
            summary["metrics_fill"] = {
                column: connection.execute(
                    "SELECT COUNT(*) FROM {} WHERE {} IS NOT NULL".format(table, column)
                ).fetchone()[0]
                for column in METRICS_COLUMNS
            }

        result[table] = summary

    # A representative record, fully expanded, so the report is auditable by eye.
    if _table_exists(connection, STOCKANALYSIS):
        sample = connection.execute(
            "SELECT * FROM {} WHERE ticker_symbol = 'DTK'".format(STOCKANALYSIS)
        ).fetchone()
        if sample is None:
            sample = connection.execute(
                "SELECT * FROM {} ORDER BY rank LIMIT 1".format(STOCKANALYSIS)
            ).fetchone()
        if sample is not None:
            row = dict(sample)
            for column in METRICS_COLUMNS + ("price_history",):
                if row.get(column):
                    row[column] = json.loads(row[column])
            result["sample_stockanalysis_record"] = row

    if _table_exists(connection, STOCK_DATA):
        sample = connection.execute(
            "SELECT * FROM {} ORDER BY ticker_symbol LIMIT 1".format(STOCK_DATA)
        ).fetchone()
        if sample is not None:
            row = dict(sample)
            row["price_history"] = json.loads(row["price_history"] or "[]")
            result["sample_stock_data_record"] = row

    connection.close()
    return result


def validate(source_stats, inspection):
    """Cross-check the database against the source files. Returns a list of problems."""
    problems = []
    for kind, counter in source_stats.items():
        if counter["failed"]:
            problems.append("{}: {} payloads failed to write".format(kind, counter["failed"]))
        table = inspection.get(kind)
        if table is None:
            problems.append("{}: table missing from database".format(kind))
            continue
        expected = len(counter["tickers"])
        if table["row_count"] != expected:
            problems.append(
                "{}: {} rows in database but {} distinct tickers in source".format(
                    kind, table["row_count"], expected
                )
            )
        if table["row_count"] != table["distinct_tickers"]:
            problems.append(
                "{}: {} rows for {} distinct tickers -- one-row-per-ticker violated".format(
                    kind, table["row_count"], table["distinct_tickers"]
                )
            )
        lo, hi = table["scraped_at_span"]
        for value in (lo, hi):
            if value is None:
                problems.append("{}: null scraped_at present".format(kind))
                continue
            try:
                datetime.fromisoformat(value)
            except (TypeError, ValueError):
                problems.append("{}: scraped_at {!r} is not ISO-8601".format(kind, value))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="replay into a throwaway database and report; the target file is untouched",
    )
    parser.add_argument(
        "--report",
        metavar="DIR",
        help="write a JSON validation report into DIR",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="empty the migrated tables first; required to re-run against a populated database",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.source_dir):
        parser.error("source directory not found: {}".format(args.source_dir))

    grouped = discover_sources(args.source_dir)
    if not grouped:
        parser.error("no *_fallback-YYYY-MM-DD.jsonl files in {}".format(args.source_dir))

    temp_dir = None
    if args.dry_run:
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, "dry-run.sqlite3")
    else:
        db_path = args.db_path

    # Replaying onto rows that are already there would append the whole price series a
    # second time, so a populated target is refused rather than quietly corrupted.
    existing = existing_row_counts(db_path)
    if existing and not args.reset:
        parser.error(
            "target already contains data ({}); re-running would duplicate price_history "
            "entries. Pass --reset to rebuild from scratch, or --dry-run to inspect.".format(
                ", ".join("{}={}".format(t, n) for t, n in sorted(existing.items()))
            )
        )
    if args.reset:
        reset_tables(db_path)

    print("Source : {} ({} table(s))".format(args.source_dir, len(grouped)))
    print("Target : {}{}{}".format(
        db_path,
        "  [DRY RUN]" if args.dry_run else "",
        "  [RESET]" if args.reset and not args.dry_run else "",
    ))

    backend = SQLiteBackend(db_path=db_path)
    backend.open()
    try:
        source_stats = replay(backend, grouped, verbose=not args.quiet)
    finally:
        backend.close()

    inspection = inspect(db_path)
    problems = validate(source_stats, inspection)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": os.path.abspath(args.source_dir),
        "db_path": os.path.abspath(db_path),
        "dry_run": bool(args.dry_run),
        "source": {
            kind: {k: (len(v) if k == "tickers" else v) for k, v in counter.items()}
            for kind, counter in source_stats.items()
        },
        "database": inspection,
        "problems": problems,
        "ok": not problems,
    }

    print("\n--- migration summary ---")
    for kind, counter in sorted(source_stats.items()):
        table = inspection.get(kind, {})
        print(
            "{:22s} {:>5} rows replayed ({} ok / {} failed) from {} files "
            "-> {} database rows, {} history points".format(
                kind,
                counter["rows"],
                counter["ok"],
                counter["failed"],
                counter["files"],
                table.get("row_count", "?"),
                table.get("price_history_total_points", "?"),
            )
        )
    if problems:
        print("\nPROBLEMS:")
        for problem in problems:
            print("  - {}".format(problem))
    else:
        print("\nvalidation OK")

    if args.report:
        os.makedirs(args.report, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        path = os.path.join(args.report, "migration-{}.json".format(stamp))
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(report, indent=2, default=str) + "\n")
        print("report written to {}".format(path))

    if temp_dir is not None:
        temp_dir.cleanup()

    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
