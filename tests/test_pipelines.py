"""
Tests for the StockAnalysis pipeline and the partial-update safety in the backend.

Since the screener API was retired, a run legitimately produces only a subset of the
five views for some tickers. Writing None for the rest blanked the stored columns on
every run, so these lock in that an unscraped view is omitted rather than nulled.
"""
import unittest

from scrapy.exceptions import DropItem

from nse_scraper.db.backends import SUPPORTED_BACKENDS, SQLiteBackend, SupabaseBackend
from nse_scraper.extensions import DB_FAILED_STAT, DB_OK_STAT
from nse_scraper.pipelines import NseScraperPipeline, StockAnalysisPipeline


class _FakeStorage:
    def __init__(self):
        self.records = []

    def open(self):
        pass

    def close(self):
        pass

    def upsert_stockanalysis_stock(self, record):
        self.records.append(record)
        return True


def _view_item(view, ticker="SCOM", metrics=None):
    metrics = metrics or {"example": 1}
    return {
        "source": "stockanalysis",
        "view": view,
        "symbol": ticker,
        "ticker_symbol": ticker,
        "rank": 1,
        "company_name": "Safaricom PLC",
        "stock_name": "Safaricom PLC",
        "stock_price": 35.6,
        "stock_change": 0.282,
        "created_at": "2026-07-26T00:00:00+00:00",
        "metrics_raw": metrics,
        "metrics": metrics,
        "scraped_at": "2026-07-26T00:00:00+00:00",
    }


class TestStockAnalysisPipeline(unittest.TestCase):
    def setUp(self):
        # Credentials only have to satisfy the backend constructor; the real client is
        # replaced below so nothing touches the network.
        self.pipeline = StockAnalysisPipeline(
            db_backend="supabase",
            supabase_url="https://example.supabase.co",
            supabase_key="fake",
            stockanalysis_table="stockanalysis_stocks",
        )
        self.storage = _FakeStorage()
        self.pipeline.storage = self.storage

    def test_partial_views_are_still_written(self):
        self.pipeline.process_item(_view_item("overview"))
        self.pipeline.process_item(_view_item("dividends"))
        self.pipeline.close_spider()

        self.assertEqual(len(self.storage.records), 1)
        record = self.storage.records[0]
        self.assertEqual(record["ticker_symbol"], "SCOM")
        self.assertIsNotNone(record["overview_metrics"])
        self.assertIsNotNone(record["dividends_metrics"])

    def test_no_duplicate_write_when_all_views_arrive(self):
        """Buffered to close_spider so a straggler cannot trigger a thinner re-upsert."""
        for view in ("overview", "performance", "dividends", "price", "profile"):
            self.pipeline.process_item(_view_item(view))
        self.assertEqual(self.storage.records, [])

        self.pipeline.close_spider()
        self.assertEqual(len(self.storage.records), 1)

    def test_multiple_tickers_each_written_once(self):
        self.pipeline.process_item(_view_item("overview", ticker="SCOM"))
        self.pipeline.process_item(_view_item("overview", ticker="EQTY"))
        self.pipeline.close_spider()

        self.assertEqual(
            sorted(r["ticker_symbol"] for r in self.storage.records), ["EQTY", "SCOM"]
        )

    def test_same_view_from_two_pages_is_merged(self):
        """Profile arrives from both the quote and company pages, in any order."""
        self.pipeline.process_item(
            _view_item("profile", metrics={"industry": "Banks", "country": None})
        )
        self.pipeline.process_item(
            _view_item("profile", metrics={"industry": None, "country": "Kenya"})
        )
        self.pipeline.close_spider()

        metrics = self.storage.records[0]["profile_metrics"]
        self.assertEqual(metrics["industry"], "Banks")
        self.assertEqual(metrics["country"], "Kenya")

    def test_unrelated_items_pass_through(self):
        item = {"source": "afx", "ticker_symbol": "SCOM"}
        self.assertIs(self.pipeline.process_item(item), item)
        self.pipeline.close_spider()
        self.assertEqual(self.storage.records, [])


class _RecordingTable:
    def __init__(self, sink):
        self.sink = sink

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return type("Response", (), {"data": []})()

    def upsert(self, payload, **_kwargs):
        self.sink.append(payload)
        return self


class _RecordingClient:
    def __init__(self):
        self.payloads = []

    def table(self, _name):
        return _RecordingTable(self.payloads)


class TestPartialUpsertSafety(unittest.TestCase):
    def setUp(self):
        self.backend = SupabaseBackend(
            supabase_url="https://example.supabase.co",
            supabase_key="fake",
            supabase_table="stock_data",
        )
        self.client = _RecordingClient()
        self.backend.client = self.client

    def test_unscraped_views_are_omitted_not_nulled(self):
        written = self.backend.upsert_stockanalysis_stock(
            {
                "ticker_symbol": "SCOM",
                "company_name": "Safaricom PLC",
                "stock_price": 35.6,
                "stock_change": 0.282,
                "overview_metrics": {"marketCap": 1},
                "performance_metrics": None,
                "dividends_metrics": None,
                "price_metrics": None,
                "profile_metrics": None,
            }
        )

        self.assertTrue(written)
        payload = self.client.payloads[0]
        self.assertIn("overview_metrics", payload)
        for key in (
            "performance_metrics",
            "dividends_metrics",
            "price_metrics",
            "profile_metrics",
        ):
            self.assertNotIn(key, payload)

    def test_scraped_views_are_written(self):
        self.backend.upsert_stockanalysis_stock(
            {
                "ticker_symbol": "SCOM",
                "company_name": "Safaricom PLC",
                "stock_price": 35.6,
                "stock_change": 0.282,
                "overview_metrics": {"marketCap": 1},
                "dividends_metrics": {"dividendYield": 6.46},
            }
        )
        payload = self.client.payloads[0]
        self.assertEqual(payload["dividends_metrics"], {"dividendYield": 6.46})


class _FakeStats:
    """Minimal stats collector: only inc_value is used by the pipelines."""

    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1):
        self.values[key] = self.values.get(key, 0) + count


class _FailingStorage:
    """A backend whose writes fail the way a real one does: False, never an exception."""

    def __init__(self):
        self.records = []

    def open(self):
        pass

    def close(self):
        pass

    def upsert_stock(self, record):
        self.records.append(record)
        return False

    def upsert_stockanalysis_stock(self, record):
        self.records.append(record)
        return False


class _OkStockStorage(_FailingStorage):
    def upsert_stock(self, record):
        self.records.append(record)
        return True


class TestNseScraperPipeline(unittest.TestCase):
    """The afx_scraper pipeline: validation, one write per item, and the stat counters.

    The counters are the whole reason the pipeline holds a reference to crawler.stats:
    DataQualityGate fails a run where every write failed, which is what turned the Supabase
    outage into RUN_STATUS FAILED instead of a silent success.
    """

    def _pipeline(self, storage, stats=None):
        pipeline = NseScraperPipeline(
            db_backend="sqlite",
            stock_table="stock_data",
            sqlite_path="data/nse_scraper.sqlite3",
            stats=stats,
        )
        pipeline.storage = storage
        return pipeline

    def _item(self, **overrides):
        item = {
            "ticker_symbol": "SCOM",
            "stock_name": "Safaricom PLC",
            "stock_price": 35.6,
            "stock_change": 0.282,
        }
        item.update(overrides)
        return item

    def test_a_valid_item_is_written_and_returned(self):
        storage = _OkStockStorage()
        pipeline = self._pipeline(storage)
        item = self._item()
        self.assertIs(pipeline.process_item(item), item)
        self.assertEqual(len(storage.records), 1)
        self.assertEqual(storage.records[0]["ticker_symbol"], "SCOM")

    def test_a_successful_write_increments_the_ok_stat(self):
        stats = _FakeStats()
        self._pipeline(_OkStockStorage(), stats).process_item(self._item())
        self.assertEqual(stats.values.get(DB_OK_STAT), 1)
        self.assertIsNone(stats.values.get(DB_FAILED_STAT))

    def test_a_failed_write_increments_the_failed_stat(self):
        stats = _FakeStats()
        self._pipeline(_FailingStorage(), stats).process_item(self._item())
        self.assertEqual(stats.values.get(DB_FAILED_STAT), 1)
        self.assertIsNone(stats.values.get(DB_OK_STAT))

    def test_a_total_write_blackout_is_visible_to_the_quality_gate(self):
        """db_failed with no db_ok is exactly the condition DataQualityGate fails on."""
        stats = _FakeStats()
        pipeline = self._pipeline(_FailingStorage(), stats)
        for ticker in ("SCOM", "EQTY", "KCB"):
            pipeline.process_item(self._item(ticker_symbol=ticker))
        self.assertEqual(stats.values.get(DB_FAILED_STAT), 3)
        self.assertFalse(stats.values.get(DB_OK_STAT))

    def test_items_missing_required_fields_are_dropped_without_writing(self):
        storage = _OkStockStorage()
        pipeline = self._pipeline(storage)
        for missing in ("ticker_symbol", "stock_name", "stock_price"):
            with self.subTest(missing=missing):
                with self.assertRaises(DropItem):
                    pipeline.process_item(self._item(**{missing: None}))
        self.assertEqual(storage.records, [])

    def test_a_pipeline_without_stats_still_writes(self):
        """stats is optional; _record_write must not blow up when it is None."""
        storage = _OkStockStorage()
        self._pipeline(storage, stats=None).process_item(self._item())
        self.assertEqual(len(storage.records), 1)


class TestStockAnalysisPipelineStats(unittest.TestCase):
    def _pipeline(self, storage, stats):
        pipeline = StockAnalysisPipeline(
            db_backend="sqlite",
            stockanalysis_table="stockanalysis_stocks",
            sqlite_path="data/nse_scraper.sqlite3",
            stats=stats,
        )
        pipeline.storage = storage
        return pipeline

    def test_buffered_writes_are_counted_on_close(self):
        stats = _FakeStats()
        pipeline = self._pipeline(_FakeStorage(), stats)
        pipeline.process_item(_view_item("overview"))
        pipeline.process_item(_view_item("dividends"))
        # Nothing is written until close_spider: the pipeline buffers so a late view
        # cannot re-upsert a thinner record.
        self.assertEqual(stats.values, {})

        pipeline.close_spider()
        self.assertEqual(stats.values.get(DB_OK_STAT), 1)

    def test_failed_writes_are_counted_on_close(self):
        stats = _FakeStats()
        pipeline = self._pipeline(_FailingStorage(), stats)
        pipeline.process_item(_view_item("overview"))
        pipeline.close_spider()
        self.assertEqual(stats.values.get(DB_FAILED_STAT), 1)


class TestBackendSelection(unittest.TestCase):
    """StockAnalysisPipeline must build storage for any supported backend.

    While this tested `== "supabase"`, selecting sqlite left storage as None and every
    item passed through unstored -- with both counters at zero, so the quality gate saw
    nothing wrong.
    """

    def _pipeline(self, backend):
        return StockAnalysisPipeline(
            db_backend=backend,
            stockanalysis_table="stockanalysis_stocks",
            sqlite_path="data/nse_scraper.sqlite3",
            supabase_url="https://example.supabase.co",
            supabase_key="fake",
        )

    def test_sqlite_backend_builds_storage(self):
        self.assertIsInstance(self._pipeline("sqlite").storage, SQLiteBackend)

    def test_supabase_backend_still_builds_storage(self):
        self.assertIsInstance(self._pipeline("supabase").storage, SupabaseBackend)

    def test_every_supported_backend_builds_storage(self):
        for name in SUPPORTED_BACKENDS:
            with self.subTest(backend=name):
                self.assertIsNotNone(self._pipeline(name).storage)

    def test_an_unset_backend_leaves_items_untouched(self):
        pipeline = self._pipeline("")
        self.assertIsNone(pipeline.storage)
        item = _view_item("overview")
        self.assertIs(pipeline.process_item(item), item)


if __name__ == "__main__":
    unittest.main()
