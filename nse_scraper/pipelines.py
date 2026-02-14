# useful for handling different item types with a single interface
import logging
from scrapy.exceptions import DropItem

from .db import create_backend

logger = logging.getLogger(__name__)


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

    def open_spider(self, spider):
        """Called when spider is opened"""
        self.storage.open()
        logger.info("Storage backend active: %s", self.db_backend)

    def close_spider(self, spider):
        """Called when spider is closed"""
        self.storage.close()
        logger.info("Storage backend closed")
    
    def process_item(self, item, spider):
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
