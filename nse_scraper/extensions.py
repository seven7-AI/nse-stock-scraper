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

        failures = []
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

        report = {
            "spider": spider.name,
            "finish_reason": reason,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "item_scraped_count": item_count,
            "min_items": min_items,
            "db_upsert_ok": db_ok,
            "db_upsert_failed": db_failed,
            "log_count_error": stats.get("log_count/ERROR", 0) or 0,
            "retry_count": stats.get("retry/count", 0) or 0,
            "response_received_count": stats.get("response_received_count", 0) or 0,
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
