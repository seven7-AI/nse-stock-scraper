"""Scrapy extensions for run-quality reporting.

The daily job historically reported SUCCESS whenever Scrapy exited 0, but Scrapy
exits 0 even when a spider scrapes nothing at all. This extension records the
outcome of every crawl to a machine-readable JSON file that ``scripts/run_daily_job.sh``
reads to decide RUN_STATUS, so a run that silently scrapes nothing (or fails every
database write) is reported FAILED instead of SUCCESS.
"""

import json
import logging
import os
from datetime import datetime, timezone

from scrapy import signals

logger = logging.getLogger(__name__)

# Stats keys incremented by the pipelines when a Supabase write succeeds/fails.
DB_OK_STAT = "nse/db_upsert_ok"
DB_FAILED_STAT = "nse/db_upsert_failed"
# Financial-statement pages stored / failed (stockanalysis_scraper only). Reported,
# and a run where every statement write failed is a gate failure like the above.
FINANCIALS_OK_STAT = "nse_scraper/financials_ok"
FINANCIALS_FAILED_STAT = "nse_scraper/financials_failed"
# Rows stored with / without a usable price, incremented by StockAnalysisPipeline.
# db_upsert_ok counts rows that reached the database, which stays high even when the
# source stops publishing the one field this pipeline exists to deliver: from
# 2026-11-06 stockanalysis.com served every NSE listing with a null price, and the
# gate reported SUCCESS for a week while stock_observations went nowhere.
PRICE_PRESENT_STAT = "nse/price_present"
PRICE_NULL_STAT = "nse/price_null"


def min_items_setting_name(spider_name):
    """Setting name holding the minimum acceptable item count for a spider.

    ``afx_scraper`` -> ``MIN_ITEMS_AFX_SCRAPER``
    """
    return "MIN_ITEMS_{}".format(spider_name.upper())


class DataQualityGate:
    """Writes per-crawl quality stats and flags runs that scraped too little."""

    def __init__(self, crawler, stats_dir):
        self.crawler = crawler
        self.stats_dir = stats_dir

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler, crawler.settings.get("QUALITY_STATS_DIR", "reports/stats"))
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_closed(self, spider, reason):
        stats = self.crawler.stats.get_stats() or {}
        item_count = stats.get("item_scraped_count", 0) or 0
        min_items = self.crawler.settings.getint(min_items_setting_name(spider.name), 0)
        db_ok = stats.get(DB_OK_STAT, 0) or 0
        db_failed = stats.get(DB_FAILED_STAT, 0) or 0
        requests_made = stats.get("downloader/request_count", 0) or 0
        responses = stats.get("response_received_count", 0) or 0
        price_present = stats.get(PRICE_PRESENT_STAT, 0) or 0
        price_null = stats.get(PRICE_NULL_STAT, 0) or 0

        failures = []
        # A crawl that asked for pages and got none back is an unreachable source, not
        # an empty one. Keyed on requests rather than on the response count alone so a
        # run that never crawled (CI, a disabled spider) stays inert - see
        # test_unconfigured_gate_is_inert. afx_scraper sat at 4 requests / 0 responses
        # for three weeks of TimeoutError while reporting quality_ok.
        if requests_made and not responses:
            failures.append(
                "made {} request(s) and received no response: the source was "
                "unreachable, not empty".format(requests_made)
            )
        # Rows can be written in full while the price field is null for every one of
        # them. Counting writes cannot see that; counting the field can.
        if price_null and not price_present:
            failures.append(
                "stored {} row(s) and not one carried a price: the source stopped "
                "publishing it".format(price_null)
            )
        if item_count < min_items:
            failures.append(
                "scraped {} items, below minimum of {}".format(item_count, min_items)
            )
        # Writes are swallowed into a local JSONL fallback, so a crawl can look
        # healthy while nothing reached the database. Treat that as a failure.
        if db_failed and not db_ok:
            failures.append(
                "all {} database writes failed (see reports/local_fallback)".format(db_failed)
            )
        financials_ok = stats.get(FINANCIALS_OK_STAT, 0) or 0
        financials_failed = stats.get(FINANCIALS_FAILED_STAT, 0) or 0
        if financials_failed and not financials_ok:
            failures.append(
                "all {} financial-statement writes failed (see reports/local_fallback)".format(
                    financials_failed
                )
            )

        report = {
            "spider": spider.name,
            "finish_reason": reason,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "item_scraped_count": item_count,
            "min_items": min_items,
            "db_upsert_ok": db_ok,
            "db_upsert_failed": db_failed,
            "financials_ok": financials_ok,
            "financials_failed": financials_failed,
            "price_present": price_present,
            "price_null": price_null,
            "log_count_error": stats.get("log_count/ERROR", 0) or 0,
            "retry_count": stats.get("retry/count", 0) or 0,
            "request_count": requests_made,
            "response_received_count": responses,
            "quality_ok": not failures,
            "failures": failures,
        }

        self._write(spider.name, report)

        if failures:
            logger.error(
                "Data quality gate FAILED for %s: %s", spider.name, "; ".join(failures)
            )
        else:
            logger.info(
                "Data quality gate passed for %s: %s items (minimum %s)",
                spider.name,
                item_count,
                min_items,
            )

    def _write(self, spider_name, report):
        """Write a timestamped report plus a stable ``-latest.json`` the shell reads."""
        try:
            os.makedirs(self.stats_dir, exist_ok=True)
        except Exception:
            logger.exception("Could not create stats directory %s", self.stats_dir)
            return

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        payload = json.dumps(report, indent=2, default=str)
        for filename in (
            "{}-{}.json".format(spider_name, stamp),
            "{}-latest.json".format(spider_name),
        ):
            path = os.path.join(self.stats_dir, filename)
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(payload + "\n")
            except Exception:
                logger.exception("Could not write quality report to %s", path)
