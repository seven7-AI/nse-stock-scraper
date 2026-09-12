#!/usr/bin/env python3
"""Replay each ticker's price_history JSON into stock_observations. One-off, idempotent.

Before the canonical table existed (2026-09-12) the scraper kept its daily observations
only as a JSON array on the per-ticker row - appended whenever price or change moved.
Those are real scrapes, dated by scraped_at, and this copies them into the timeline so
the 2026 end of every series is more than a single point.

    python scripts/backfill_observations_from_history.py            # live
    python scripts/backfill_observations_from_history.py --dry-run

Rows land with data_source='nse_scraper' and quality_flags
["scrape_date_is_observation_date", "backfilled_from_price_history"], resolved through
instrument_aliases, INSERT OR IGNORE on (ticker_symbol, trade_date). Re-running inserts 0.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

FLAGS = json.dumps(["scrape_date_is_observation_date", "backfilled_from_price_history"])


def backfill(db_path, dry_run=False):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    now = datetime.now(timezone.utc).isoformat()
    aliases = dict(connection.execute("SELECT source_ticker, canonical_ticker FROM instrument_aliases").fetchall())
    known = {r[0] for r in connection.execute("SELECT ticker_symbol FROM instruments")}

    stats = {"tickers": 0, "points": 0, "inserted": 0, "already_present": 0, "skipped_no_price": 0, "instruments_created": 0}
    try:
        for row in connection.execute("SELECT ticker_symbol, company_name, price_history FROM stockanalysis_stocks"):
            ticker = (row["ticker_symbol"] or "").strip().upper()
            if not ticker:
                continue
            canonical = aliases.get(ticker, ticker)
            try:
                history = json.loads(row["price_history"] or "[]")
            except (TypeError, ValueError):
                history = []
            if not isinstance(history, list) or not history:
                continue
            stats["tickers"] += 1
            if canonical not in known:
                connection.execute(
                    "INSERT OR IGNORE INTO instruments (ticker_symbol, company_name, instrument_type, "
                    "created_at, updated_at) VALUES (?, ?, 'ordinary', ?, ?)",
                    (canonical, row["company_name"] or canonical, now, now),
                )
                known.add(canonical)
                stats["instruments_created"] += 1
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                stats["points"] += 1
                price = entry.get("stock_price")
                scraped_at = str(entry.get("scraped_at") or "")
                if price is None or len(scraped_at) < 10:
                    stats["skipped_no_price"] += 1
                    continue
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO stock_observations (ticker_symbol, trade_date, source_ticker, "
                    "company_name, close_price, change_abs, data_source, source_date_raw, quality_flags, "
                    "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (canonical, scraped_at[:10], ticker, row["company_name"], float(price),
                     float(entry["stock_change"]) if entry.get("stock_change") is not None else None,
                     "nse_scraper", scraped_at, FLAGS, now, now),
                )
                if cursor.rowcount == 1:
                    stats["inserted"] += 1
                else:
                    stats["already_present"] += 1
        connection.execute(
            "UPDATE instruments SET last_seen_date = (SELECT max(trade_date) FROM stock_observations o "
            "WHERE o.ticker_symbol = instruments.ticker_symbol), updated_at = ?", (now,))
        if dry_run:
            connection.rollback()
        else:
            connection.commit()
    finally:
        connection.close()
    return stats


def main(argv=None):
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=os.getenv("SQLITE_DB_PATH", "data/nse_scraper.sqlite3"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    db_path = args.db if os.path.isabs(args.db) else os.path.join(REPO_ROOT, args.db)
    stats = backfill(db_path, dry_run=args.dry_run)
    tag = " (DRY RUN - rolled back)" if args.dry_run else ""
    print("backfill from price_history{}: {}".format(tag, json.dumps(stats)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
