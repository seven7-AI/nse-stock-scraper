import logging
from datetime import datetime, timezone

import pymongo
from sqlalchemy import create_engine, desc
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from .models import Base, StockData

logger = logging.getLogger(__name__)


def _normalize_record(record):
    normalized = dict(record)
    created_at = normalized.get("created_at")
    if created_at is None:
        normalized["created_at"] = datetime.now(timezone.utc)
    elif isinstance(created_at, datetime) and created_at.tzinfo is None:
        normalized["created_at"] = created_at.replace(tzinfo=timezone.utc)
    # Ensure scraped_at exists for historical tracking
    scraped_at = normalized.get("scraped_at")
    if scraped_at is None:
        normalized["scraped_at"] = normalized["created_at"]
    elif isinstance(scraped_at, datetime) and scraped_at.tzinfo is None:
        normalized["scraped_at"] = scraped_at.replace(tzinfo=timezone.utc)
    return normalized


class MongoBackend:
    def __init__(self, mongodb_uri, mongo_database, stock_table):
        if not mongodb_uri:
            raise ValueError("MONGODB_URI is required when DB_BACKEND=mongo")
        self.mongodb_uri = mongodb_uri
        self.mongo_database = mongo_database
        self.stock_table = stock_table
        self.client = None
        self.db = None

    def open(self):
        self.client = pymongo.MongoClient(self.mongodb_uri)
        self.db = self.client[self.mongo_database]
        self.db[self.stock_table].create_index([("ticker_symbol", pymongo.ASCENDING)], unique=True)
        logger.info("MongoDB backend ready")

    def close(self):
        if self.client:
            self.client.close()

    def upsert_stock(self, record):
        payload = _normalize_record(record)
        self.db[self.stock_table].replace_one(
            {"ticker_symbol": payload["ticker_symbol"]},
            payload,
            upsert=True,
        )

    def get_latest_by_ticker(self, ticker_symbol):
        return self.db[self.stock_table].find_one(
            {"ticker_symbol": ticker_symbol},
            sort=[("created_at", -1)],
        )


class PostgresBackend:
    def __init__(self, sql_database_url, stock_table="stock_data", sql_echo=False):
        if not sql_database_url:
            raise ValueError("SQL_DATABASE_URL is required when DB_BACKEND=postgres")
        self.sql_database_url = sql_database_url
        self.stock_table = stock_table
        self.sql_echo = sql_echo
        self.engine = None
        self.Session = None

    def open(self):
        self.engine = create_engine(self.sql_database_url, echo=self.sql_echo, future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)
        logger.info("PostgreSQL backend ready")

    def close(self):
        if self.engine:
            self.engine.dispose()

    def upsert_stock(self, record):
        payload = _normalize_record(record)
        with self.engine.begin() as conn:
            stmt = pg_insert(StockData).values(
                ticker_symbol=payload["ticker_symbol"],
                stock_name=payload["stock_name"],
                stock_price=float(payload["stock_price"]),
                stock_change=float(payload["stock_change"]) if payload.get("stock_change") is not None else None,
                created_at=payload["created_at"],
            )
            update_values = {
                "stock_name": stmt.excluded.stock_name,
                "stock_price": stmt.excluded.stock_price,
                "stock_change": stmt.excluded.stock_change,
                "created_at": stmt.excluded.created_at,
            }
            conn.execute(stmt.on_conflict_do_update(index_elements=["ticker_symbol"], set_=update_values))

    def get_latest_by_ticker(self, ticker_symbol):
        with self.Session() as session:
            record = (
                session.query(StockData)
                .filter(StockData.ticker_symbol == ticker_symbol)
                .order_by(desc(StockData.created_at))
                .first()
            )
            if record is None:
                return None
            return {
                "ticker_symbol": record.ticker_symbol,
                "stock_name": record.stock_name,
                "stock_price": record.stock_price,
                "stock_change": record.stock_change,
                "created_at": record.created_at,
            }


class SupabaseBackend:
    def __init__(self, supabase_url, supabase_key, supabase_table, stockanalysis_table="stockanalysis_stocks"):
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY are required when DB_BACKEND=supabase")
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.supabase_table = supabase_table
        self.stockanalysis_table = stockanalysis_table
        self.client = None

    def open(self):
        from supabase import create_client

        self.client = create_client(self.supabase_url, self.supabase_key)
        logger.info("Supabase backend ready")

    def close(self):
        return None

    def upsert_stockanalysis_stock(self, record):
        """Insert one normalized stock record (all tab data) into stockanalysis_stocks for historical tracking."""
        scraped_at = record.get("scraped_at")
        if scraped_at is None:
            scraped_at = datetime.now(timezone.utc)
        if hasattr(scraped_at, "isoformat"):
            scraped_at = scraped_at.isoformat()
        payload = {
            "ticker_symbol": record["ticker_symbol"],
            "company_name": record["company_name"],
            "rank": record.get("rank"),
            "stock_price": float(record["stock_price"]) if record.get("stock_price") is not None else None,
            "stock_change": float(record["stock_change"]) if record.get("stock_change") is not None else None,
            "scraped_at": scraped_at,
            "overview_metrics": record.get("overview_metrics"),
            "performance_metrics": record.get("performance_metrics"),
            "dividends_metrics": record.get("dividends_metrics"),
            "price_metrics": record.get("price_metrics"),
            "profile_metrics": record.get("profile_metrics"),
        }
        # Use insert instead of upsert to preserve historical data
        # Composite primary key (ticker_symbol, scraped_at) prevents duplicates
        self.client.table(self.stockanalysis_table).insert(payload).execute()

    def upsert_stock(self, record):
        payload = _normalize_record(record)
        scraped_at = payload.get("scraped_at")
        if scraped_at is None:
            scraped_at = payload.get("created_at", datetime.now(timezone.utc))
        if hasattr(scraped_at, "isoformat"):
            scraped_at_iso = scraped_at.isoformat()
        else:
            scraped_at_iso = scraped_at
        serialized = {
            "ticker_symbol": payload["ticker_symbol"],
            "stock_name": payload["stock_name"],
            "stock_price": float(payload["stock_price"]),
            "stock_change": float(payload["stock_change"]) if payload.get("stock_change") is not None else None,
            "scraped_at": scraped_at_iso,
            "created_at": payload["created_at"].isoformat() if hasattr(payload["created_at"], "isoformat") else payload["created_at"],
        }
        # Use insert instead of upsert to preserve historical data
        # Composite primary key (ticker_symbol, scraped_at) prevents duplicates
        self.client.table(self.supabase_table).insert(serialized).execute()

    def get_latest_by_ticker(self, ticker_symbol):
        response = (
            self.client.table(self.supabase_table)
            .select("ticker_symbol,stock_name,stock_price,stock_change,created_at")
            .eq("ticker_symbol", ticker_symbol)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]


def create_backend(
    backend_name,
    mongodb_uri=None,
    mongo_database="nse_data",
    stock_table="stock_data",
    sql_database_url=None,
    sql_echo=False,
    supabase_url=None,
    supabase_key=None,
    supabase_table="stock_data",
    stockanalysis_table="stockanalysis_stocks",
):
    backend = backend_name.strip().lower()
    if backend == "mongo":
        return MongoBackend(mongodb_uri=mongodb_uri, mongo_database=mongo_database, stock_table=stock_table)
    if backend == "postgres":
        return PostgresBackend(
            sql_database_url=sql_database_url,
            stock_table=stock_table,
            sql_echo=sql_echo,
        )
    if backend == "supabase":
        return SupabaseBackend(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            supabase_table=supabase_table,
            stockanalysis_table=stockanalysis_table,
        )
    raise ValueError("Unsupported DB_BACKEND. Use one of: mongo, postgres, supabase")
