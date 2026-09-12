#!/usr/bin/env python3
"""Import the 2007-2024 NSE archive into the canonical stock_observations table.

    python scripts/import_historical.py                      # everything
    python scripts/import_historical.py --years 2009 2017    # a subset
    python scripts/import_historical.py --dry-run            # count, write nothing
    python scripts/import_historical.py --validate           # import, then validate

Idempotent: re-running inserts nothing and reports rows_already_present == rows_read.
The archive directory defaults to NSE_ARCHIVE_DIR, then ../Nairobi-stock-Exchange/NSE_DATA
relative to this repository, so the two projects stay decoupled by a path, not by code.
"""

import argparse
import json
import logging
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

from nse_scraper.historical.importer import HistoricalImporter  # noqa: E402
from nse_scraper.historical.validate import validate, render_markdown  # noqa: E402

DEFAULT_ARCHIVE = os.path.normpath(os.path.join(REPO_ROOT, "..", "Nairobi-stock-Exchange", "NSE_DATA"))


def main(argv=None):
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=os.getenv("SQLITE_DB_PATH", "data/nse_scraper.sqlite3"),
                        help="SQLite database (default: SQLITE_DB_PATH or data/nse_scraper.sqlite3)")
    parser.add_argument("--archive-dir", default=os.getenv("NSE_ARCHIVE_DIR", DEFAULT_ARCHIVE),
                        help="directory holding NSE_data_all_stocks_*.csv and the sector files")
    parser.add_argument("--years", nargs="*", type=int, help="only these years")
    parser.add_argument("--dry-run", action="store_true", help="count what would happen; write nothing")
    parser.add_argument("--validate", action="store_true", help="run the validation report after importing")
    parser.add_argument("--report", default=None, help="write the validation report (markdown) here")
    parser.add_argument("--json", action="store_true", help="print per-file results as JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s %(message)s")

    if not os.path.isdir(args.archive_dir):
        parser.error("archive directory not found: {}".format(args.archive_dir))

    db_path = args.db if os.path.isabs(args.db) else os.path.join(REPO_ROOT, args.db)
    with HistoricalImporter(db_path, args.archive_dir) as importer:
        results = importer.run(years=args.years, dry_run=args.dry_run)

    dicts = [r.as_dict() for r in results]
    if args.json:
        print(json.dumps(dicts, indent=2))
    else:
        _print_table(dicts, dry_run=args.dry_run)

    if args.validate and not args.dry_run:
        report = validate(db_path, args.archive_dir)
        markdown = render_markdown(report)
        if args.report:
            with open(args.report, "w", encoding="utf-8") as handle:
                handle.write(markdown)
            print("\nvalidation report written to {}".format(args.report))
        else:
            print("\n" + markdown)
        return 0 if report["ok"] else 1
    return 0


def _print_table(dicts, dry_run):
    tag = " (DRY RUN — nothing written)" if dry_run else ""
    print("{:<30} {:>7} {:>7} {:>8} {:>5} {:>4}{}".format("file", "read", "insert", "present", "quar", "rej", tag))
    totals = {"rows_read": 0, "rows_inserted": 0, "rows_already_present": 0, "rows_quarantined": 0, "rows_rejected": 0}
    for d in dicts:
        for k in totals:
            totals[k] += d[k]
        notes = {**d["repairs"], **d["flags"], **d["rejections"]}
        print("{:<30} {:>7} {:>7} {:>8} {:>5} {:>4}  {}".format(
            d["source_file"], d["rows_read"], d["rows_inserted"], d["rows_already_present"],
            d["rows_quarantined"], d["rows_rejected"], notes if notes else ""))
    print("{:<30} {:>7} {:>7} {:>8} {:>5} {:>4}".format(
        "TOTAL", totals["rows_read"], totals["rows_inserted"], totals["rows_already_present"],
        totals["rows_quarantined"], totals["rows_rejected"]))


if __name__ == "__main__":
    sys.exit(main())
