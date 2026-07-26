import os
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = 'nse_scraper'

SPIDER_MODULES = ['nse_scraper.spiders']
NEWSPIDER_MODULE = 'nse_scraper.spiders'

# Supabase-only storage configuration
DB_BACKEND = os.getenv("DB_BACKEND", "supabase").strip().lower()
STOCK_TABLE = os.getenv("STOCK_TABLE", "stock_data")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", STOCK_TABLE)
STOCKANALYSIS_TABLE = os.getenv("STOCKANALYSIS_TABLE", "stockanalysis_stocks")

# Item pipelines
ITEM_PIPELINES = {
    'nse_scraper.pipelines.NseScraperPipeline': 300,
}

# Extensions
EXTENSIONS = {
    'nse_scraper.extensions.DataQualityGate': 500,
}

# Downloader middlewares (proxy injection is a no-op unless AFX_PROXY_URL is set)
DOWNLOADER_MIDDLEWARES = {
    'nse_scraper.middlewares.NseScraperDownloaderMiddleware': 543,
}

# Data-quality gate: minimum acceptable item count per spider.
# Scrapy exits 0 even when a spider scrapes nothing, so these thresholds are what
# turn a silent no-data run into RUN_STATUS FAILED. Default 0 (gate off) so CI and
# ad-hoc runs are unaffected; the daily job sets real values via .env.
MIN_ITEMS_AFX_SCRAPER = int(os.getenv("MIN_ITEMS_AFX_SCRAPER", "0"))
MIN_ITEMS_STOCKANALYSIS_SCRAPER = int(os.getenv("MIN_ITEMS_STOCKANALYSIS_SCRAPER", "0"))
QUALITY_STATS_DIR = os.getenv("QUALITY_STATS_DIR", "reports/stats")

# Optional outbound proxy for afx_scraper only (afx.kwayisi.org blocks this host).
# Empty means no proxy and completely unchanged behaviour.
AFX_PROXY_URL = os.getenv("AFX_PROXY_URL", "").strip()

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = '%(asctime)s [%(name)s] %(levelname)s: %(message)s'

# Obey robots.txt rules
ROBOTSTXT_OBEY = False

# User agent
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# Request settings
DEFAULT_REQUEST_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
}

# Concurrent requests (be respectful)
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# Download delay (be respectful to target server)
DOWNLOAD_DELAY = 1

# HTTP Cache settings
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 3600  # Cache for 1 hour instead of 6 minutes
HTTPCACHE_DIR = 'httpcache'
HTTPCACHE_STORAGE = 'scrapy.extensions.httpcache.FilesystemCacheStorage'

# Retry settings
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Fail fast on unreachable hosts. Scrapy's default of 180s meant an unreachable
# host burned ~9 minutes per run across retries before giving up.
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "30"))

# AutoThrottle: stockanalysis_scraper now fetches several pages per ticker, so
# adapt the delay to the server's response times instead of hammering a fixed rate.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 20
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
