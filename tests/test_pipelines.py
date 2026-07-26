"""
Tests for the StockAnalysis pipeline and the partial-update safety in the backend.

Since the screener API was retired, a run legitimately produces only a subset of the
five views for some tickers. Writing None for the rest blanked the stored columns on
every run, so these lock in that an unscraped view is omitted rather than nulled.
"""
import unittest

from nse_scraper.db.backends import SupabaseBackend
from nse_scraper.pipelines import StockAnalysisPipeline


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


if __name__ == "__main__":
    unittest.main()
