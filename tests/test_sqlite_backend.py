"""Tests for SQLiteBackend - the invariants the Supabase migration had to carry over.

Each test here locks in one behaviour that, if lost, degrades the dataset silently rather
than loudly:

* one row per ticker -- a regression turns the table into a row-per-scrape log
* price_history appends only on a real move -- otherwise it grows by a duplicate a day
* an unscraped view keeps its stored value -- the bug that blanked four views for weeks
* a failed write is counted and replayable -- what lets the quality gate see a blackout
* data survives reopening the file -- what `docker compose run --rm` depends on
"""
import json
import os
import sqlite3
import tempfile
import unittest

from nse_scraper.db.backends import METRICS_COLUMNS, SQLiteBackend


def _sa_record(ticker="SCOM", price=35.6, change=0.282, scraped_at="2026-07-26T00:00:00+00:00", **metrics):
    """A stockanalysis_stocks record; pass metrics columns explicitly to include them."""
    record = {
        "ticker_symbol": ticker,
        "company_name": "Safaricom PLC",
        "rank": 1,
        "stock_price": price,
        "stock_change": change,
        "scraped_at": scraped_at,
    }
    record.update(metrics)
    return record


def _stock_record(ticker="SCOM", price=35.6, change=0.282, scraped_at="2026-07-26T00:00:00+00:00"):
    return {
        "ticker_symbol": ticker,
        "stock_name": "Safaricom PLC",
        "stock_price": price,
        "stock_change": change,
        "scraped_at": scraped_at,
        "created_at": scraped_at,
    }


class _SqliteTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "nested", "test.sqlite3")
        self.backend = SQLiteBackend(db_path=self.db_path)
        self.backend.open()
        self.addCleanup(self.backend.close)

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


class TestSchemaCreation(_SqliteTestCase):
    def test_open_creates_the_database_file_and_parent_directory(self):
        self.assertTrue(os.path.exists(self.db_path))

    def test_open_creates_both_tables(self):
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("stock_data", names)
        self.assertIn("stockanalysis_stocks", names)

    def test_stockanalysis_table_has_every_metrics_column(self):
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(stockanalysis_stocks)")
        }
        for column in METRICS_COLUMNS:
            self.assertIn(column, columns)
        self.assertIn("price_history", columns)
        self.assertIn("updated_at", columns)

    def test_ticker_symbol_is_the_primary_key(self):
        """The single-row-per-ticker model is enforced by the schema, not just by code."""
        for table in ("stock_data", "stockanalysis_stocks"):
            connection = sqlite3.connect(self.db_path)
            self.addCleanup(connection.close)
            primary_keys = [
                row[1] for row in connection.execute("PRAGMA table_info({})".format(table)) if row[5]
            ]
            self.assertEqual(primary_keys, ["ticker_symbol"], table)

    def test_open_is_idempotent(self):
        self.backend.upsert_stockanalysis_stock(_sa_record())
        self.backend.close()
        self.backend.open()
        self.assertEqual(self._count(), 1)

    def test_shipped_ddl_matches_the_runtime_schema(self):
        """sql/sqlite/001_schema.sql is documentation; it must not drift from the code."""
        ddl_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sql", "sqlite", "001_schema.sql",
        )
        reference = sqlite3.connect(":memory:")
        self.addCleanup(reference.close)
        with open(ddl_path, encoding="utf-8") as handle:
            reference.executescript(handle.read())

        live = sqlite3.connect(self.db_path)
        self.addCleanup(live.close)
        for table in ("stock_data", "stockanalysis_stocks"):
            expected = [(r[1], r[2], r[5]) for r in reference.execute("PRAGMA table_info({})".format(table))]
            actual = [(r[1], r[2], r[5]) for r in live.execute("PRAGMA table_info({})".format(table))]
            self.assertEqual(expected, actual, table)


class TestUpsertBehaviour(_SqliteTestCase):
    def test_repeated_writes_keep_one_row_per_ticker(self):
        for day, price in enumerate([35.6, 36.1, 37.0], start=1):
            self.backend.upsert_stockanalysis_stock(
                _sa_record(price=price, scraped_at="2026-07-2{}T00:00:00+00:00".format(day))
            )
        self.assertEqual(self._count(), 1)
        self.assertEqual(self._row()["stock_price"], 37.0)

    def test_distinct_tickers_get_distinct_rows(self):
        self.backend.upsert_stockanalysis_stock(_sa_record(ticker="SCOM"))
        self.backend.upsert_stockanalysis_stock(_sa_record(ticker="EQTY"))
        self.assertEqual(self._count(), 2)

    def test_write_returns_true_on_success(self):
        self.assertIs(self.backend.upsert_stockanalysis_stock(_sa_record()), True)
        self.assertIs(self.backend.upsert_stock(_stock_record()), True)

    def test_created_at_is_preserved_but_updated_at_moves(self):
        self.backend.upsert_stockanalysis_stock(_sa_record(price=35.6))
        first = self._row()
        self.backend.upsert_stockanalysis_stock(_sa_record(price=40.0))
        second = self._row()
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertGreaterEqual(second["updated_at"], first["updated_at"])

    def test_stock_data_upsert_updates_in_place(self):
        self.backend.upsert_stock(_stock_record(price=35.6))
        self.backend.upsert_stock(_stock_record(price=36.6))
        self.assertEqual(self._count("stock_data"), 1)
        self.assertEqual(self._row(table="stock_data")["stock_price"], 36.6)


class TestPriceHistory(_SqliteTestCase):
    def _history(self, ticker="SCOM", table="stockanalysis_stocks"):
        return json.loads(self._row(ticker, table)["price_history"])

    def test_first_write_seeds_one_entry(self):
        self.backend.upsert_stockanalysis_stock(_sa_record(price=35.6))
        history = self._history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["stock_price"], 35.6)
        self.assertEqual(history[0]["scraped_at"], "2026-07-26T00:00:00+00:00")

    def test_a_moved_price_appends(self):
        self.backend.upsert_stockanalysis_stock(_sa_record(price=35.6))
        self.backend.upsert_stockanalysis_stock(
            _sa_record(price=36.6, scraped_at="2026-07-27T00:00:00+00:00")
        )
        self.assertEqual([e["stock_price"] for e in self._history()], [35.6, 36.6])

    def test_an_unchanged_price_does_not_append(self):
        """price_history is a change log; a flat week must not become seven entries."""
        for day in range(26, 30):
            self.backend.upsert_stockanalysis_stock(
                _sa_record(price=35.6, change=0.282, scraped_at="2026-07-{}T00:00:00+00:00".format(day))
            )
        self.assertEqual(len(self._history()), 1)

    def test_a_moved_change_alone_appends(self):
        self.backend.upsert_stockanalysis_stock(_sa_record(price=35.6, change=0.282))
        self.backend.upsert_stockanalysis_stock(
            _sa_record(price=35.6, change=-1.5, scraped_at="2026-07-27T00:00:00+00:00")
        )
        self.assertEqual(len(self._history()), 2)

    def test_history_accumulates_for_stock_data_too(self):
        self.backend.upsert_stock(_stock_record(price=35.6))
        self.backend.upsert_stock(_stock_record(price=36.6, scraped_at="2026-07-27T00:00:00+00:00"))
        self.backend.upsert_stock(_stock_record(price=36.6, scraped_at="2026-07-28T00:00:00+00:00"))
        self.assertEqual(len(self._history(table="stock_data")), 2)

    def test_history_is_queryable_with_json1(self):
        self.backend.upsert_stockanalysis_stock(_sa_record(price=35.6))
        self.backend.upsert_stockanalysis_stock(
            _sa_record(price=36.6, scraped_at="2026-07-27T00:00:00+00:00")
        )
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        depth = connection.execute(
            "SELECT json_array_length(price_history) FROM stockanalysis_stocks"
        ).fetchone()[0]
        self.assertEqual(depth, 2)


class TestMetricsJsonStorage(_SqliteTestCase):
    def test_metrics_round_trip_as_json(self):
        metrics = {"dividendYield": 4.67, "payoutFrequency": "Annual", "exDivDate": "May 25, 2026"}
        self.backend.upsert_stockanalysis_stock(_sa_record(dividends_metrics=metrics))
        self.assertEqual(json.loads(self._row()["dividends_metrics"]), metrics)

    def test_metrics_are_queryable_with_json_extract(self):
        self.backend.upsert_stockanalysis_stock(
            _sa_record(dividends_metrics={"dividendYield": 4.67})
        )
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        value = connection.execute(
            "SELECT json_extract(dividends_metrics, '$.dividendYield') FROM stockanalysis_stocks"
        ).fetchone()[0]
        self.assertEqual(value, 4.67)

    def test_nested_metric_structures_survive(self):
        metrics = {"overview": {"nested": [1, 2, {"deep": True}]}, "unicode": "Kenya — NSE"}
        self.backend.upsert_stockanalysis_stock(_sa_record(overview_metrics=metrics))
        self.assertEqual(json.loads(self._row()["overview_metrics"]), metrics)

    def test_an_unscraped_view_keeps_its_stored_value(self):
        """The invariant this whole backend was written around.

        Only ~16 tickers are enriched per run, so most days a ticker arrives with no
        dividends/profile/price metrics at all. Those columns must be left alone. Writing
        NULL instead is what blanked four views on every run under the old backend, and in
        SQLite the SET clause is ours to build -- so this is a real round-trip, not a
        payload-shape assertion.
        """
        self.backend.upsert_stockanalysis_stock(
            _sa_record(
                dividends_metrics={"dividendYield": 4.67},
                profile_metrics={"industry": "Telecom"},
                overview_metrics={"marketCap": 1_508_463_364_200},
            )
        )
        # A later run that enriched nothing: only overview is present.
        self.backend.upsert_stockanalysis_stock(
            _sa_record(
                price=40.0,
                scraped_at="2026-07-27T00:00:00+00:00",
                overview_metrics={"marketCap": 1_600_000_000_000},
            )
        )
        row = self._row()
        self.assertEqual(json.loads(row["dividends_metrics"]), {"dividendYield": 4.67})
        self.assertEqual(json.loads(row["profile_metrics"]), {"industry": "Telecom"})
        self.assertEqual(json.loads(row["overview_metrics"]), {"marketCap": 1_600_000_000_000})
        self.assertEqual(row["stock_price"], 40.0)

    def test_metrics_absent_on_first_insert_are_null(self):
        self.backend.upsert_stockanalysis_stock(_sa_record())
        row = self._row()
        for column in METRICS_COLUMNS:
            self.assertIsNone(row[column], column)


class TestFailedWrites(_SqliteTestCase):
    """A failed write must return False and stay replayable, never raise.

    That contract is what the quality gate depends on: pipelines._record_write turns the
    boolean into nse/db_upsert_ok / nse/db_upsert_failed, and DataQualityGate fails a run
    where every write failed. An exception instead would abort the crawl and lose the data.
    """

    def setUp(self):
        super().setUp()
        self.fallback_dir = os.path.join(self._tmp.name, "local_fallback")
        self.backend.local_fallback_dir = self.fallback_dir

    def _fallback_records(self):
        records = []
        for name in sorted(os.listdir(self.fallback_dir)):
            with open(os.path.join(self.fallback_dir, name), encoding="utf-8") as handle:
                records.extend(json.loads(line) for line in handle if line.strip())
        return records

    def test_failed_stockanalysis_write_returns_false_and_writes_fallback(self):
        self.backend.close()  # no connection -> every statement raises
        written = self.backend.upsert_stockanalysis_stock(
            _sa_record(dividends_metrics={"dividendYield": 4.67})
        )
        self.assertIs(written, False)
        records = self._fallback_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["ticker_symbol"], "SCOM")
        self.assertEqual(records[0]["dividends_metrics"], {"dividendYield": 4.67})

    def test_failed_stock_write_returns_false_and_writes_fallback(self):
        self.backend.close()
        self.assertIs(self.backend.upsert_stock(_stock_record()), False)
        records = self._fallback_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["ticker_symbol"], "SCOM")

    def test_fallback_payload_is_replayable(self):
        """A recorded failure must be re-writable verbatim once storage is healthy."""
        self.backend.close()
        self.backend.upsert_stockanalysis_stock(
            _sa_record(dividends_metrics={"dividendYield": 4.67})
        )
        payload = self._fallback_records()[0]

        self.backend.open()
        self.assertIs(self.backend.upsert_stockanalysis_stock(payload), True)
        self.assertEqual(json.loads(self._row()["dividends_metrics"]), {"dividendYield": 4.67})

    def test_a_failed_write_does_not_raise(self):
        self.backend.close()
        try:
            self.backend.upsert_stock(_stock_record())
        except Exception as error:  # pragma: no cover - the assertion is the point
            self.fail("a failed write must not propagate: {!r}".format(error))


class TestPersistenceAcrossRuns(unittest.TestCase):
    """`docker compose run --rm` destroys the container; the database must outlive it.

    Reopening the same path from a fresh backend instance is the in-process equivalent of
    the next day's container starting against the same bind-mounted file.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "data", "nse_scraper.sqlite3")

    def _run(self, records):
        backend = SQLiteBackend(db_path=self.db_path)
        backend.open()
        try:
            for record in records:
                backend.upsert_stockanalysis_stock(record)
        finally:
            backend.close()

    def test_data_survives_a_close_and_reopen(self):
        self._run([_sa_record(price=35.6)])
        self._run([])
        backend = SQLiteBackend(db_path=self.db_path)
        backend.open()
        self.addCleanup(backend.close)
        count = backend.connection.execute("SELECT COUNT(*) FROM stockanalysis_stocks").fetchone()[0]
        self.assertEqual(count, 1)

    def test_a_later_run_upserts_rather_than_appends(self):
        """Three 'days' of runs must leave one row and a three-point history."""
        self._run([_sa_record(price=35.6, scraped_at="2026-07-26T00:00:00+00:00")])
        self._run([_sa_record(price=36.6, scraped_at="2026-07-27T00:00:00+00:00")])
        self._run([_sa_record(price=37.6, scraped_at="2026-07-28T00:00:00+00:00")])

        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        rows, depth = connection.execute(
            "SELECT COUNT(*), json_array_length(price_history) FROM stockanalysis_stocks"
        ).fetchone()
        self.assertEqual(rows, 1)
        self.assertEqual(depth, 3)

    def test_metrics_from_separate_runs_accumulate(self):
        """Rotation means each run enriches a different slice; coverage must build up."""
        self._run([_sa_record(dividends_metrics={"dividendYield": 4.67})])
        self._run([_sa_record(scraped_at="2026-07-27T00:00:00+00:00",
                              profile_metrics={"industry": "Telecom"})])

        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM stockanalysis_stocks").fetchone()
        self.assertEqual(json.loads(row["dividends_metrics"]), {"dividendYield": 4.67})
        self.assertEqual(json.loads(row["profile_metrics"]), {"industry": "Telecom"})


if __name__ == "__main__":
    unittest.main()
