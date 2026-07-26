"""
Tests for the run data-quality gate.

Scrapy exits 0 even when a spider scrapes nothing, which is how three months of
zero-item runs were committed as SUCCESS. These cover the thresholds that turn such a
run into a failure, and the CI-safety invariant that an unconfigured gate stays inert.
"""
import json
import os
import tempfile
import unittest

from nse_scraper.extensions import (
    DB_FAILED_STAT,
    DB_OK_STAT,
    DataQualityGate,
    min_items_setting_name,
)


class _FakeStats:
    def __init__(self, values):
        self._values = values

    def get_stats(self):
        return self._values


class _FakeSettings:
    def __init__(self, values):
        self._values = values

    def get(self, name, default=None):
        return self._values.get(name, default)

    def getint(self, name, default=0):
        return int(self._values.get(name, default))


class _FakeCrawler:
    def __init__(self, stats, settings):
        self.stats = _FakeStats(stats)
        self.settings = _FakeSettings(settings)


class _FakeSpider:
    def __init__(self, name):
        self.name = name


class TestSettingNames(unittest.TestCase):
    def test_min_items_setting_name(self):
        self.assertEqual(min_items_setting_name("afx_scraper"), "MIN_ITEMS_AFX_SCRAPER")
        self.assertEqual(
            min_items_setting_name("stockanalysis_scraper"),
            "MIN_ITEMS_STOCKANALYSIS_SCRAPER",
        )


class TestDataQualityGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.stats_dir = self._tmp.name

    def _run(self, spider_name, stats, settings, reason="finished"):
        crawler = _FakeCrawler(stats, settings)
        gate = DataQualityGate(crawler, self.stats_dir)
        gate.spider_closed(_FakeSpider(spider_name), reason)
        path = os.path.join(self.stats_dir, "{}-latest.json".format(spider_name))
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_zero_items_fails_when_threshold_set(self):
        report = self._run(
            "afx_scraper", {"item_scraped_count": 0}, {"MIN_ITEMS_AFX_SCRAPER": 40}
        )
        self.assertFalse(report["quality_ok"])
        self.assertEqual(report["item_scraped_count"], 0)
        self.assertEqual(len(report["failures"]), 1)

    def test_threshold_met_passes(self):
        report = self._run(
            "afx_scraper", {"item_scraped_count": 67}, {"MIN_ITEMS_AFX_SCRAPER": 40}
        )
        self.assertTrue(report["quality_ok"])
        self.assertEqual(report["failures"], [])

    def test_unconfigured_gate_is_inert(self):
        """CI sets no thresholds, so even a zero-item crawl must pass."""
        report = self._run("afx_scraper", {"item_scraped_count": 0}, {})
        self.assertTrue(report["quality_ok"])

    def test_items_scraped_but_all_writes_failed_fails(self):
        report = self._run(
            "stockanalysis_scraper",
            {"item_scraped_count": 63, DB_OK_STAT: 0, DB_FAILED_STAT: 63},
            {},
        )
        self.assertFalse(report["quality_ok"])
        self.assertIn("database writes failed", report["failures"][0])

    def test_partial_write_failures_do_not_fail_the_run(self):
        report = self._run(
            "stockanalysis_scraper",
            {"item_scraped_count": 63, DB_OK_STAT: 60, DB_FAILED_STAT: 3},
            {},
        )
        self.assertTrue(report["quality_ok"])

    def test_report_records_run_context(self):
        report = self._run(
            "stockanalysis_scraper",
            {
                "item_scraped_count": 75,
                "log_count/ERROR": 2,
                "retry/count": 4,
                "response_received_count": 10,
            },
            {"MIN_ITEMS_STOCKANALYSIS_SCRAPER": 60},
            reason="finished",
        )
        self.assertEqual(report["spider"], "stockanalysis_scraper")
        self.assertEqual(report["finish_reason"], "finished")
        self.assertEqual(report["min_items"], 60)
        self.assertEqual(report["log_count_error"], 2)
        self.assertEqual(report["retry_count"], 4)
        self.assertEqual(report["response_received_count"], 10)

    def test_timestamped_report_is_written_alongside_latest(self):
        self._run("afx_scraper", {"item_scraped_count": 1}, {})
        written = os.listdir(self.stats_dir)
        self.assertIn("afx_scraper-latest.json", written)
        self.assertTrue(
            any(f.startswith("afx_scraper-2") for f in written),
            "expected a timestamped report, got {}".format(written),
        )


if __name__ == "__main__":
    unittest.main()
