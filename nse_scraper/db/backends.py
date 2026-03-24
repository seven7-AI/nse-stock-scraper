import logging
from datetime import datetime, timezone
import json
import os

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


class SupabaseBackend:
    def __init__(self, supabase_url, supabase_key, supabase_table, stockanalysis_table="stockanalysis_stocks"):
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY are required when DB_BACKEND=supabase")
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.supabase_table = supabase_table
        self.stockanalysis_table = stockanalysis_table
        self.client = None
        # Local fallback directory for failed Supabase writes (relative to CWD)
        self.local_fallback_dir = "reports/local_fallback"

    def open(self):
        from supabase import create_client

        self.client = create_client(self.supabase_url, self.supabase_key)
        logger.info("Supabase backend ready")

    def close(self):
        return None

    def _ensure_local_dir(self):
        if not self.local_fallback_dir:
            return
        try:
            os.makedirs(self.local_fallback_dir, exist_ok=True)
        except Exception:
            logger.exception("Failed to create local fallback directory %s", self.local_fallback_dir)

    def _write_local_fallback(self, kind, payload):
        """Write a failed Supabase payload to local JSONL for later inspection/replay."""
        if not self.local_fallback_dir:
            return
        self._ensure_local_dir()
        try:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filename = f"{kind}_fallback-{date_str}.jsonl"
            path = os.path.join(self.local_fallback_dir, filename)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, default=str) + "\n")
        except Exception:
            logger.exception("Failed to write local fallback record for %s", kind)

    def upsert_stockanalysis_stock(self, record):
        """Upsert one normalized stock record (all tab data) into stockanalysis_stocks, updating existing records."""
        scraped_at = record.get("scraped_at")
        if scraped_at is None:
            scraped_at = datetime.now(timezone.utc)
        if hasattr(scraped_at, "isoformat"):
            scraped_at = scraped_at.isoformat()
        
        # Get existing record to preserve price_history
        existing = None
        try:
            response = self.client.table(self.stockanalysis_table).select("price_history, stock_price, stock_change").eq("ticker_symbol", record["ticker_symbol"]).execute()
            if response.data:
                existing = response.data[0]
        except Exception:
            existing = None
        
        # Build price_history entry
        history_entry = {
            "scraped_at": scraped_at,
            "stock_price": float(record["stock_price"]) if record.get("stock_price") is not None else None,
            "stock_change": float(record["stock_change"]) if record.get("stock_change") is not None else None,
        }
        
        # Append to existing history or create new array
        price_history = existing.get("price_history", []) if existing else []
        if not isinstance(price_history, list):
            price_history = []
        
        # Only add if price or change actually changed (avoid duplicates)
        if not price_history or price_history[-1].get("stock_price") != history_entry["stock_price"] or price_history[-1].get("stock_change") != history_entry["stock_change"]:
            price_history.append(history_entry)
        
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
            "price_history": price_history,
        }
        # Use upsert to update existing records or insert new ones.
        # On Supabase failure, write a local fallback record.
        try:
            self.client.table(self.stockanalysis_table).upsert(payload, on_conflict="ticker_symbol").execute()
        except Exception:
            logger.exception("Supabase upsert_stockanalysis_stock failed; writing local fallback")
            self._write_local_fallback("stockanalysis_stocks", payload)

    def upsert_stock(self, record):
        payload = _normalize_record(record)
        scraped_at = payload.get("scraped_at")
        if scraped_at is None:
            scraped_at = payload.get("created_at", datetime.now(timezone.utc))
        if hasattr(scraped_at, "isoformat"):
            scraped_at_iso = scraped_at.isoformat()
        else:
            scraped_at_iso = scraped_at
        
        # Get existing record to preserve price_history
        existing = None
        try:
            response = self.client.table(self.supabase_table).select("price_history, stock_price, stock_change").eq("ticker_symbol", payload["ticker_symbol"]).execute()
            if response.data:
                existing = response.data[0]
        except Exception:
            existing = None
        
        # Build price_history entry
        history_entry = {
            "scraped_at": scraped_at_iso,
            "stock_price": float(payload["stock_price"]),
            "stock_change": float(payload["stock_change"]) if payload.get("stock_change") is not None else None,
        }
        
        # Append to existing history or create new array
        price_history = existing.get("price_history", []) if existing else []
        if not isinstance(price_history, list):
            price_history = []
        
        # Only add if price or change actually changed (avoid duplicates)
        if not price_history or price_history[-1].get("stock_price") != history_entry["stock_price"] or price_history[-1].get("stock_change") != history_entry["stock_change"]:
            price_history.append(history_entry)
        
        serialized = {
            "ticker_symbol": payload["ticker_symbol"],
            "stock_name": payload["stock_name"],
            "stock_price": float(payload["stock_price"]),
            "stock_change": float(payload["stock_change"]) if payload.get("stock_change") is not None else None,
            "scraped_at": scraped_at_iso,
            "created_at": payload["created_at"].isoformat() if hasattr(payload["created_at"], "isoformat") else payload["created_at"],
            "price_history": price_history,
        }
        # Use upsert to update existing records or insert new ones.
        # On Supabase failure, write a local fallback record.
        try:
            self.client.table(self.supabase_table).upsert(serialized, on_conflict="ticker_symbol").execute()
        except Exception:
            logger.exception("Supabase upsert_stock failed; writing local fallback")
            self._write_local_fallback("stock_data", serialized)

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
    stock_table="stock_data",
    supabase_url=None,
    supabase_key=None,
    supabase_table="stock_data",
    stockanalysis_table="stockanalysis_stocks",
):
    backend = backend_name.strip().lower()
    if backend == "supabase":
        return SupabaseBackend(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            supabase_table=supabase_table,
            stockanalysis_table=stockanalysis_table,
        )
    raise ValueError("Unsupported DB_BACKEND. Use: supabase")
