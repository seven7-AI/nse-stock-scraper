# useful for handling different item types with a single interface
import logging
from scrapy.exceptions import DropItem

from .db import create_backend

logger = logging.getLogger(__name__)

STOCKANALYSIS_VIEWS = ("overview", "performance", "dividends", "price", "profile")


class NseScraperPipeline:
    def __init__(
        self,
        db_backend,
        mongodb_uri,
        mongo_db,
        stock_table,
        sql_database_url,
        sql_echo,
        supabase_url,
        supabase_key,
        supabase_table,
    ):
        self.db_backend = db_backend
        self.storage = create_backend(
            backend_name=db_backend,
            mongodb_uri=mongodb_uri,
            mongo_database=mongo_db,
            stock_table=stock_table,
            sql_database_url=sql_database_url,
            sql_echo=sql_echo,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            supabase_table=supabase_table,
        )

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            db_backend=crawler.settings.get("DB_BACKEND", "mongo"),
            mongodb_uri=crawler.settings.get("MONGODB_URI"),
            mongo_db=crawler.settings.get("MONGO_DATABASE", "nse_data"),
            stock_table=crawler.settings.get("STOCK_TABLE", "stock_data"),
            sql_database_url=crawler.settings.get("SQL_DATABASE_URL"),
            sql_echo=crawler.settings.get("SQL_ECHO", False),
            supabase_url=crawler.settings.get("SUPABASE_URL"),
            supabase_key=crawler.settings.get("SUPABASE_KEY"),
            supabase_table=crawler.settings.get("SUPABASE_TABLE", "stock_data"),
        )

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
            self.storage.upsert_stock(data)
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

    def __init__(self, db_backend, supabase_url, supabase_key, stockanalysis_table):
        self.db_backend = (db_backend or "").strip().lower()
        self.stockanalysis_table = stockanalysis_table
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
        )

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
            self.storage.upsert_stockanalysis_stock(record)
            logger.debug("Upserted stockanalysis_stocks: %s", ticker_symbol)
        except Exception as e:
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
        self._buffer.setdefault(ticker, {})[view] = item
        if len(self._buffer[ticker]) == len(STOCKANALYSIS_VIEWS):
            self._upsert_one(ticker, self._buffer.pop(ticker))
        return item
