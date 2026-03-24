import logging
import os
from dotenv import load_dotenv

try:
    from nse_scraper.db import create_backend
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from db import create_backend

load_dotenv()

logger = logging.getLogger(__name__)

DB_BACKEND = os.getenv("DB_BACKEND", "supabase").strip().lower()
STOCK_TABLE = os.getenv("STOCK_TABLE", "stock_data")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", STOCK_TABLE)


def stock_query(ticker_symbol="BAT", threshold=38.0):
    """
    Placeholder utility: query latest stock price from selected backend.
    Messaging and schedulers are intentionally disabled in this project.
    """
    backend = None
    try:
        backend = create_backend(
            backend_name=DB_BACKEND,
            stock_table=STOCK_TABLE,
            supabase_url=SUPABASE_URL,
            supabase_key=SUPABASE_KEY,
            supabase_table=SUPABASE_TABLE,
        )
        backend.open()

        ticker_data = backend.get_latest_by_ticker(ticker_symbol)
        if not ticker_data:
            logger.warning("No data found for ticker %s", ticker_symbol)
            return None

        stock_name = ticker_data.get("stock_name")
        stock_price = ticker_data.get("stock_price")

        if not stock_name or stock_price is None:
            logger.warning("Incomplete data for %s: %s", ticker_symbol, ticker_data)
            return None

        sms_data = {"stock_name": stock_name, "stock_price": stock_price}
        logger.info("Retrieved stock data: %s", sms_data)

        if float(stock_price) >= float(threshold):
            logger.info(
                "Threshold met (%s >= %s). Notifications are disabled; no message sent.",
                stock_price,
                threshold,
            )
        else:
            logger.info("Threshold not met (%s < %s).", stock_price, threshold)
        return sms_data
    except Exception as e:
        logger.error("Error in stock_query: %s", e, exc_info=True)
        return None
    finally:
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    stock_query()
