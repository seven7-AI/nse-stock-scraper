"""Tests for scripts/migrate_fallback_to_sqlite.py - the Supabase-to-SQLite data migration.

The migration replays reports/local_fallback/*.jsonl because the Supabase project became
unreachable (DNS NXDOMAIN) on 2026-07-26 and the fallback files are the only surviving copy
of the data. What these tests lock in is that the replay is *order-dependent and
accumulating*, not a last-file-wins copy:

* files must be applied oldest-first, or price_history is built backwards
* lines within a file must be applied in order (the 2026-07-26 file holds two runs)
* metrics present on one day and absent the next must survive
* re-running the migration must not duplicate rows or history points

Fully offline: fixtures are written into a temp directory, never read from reports/.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
)

from migrate_fallback_to_sqlite import (  # noqa: E402
    discover_sources,
    inspect,
    main,
    read_payloads,
    replay,
    validate,
)
from nse_scraper.db.backends import SQLiteBackend  # noqa: E402


def _sa_payload(ticker="SCOM", price=35.6, change=0.28, scraped_at="2026-07-26T07:00:00+00:00", **metrics):
    """A fallback line in exactly the shape SupabaseBackend recorded."""
    payload = {
        "ticker_symbol": ticker,
        "company_name": "Safaricom PLC",
        "rank": 1,
        "stock_price": price,
        "stock_change": change,
        "scraped_at": scraped_at,
        # Every recorded payload carries a single-entry history, because the read-back
        # that would have grown it failed too. The migration must rebuild, not copy this.
        "price_history": [
            {"scraped_at": scraped_at, "stock_price": price, "stock_change": change}
        ],
    }
    payload.update(metrics)
    return payload


class _MigrationTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.source_dir = os.path.join(self._tmp.name, "local_fallback")
        os.makedirs(self.source_dir)
        self.db_path = os.path.join(self._tmp.name, "data", "test.sqlite3")

    def _write_fallback(self, kind, date, payloads):
        path = os.path.join(self.source_dir, "{}_fallback-{}.jsonl".format(kind, date))
        with open(path, "a", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(json.dumps(payload) + "\n")
        return path

    def _migrate(self):
        backend = SQLiteBackend(db_path=self.db_path)
        backend.open()
        try:
            stats = replay(backend, discover_sources(self.source_dir), verbose=False)
        finally:
            backend.close()
        return stats

    def _row(self, ticker="SCOM", table="stockanalysis_stocks"):
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM {} WHERE ticker_symbol = ?".format(table), (ticker,)
        ).fetchone()
        return dict(row) if row is not None else None

    def _count(self, table="stockanalysis_stocks"):
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        return connection.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]


class TestSourceDiscovery(_MigrationTestCase):
    def test_files_are_grouped_by_table_and_sorted_oldest_first(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-28", [_sa_payload()])
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        self._write_fallback("stockanalysis_stocks", "2026-07-27", [_sa_payload()])
        self._write_fallback("stock_data", "2026-08-08", [])

        grouped = discover_sources(self.source_dir)
        self.assertEqual(sorted(grouped), ["stock_data", "stockanalysis_stocks"])
        self.assertEqual(
            [date for date, _ in grouped["stockanalysis_stocks"]],
            ["2026-07-26", "2026-07-27", "2026-07-28"],
        )

    def test_unrelated_files_are_ignored(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        with open(os.path.join(self.source_dir, "notes.txt"), "w", encoding="utf-8") as handle:
            handle.write("not a fallback file\n")
        with open(os.path.join(self.source_dir, ".gitkeep"), "w", encoding="utf-8") as handle:
            handle.write("")
        self.assertEqual(len(discover_sources(self.source_dir)), 1)

    def test_blank_and_malformed_lines_are_skipped(self):
        path = self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n")
            handle.write("{not json\n")
        self.assertEqual(len(list(read_payloads(path))), 1)


class TestChronologicalReplay(_MigrationTestCase):
    def test_history_is_rebuilt_across_days(self):
        """Three days of single-entry payloads become one row with a three-point history."""
        for day, price in ((26, 35.6), (27, 36.6), (28, 37.6)):
            self._write_fallback(
                "stockanalysis_stocks",
                "2026-07-{}".format(day),
                [_sa_payload(price=price, scraped_at="2026-07-{}T07:00:00+00:00".format(day))],
            )
        self._migrate()

        self.assertEqual(self._count(), 1)
        history = json.loads(self._row()["price_history"])
        self.assertEqual([e["stock_price"] for e in history], [35.6, 36.6, 37.6])

    def test_the_newest_day_wins_for_scalar_fields(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload(price=35.6)])
        self._write_fallback(
            "stockanalysis_stocks",
            "2026-07-27",
            [_sa_payload(price=40.0, scraped_at="2026-07-27T07:00:00+00:00")],
        )
        self._migrate()
        self.assertEqual(self._row()["stock_price"], 40.0)

    def test_repeated_tickers_within_one_file_apply_in_order(self):
        """The real 2026-07-26 file holds two runs, so each ticker appears twice."""
        self._write_fallback(
            "stockanalysis_stocks",
            "2026-07-26",
            [
                _sa_payload(price=35.6, scraped_at="2026-07-26T07:00:00+00:00"),
                _sa_payload(price=38.0, scraped_at="2026-07-26T19:00:00+00:00"),
            ],
        )
        self._migrate()
        self.assertEqual(self._count(), 1)
        self.assertEqual(self._row()["stock_price"], 38.0)
        self.assertEqual(len(json.loads(self._row()["price_history"])), 2)

    def test_an_unchanged_price_adds_no_history_point(self):
        for day in (26, 27, 28):
            self._write_fallback(
                "stockanalysis_stocks",
                "2026-07-{}".format(day),
                [_sa_payload(price=35.6, scraped_at="2026-07-{}T07:00:00+00:00".format(day))],
            )
        self._migrate()
        self.assertEqual(len(json.loads(self._row()["price_history"])), 1)


class TestMetricsAccumulation(_MigrationTestCase):
    def test_metrics_from_different_days_merge(self):
        """Rotation enriches ~16 tickers a day, so coverage only exists across days."""
        self._write_fallback(
            "stockanalysis_stocks",
            "2026-07-26",
            [_sa_payload(dividends_metrics={"dividendYield": 4.67})],
        )
        self._write_fallback(
            "stockanalysis_stocks",
            "2026-07-27",
            [_sa_payload(scraped_at="2026-07-27T07:00:00+00:00",
                         profile_metrics={"industry": "Telecom"})],
        )
        self._migrate()

        row = self._row()
        self.assertEqual(json.loads(row["dividends_metrics"]), {"dividendYield": 4.67})
        self.assertEqual(json.loads(row["profile_metrics"]), {"industry": "Telecom"})

    def test_a_later_day_without_metrics_does_not_blank_them(self):
        self._write_fallback(
            "stockanalysis_stocks",
            "2026-07-26",
            [_sa_payload(dividends_metrics={"dividendYield": 4.67})],
        )
        for day in (27, 28, 29):
            self._write_fallback(
                "stockanalysis_stocks",
                "2026-07-{}".format(day),
                [_sa_payload(price=36.0 + day, scraped_at="2026-07-{}T07:00:00+00:00".format(day))],
            )
        self._migrate()
        self.assertEqual(json.loads(self._row()["dividends_metrics"]), {"dividendYield": 4.67})

    def test_a_later_day_with_metrics_replaces_them(self):
        self._write_fallback(
            "stockanalysis_stocks",
            "2026-07-26",
            [_sa_payload(dividends_metrics={"dividendYield": 4.67})],
        )
        self._write_fallback(
            "stockanalysis_stocks",
            "2026-07-27",
            [_sa_payload(scraped_at="2026-07-27T07:00:00+00:00",
                         dividends_metrics={"dividendYield": 5.10})],
        )
        self._migrate()
        self.assertEqual(json.loads(self._row()["dividends_metrics"]), {"dividendYield": 5.10})


class TestStockDataMigration(_MigrationTestCase):
    def test_stock_data_payloads_migrate(self):
        payload = {
            "ticker_symbol": "ABSA",
            "stock_name": "Absa Bank Kenya Plc",
            "stock_price": 33.4,
            "stock_change": 0.1,
            "scraped_at": "2026-08-08T07:00:26.368810+00:00",
            "created_at": "2026-08-08T07:00:26.368810+00:00",
            "price_history": [],
        }
        self._write_fallback("stock_data", "2026-08-08", [payload])
        stats = self._migrate()

        self.assertEqual(stats["stock_data"]["ok"], 1)
        self.assertEqual(self._count("stock_data"), 1)
        row = self._row("ABSA", table="stock_data")
        self.assertEqual(row["stock_name"], "Absa Bank Kenya Plc")
        self.assertEqual(row["stock_price"], 33.4)
        self.assertEqual(len(json.loads(row["price_history"])), 1)


class TestIdempotence(_MigrationTestCase):
    """Replaying is append-based, so a re-run must either reset or refuse.

    Without a guard, running the migration twice restarts from the oldest file and appends
    the entire price series a second time -- 2 points silently become 4.
    """

    def _seed_two_days(self):
        for day, price in ((26, 35.6), (27, 36.6)):
            self._write_fallback(
                "stockanalysis_stocks",
                "2026-07-{}".format(day),
                [_sa_payload(price=price, scraped_at="2026-07-{}T07:00:00+00:00".format(day))],
            )

    def test_a_second_run_against_a_populated_database_is_refused(self):
        self._seed_two_days()
        self.assertEqual(main(["--source-dir", self.source_dir, "--db-path", self.db_path,
                               "--quiet"]), 0)
        depth_before = len(json.loads(self._row()["price_history"]))

        with self.assertRaises(SystemExit):
            main(["--source-dir", self.source_dir, "--db-path", self.db_path, "--quiet"])

        self.assertEqual(len(json.loads(self._row()["price_history"])), depth_before)

    def test_reset_makes_a_re_run_reproduce_the_same_result(self):
        self._seed_two_days()
        main(["--source-dir", self.source_dir, "--db-path", self.db_path, "--quiet"])
        first_rows = self._count()
        first_history = json.loads(self._row()["price_history"])

        main(["--source-dir", self.source_dir, "--db-path", self.db_path, "--reset", "--quiet"])

        self.assertEqual(self._count(), first_rows)
        self.assertEqual(json.loads(self._row()["price_history"]), first_history)

    def test_reset_on_a_missing_database_is_harmless(self):
        self._seed_two_days()
        self.assertEqual(
            main(["--source-dir", self.source_dir, "--db-path", self.db_path,
                  "--reset", "--quiet"]),
            0,
        )
        self.assertEqual(self._count(), 1)


class TestValidation(_MigrationTestCase):
    def test_inspect_reports_counts_and_history_depth(self):
        for day, price in ((26, 35.6), (27, 36.6)):
            self._write_fallback(
                "stockanalysis_stocks",
                "2026-07-{}".format(day),
                [_sa_payload(price=price, scraped_at="2026-07-{}T07:00:00+00:00".format(day))],
            )
        self._migrate()

        report = inspect(self.db_path)
        summary = report["stockanalysis_stocks"]
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(summary["distinct_tickers"], 1)
        self.assertEqual(summary["price_history_total_points"], 2)
        self.assertIn("metrics_fill", summary)

    def test_validate_passes_a_clean_migration(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        stats = self._migrate()
        self.assertEqual(validate(stats, inspect(self.db_path)), [])

    def test_validate_flags_a_row_count_mismatch(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        stats = self._migrate()
        stats["stockanalysis_stocks"]["tickers"] = ["SCOM", "EQTY"]  # a ticker that never landed
        problems = validate(stats, inspect(self.db_path))
        self.assertTrue(any("rows in database" in p for p in problems))

    def test_validate_flags_failed_writes(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        stats = self._migrate()
        stats["stockanalysis_stocks"]["failed"] = 3
        problems = validate(stats, inspect(self.db_path))
        self.assertTrue(any("failed to write" in p for p in problems))


class TestCommandLine(_MigrationTestCase):
    def test_dry_run_leaves_the_target_untouched(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        exit_code = main(
            ["--source-dir", self.source_dir, "--db-path", self.db_path, "--dry-run", "--quiet"]
        )
        self.assertEqual(exit_code, 0)
        self.assertFalse(os.path.exists(self.db_path))

    def test_real_run_creates_the_database_and_a_report(self):
        self._write_fallback("stockanalysis_stocks", "2026-07-26", [_sa_payload()])
        report_dir = os.path.join(self._tmp.name, "migration")
        exit_code = main(
            ["--source-dir", self.source_dir, "--db-path", self.db_path,
             "--report", report_dir, "--quiet"]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(os.path.exists(self.db_path))

        reports = os.listdir(report_dir)
        self.assertEqual(len(reports), 1)
        with open(os.path.join(report_dir, reports[0]), encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertTrue(report["ok"])
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["database"]["stockanalysis_stocks"]["row_count"], 1)


if __name__ == "__main__":
    unittest.main()
