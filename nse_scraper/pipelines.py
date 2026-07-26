# useful for handling different item types with a single interface
import logging
from scrapy.exceptions import DropItem

from .db import create_backend
from .extensions import DB_FAILED_STAT, DB_OK_STAT

logger = logging.getLogger(__name__)

STOCKANALYSIS_VIEWS = ("overview", "performance", "dividends", "price", "profile")


class NseScraperPipeline:
    def __init__(
        self,
        db_backend,
        stock_table,
        supabase_url,
        supabase_key,
        supabase_table,
        stats=None,
    ):
        self.db_backend = db_backend
        self.stats = stats
        self.storage = create_backend(
            backend_name=db_backend,
            stock_table=stock_table,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            supabase_table=supabase_table,
        )

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            db_backend=crawler.settings.get("DB_BACKEND", "supabase"),
            stock_table=crawler.settings.get("STOCK_TABLE", "stock_data"),
            supabase_url=crawler.settings.get("SUPABASE_URL"),
            supabase_key=crawler.settings.get("SUPABASE_KEY"),
            supabase_table=crawler.settings.get("SUPABASE_TABLE", "stock_data"),
            # Retained so the data-quality gate can see whether writes succeeded.
            stats=crawler.stats,
        )

    def _record_write(self, written):
        if self.stats is None:
            return
        self.stats.inc_value(DB_OK_STAT if written else DB_FAILED_STAT)

    def open_spider(self, spider=None):
        """Called when spider is opened"""
        self.storage.open()
        logger.info("Storage backend active: %s", self.db_backend)

    def close_spider(self, spider=None):
        """Called when spider is closed"""
        self.storage.close()
        logger.info("Storage backend closed")

    def process_item(self, item, spider=None):
        """Process item and store to database"""
        try:
            # Validate required fields
            if not item.get('ticker_symbol'):
                raise DropItem(f'Missing ticker_symbol in {item}')
            if not item.get('stock_name'):
                raise DropItem(f'Missing stock_name in {item}')
            if item.get('stock_price') is None:
                raise DropItem(f'Missing stock_price in {item}')
            
            # Convert to dict
            data = dict(item)
            
            # Replace or insert the document
            self._record_write(self.storage.upsert_stock(data))
            logger.debug(f"Upserted stock data for {data['ticker_symbol']}")
            
            return item
            
        except DropItem as e:
            logger.warning(f"Dropped item: {e}")
            raise
        except Exception as e:
            logger.error(f"Error processing item: {e}", exc_info=True)
            raise DropItem(f"Failed to process item: {e}")


class StockAnalysisPipeline:
    """Groups per-view StockAnalysis items by ticker_symbol and upserts one row per stock to Supabase."""

    def __init__(self, db_backend, supabase_url, supabase_key, stockanalysis_table, stats=None):
        self.db_backend = (db_backend or "").strip().lower()
        self.stockanalysis_table = stockanalysis_table
        self.stats = stats
        self.storage = None
        if self.db_backend == "supabase":
            self.storage = create_backend(
                backend_name="supabase",
                supabase_url=supabase_url,
                supabase_key=supabase_key,
                supabase_table="stock_data",
                stockanalysis_table=stockanalysis_table,
            )
        self._buffer = {}

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            db_backend=crawler.settings.get("DB_BACKEND"),
            supabase_url=crawler.settings.get("SUPABASE_URL"),
            supabase_key=crawler.settings.get("SUPABASE_KEY"),
            stockanalysis_table=crawler.settings.get("STOCKANALYSIS_TABLE", "stockanalysis_stocks"),
            # Retained so the data-quality gate can see whether writes succeeded.
            stats=crawler.stats,
        )

    def _record_write(self, written):
        if self.stats is None:
            return
        self.stats.inc_value(DB_OK_STAT if written else DB_FAILED_STAT)

    def open_spider(self, spider=None):
        if self.storage:
            self.storage.open()
            logger.info("StockAnalysisPipeline: Supabase storage active")

    def close_spider(self, spider=None):
        if self.storage and self._buffer:
            for ticker_symbol, views in list(self._buffer.items()):
                self._upsert_one(ticker_symbol, views)
            self._buffer.clear()
        if self.storage:
            self.storage.close()

    def _upsert_one(self, ticker_symbol, views):
        """Build one normalized record from view dict and upsert."""
        # Prefer overview for common fields; fallback to first available
        prefer = views.get("overview") or next(iter(views.values()), None)
        if not prefer:
            return
        item = dict(prefer) if hasattr(prefer, "keys") else prefer
        scraped_at = item.get("scraped_at")
        if hasattr(scraped_at, "isoformat"):
            scraped_at = scraped_at.isoformat()
        record = {
            "ticker_symbol": ticker_symbol,
            "company_name": item.get("company_name") or item.get("stock_name") or "",
            "rank": item.get("rank"),
            "stock_price": item.get("stock_price"),
            "stock_change": item.get("stock_change"),
            "scraped_at": scraped_at,
            "overview_metrics": None,
            "performance_metrics": None,
            "dividends_metrics": None,
            "price_metrics": None,
            "profile_metrics": None,
        }
        for view_name in STOCKANALYSIS_VIEWS:
            v = views.get(view_name)
            if v is None:
                continue
            raw = v.get("metrics_raw") or v.get("metrics") or {}
            if view_name == "overview":
                record["overview_metrics"] = {k: raw[k] for k in raw if k not in ("price", "change")}
            elif view_name == "price":
                record["price_metrics"] = {k: raw[k] for k in raw if k not in ("price", "change")}
            else:
                record[f"{view_name}_metrics"] = dict(raw)
        try:
            self._record_write(self.storage.upsert_stockanalysis_stock(record))
            logger.debug(
                "Upserted stockanalysis_stocks: %s (views: %s)",
                ticker_symbol,
                ",".join(sorted(v for v in STOCKANALYSIS_VIEWS if views.get(v))) or "none",
            )
        except Exception as e:
            self._record_write(False)
            logger.error("Failed to upsert stockanalysis_stocks %s: %s", ticker_symbol, e, exc_info=True)

    def process_item(self, item, spider=None):
        if getattr(item, "get", None) is None:
            item = dict(item)
        source = item.get("source")
        view = item.get("view")
        ticker = item.get("ticker_symbol") or item.get("symbol")
        if source != "stockanalysis" or not view or not ticker:
            return item
        if view not in STOCKANALYSIS_VIEWS:
            return item
        if not self.storage:
            return item
        # Buffered until close_spider rather than flushed as soon as all five views
        # arrive: views now come from separate per-symbol pages, and a straggler
        # arriving after an eager flush would re-upsert a thinner record.
        views = self._buffer.setdefault(ticker, {})
        existing = views.get(view)
        views[view] = self._merge_view(existing, item) if existing else item
        return item

    @staticmethod
    def _merge_view(existing, item):
        """Combine two items for the same view, keeping values already populated.

        A view can be assembled from more than one page (profile comes from both the
        quote and company pages), and arrival order is not guaranteed, so neither
        contributor may blank the other's fields.
        """
        merged = dict(existing)
        for key in ("metrics_raw", "metrics"):
            combined = dict(existing.get(key) or {})
            for name, value in (item.get(key) or {}).items():
                if value is not None or name not in combined:
                    combined[name] = value
            merged[key] = combined
        for key, value in item.items():
            if key not in ("metrics_raw", "metrics") and merged.get(key) is None:
                merged[key] = value
        return merged
