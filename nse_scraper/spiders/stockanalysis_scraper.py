import json
import logging
import os
import re
from datetime import datetime, timezone

from scrapy import Request, Spider

from .. import stockanalysis_pages
from ..db import SUPPORTED_BACKENDS


logger = logging.getLogger(__name__)


def _stockanalysis_pipelines():
    """Install StockAnalysisPipeline whenever a supported backend is configured.

    Tested against SUPPORTED_BACKENDS rather than a literal backend name. When this read
    "== supabase" it silently installed no pipeline under any other backend: items were
    dropped, db_upsert_ok and db_upsert_failed both stayed 0, and the quality gate --
    which only fails on `db_failed and not db_ok` -- reported SUCCESS for a run that
    stored nothing.

    Note this reads the environment at import time, so `-s DB_BACKEND=...` on the command
    line does not affect it; the environment variable does.
    """
    if os.getenv("DB_BACKEND", "sqlite").strip().lower() in SUPPORTED_BACKENDS:
        return {"nse_scraper.pipelines.StockAnalysisPipeline": 300}
    return {}


class StockAnalysisScraperSpider(Spider):
    name = "stockanalysis_scraper"
    allowed_domains = ["stockanalysis.com"]
    start_urls = ["https://stockanalysis.com/list/nairobi-stock-exchange/"]
    # Enriching every ticker means a few hundred requests per run instead of one, and
    # the site starts returning 403 well before that at the project-wide rate. These
    # settings are scoped to this spider so afx_scraper is unaffected.
    custom_settings = {
        "ITEM_PIPELINES": _stockanalysis_pipelines(),
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": float(os.getenv("STOCKANALYSIS_DOWNLOAD_DELAY", "2")),
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 2,
        "AUTOTHROTTLE_MAX_DELAY": 15,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
        # 403 is deliberately NOT retried. It signals an active rate limit, and
        # retrying turned one blocked run into 353 blocked requests that both wasted
        # 16 minutes and deepened the block. Fewer requests per run is the fix.
        "RETRY_HTTP_CODES": [500, 502, 503, 504, 408, 429],
        "RETRY_TIMES": 2,
    }
    # How many symbols to enrich per run. The site rate-limits a full-catalogue crawl
    # (a 126-request run drew 353 x 403 and only 36 successes), so each run refreshes a
    # rotating slice instead and the whole list is covered every few days. That suits
    # the enriched fields -- dividends, profile and 52-week range move slowly -- while
    # price and change still refresh daily for every ticker from the list page.
    # 0 disables the cap and enriches everything in one run.
    _MAX_SYMBOLS = int(os.getenv("STOCKANALYSIS_MAX_SYMBOLS", "16"))
    # Which per-symbol pages to fetch. Dropping "company" removes a third of the
    # requests and loses only `country`, since the quote page carries the other
    # profile fields -- worth it if the site starts rate-limiting a full crawl.
    _SYMBOL_PAGES = tuple(
        page.strip()
        for page in os.getenv(
            "STOCKANALYSIS_SYMBOL_PAGES",
            ",".join(stockanalysis_pages.DEFAULT_SYMBOL_PAGES),
        ).split(",")
        if page.strip()
    )
    _TARGET_VIEW_COLUMNS = {
        "overview": [
            "no",
            "s",
            "n",
            "marketCap",
            "price",
            "change",
            "revenue",
            "volume",
            "industry",
            "sector",
            "revenueGrowth",
            "netIncome",
            "fcf",
            "netCash",
        ],
        "performance": ["no", "s", "tr1m", "tr6m", "trYTD", "tr1y", "tr5y", "tr10y"],
        "dividends": [
            "no",
            "s",
            "dps",
            "dividendYield",
            "dividendGrowth",
            "exDivDate",
            "payoutRatio",
            "payoutFrequency",
        ],
        "price": [
            "no",
            "s",
            "price",
            "change",
            "volume",
            "low52",
            "low52ch",
            "high52",
            "high52ch",
        ],
        "profile": ["no", "s", "n", "industry", "country", "employees", "founded"],
    }

    _KEYWORDS_TO_NULL = {"", "-", "--", "n/a", "na", "null", "none"}
    _UNIT_MULTIPLIERS = {
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "T": 1_000_000_000_000,
    }

    def parse(self, response):
        stock_data, view_map, stock_query = self._extract_embedded_payload(response.text)
        scraped_at = datetime.now(timezone.utc).isoformat()

        if stock_data and view_map:
            if stock_query and self._needs_symbol_page_enrichment(stock_data):
                base_by_symbol = {}
                for row in stock_data:
                    symbol = self._extract_symbol(row.get("s"))
                    if symbol:
                        base_by_symbol[symbol] = row

                # Always emit overview from embedded payload so partial data is still stored
                # even if one of the API view requests fails.
                for row in stock_data:
                    symbol = self._extract_symbol(row.get("s"))
                    if not symbol:
                        continue
                    metrics_raw = {}
                    metrics = {}
                    for column_id in self._TARGET_VIEW_COLUMNS["overview"]:
                        if column_id in {"no", "s", "n"}:
                            continue
                        raw_value = row.get(column_id)
                        metrics_raw[column_id] = raw_value
                        metrics[column_id] = self._normalize_metric_value(raw_value)
                    yield {
                        "source": "stockanalysis",
                        "view": "overview",
                        "symbol": symbol,
                        "ticker_symbol": symbol,
                        "rank": row.get("no"),
                        "company_name": row.get("n"),
                        "stock_name": row.get("n"),
                        "stock_price": row.get("price"),
                        "stock_change": row.get("change"),
                        "created_at": scraped_at,
                        "metrics_raw": metrics_raw,
                        "metrics": metrics,
                        "scraped_at": scraped_at,
                    }

                # The screener API that used to serve the other four views is gone
                # (404 on every variant), so they are rebuilt from the per-symbol
                # pages, which are still server-rendered.
                symbols = self._symbols_for_this_run(list(base_by_symbol))

                for symbol in symbols:
                    for page in self._SYMBOL_PAGES:
                        yield Request(
                            url=stockanalysis_pages.symbol_page_url(symbol, page),
                            callback=self._parse_symbol_page,
                            errback=self._handle_symbol_page_error,
                            cb_kwargs={
                                "symbol": symbol,
                                "page": page,
                                "base": base_by_symbol.get(symbol, {}),
                                "scraped_at": scraped_at,
                            },
                        )
                return

            logger.info(
                "Parsed embedded payload: %s rows across %s views",
                len(stock_data),
                len(view_map),
            )
            for view_name, view_ids in view_map.items():
                for row in stock_data:
                    symbol = self._extract_symbol(row.get("s"))
                    if not symbol:
                        continue

                    metrics_raw = {}
                    metrics = {}
                    for column_id in view_ids:
                        if column_id in {"no", "s", "n"}:
                            continue
                        raw_value = row.get(column_id)
                        metrics_raw[column_id] = raw_value
                        metrics[column_id] = self._normalize_metric_value(raw_value)

                    yield {
                        "source": "stockanalysis",
                        "view": view_name,
                        "symbol": symbol,
                        "ticker_symbol": symbol,
                        "rank": row.get("no"),
                        "company_name": row.get("n"),
                        "stock_name": row.get("n"),
                        "stock_price": row.get("price"),
                        "stock_change": row.get("change"),
                        "created_at": scraped_at,
                        "metrics_raw": metrics_raw,
                        "metrics": metrics,
                        "scraped_at": scraped_at,
                    }
            return

        logger.warning(
            "Could not parse embedded payload; falling back to visible table extraction"
        )
        for item in self._parse_visible_table(response, scraped_at):
            yield item

    def _extract_embedded_payload(self, html_text):
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", html_text, flags=re.S)
        if not scripts:
            return None, None, None

        payload_script = None
        for script in scripts:
            if "stockData:[" in script and "initialDynamicViews:" in script:
                payload_script = script
                break

        if not payload_script:
            return None, None, None

        stock_data_match = re.search(
            r"stockData:\s*(\[.*?\])\s*,\s*pagination:", payload_script, flags=re.S
        )
        views_match = re.search(
            r"initialDynamicViews:\s*(\{.*?\})\s*,\s*columnId:",
            payload_script,
            flags=re.S,
        )
        stock_query_match = re.search(
            r"stockQuery:\s*(\{.*?\})\s*,\s*stockFixed:",
            payload_script,
            flags=re.S,
        )

        if not stock_data_match or not views_match:
            return None, None, None

        try:
            stock_data = self._loads_js_like(stock_data_match.group(1))
            views = self._loads_js_like(views_match.group(1))
            stock_query = (
                self._loads_js_like(stock_query_match.group(1))
                if stock_query_match
                else None
            )
            view_map = self._view_map_from_payload(views)
            return stock_data, view_map, stock_query
        except Exception:
            logger.exception("Failed to decode embedded StockAnalysis payload")
            return None, None, None

    def _needs_symbol_page_enrichment(self, stock_data):
        """Detect whether the payload only includes overview fields.

        Kept as a gate rather than always fetching per-symbol pages: if the site ever
        restores the full payload, this returns False and the spider reverts to the
        cheap single-request path on its own.
        """
        for view_name, column_ids in self._TARGET_VIEW_COLUMNS.items():
            metric_ids = [c for c in column_ids if c not in {"no", "s", "n"}]
            if not metric_ids:
                continue
            has_any = any(
                row.get(metric_id) not in (None, "")
                for row in stock_data
                for metric_id in metric_ids
            )
            if not has_any:
                logger.info(
                    "View '%s' missing in embedded payload; rebuilding from per-symbol pages",
                    view_name,
                )
                return True
        return False

    def _symbols_for_this_run(self, symbols):
        """Pick this run's slice, advancing the window each day so coverage rotates."""
        if self._MAX_SYMBOLS <= 0 or len(symbols) <= self._MAX_SYMBOLS:
            return symbols

        # Keyed on the date so consecutive daily runs pick up where the last left off,
        # and a re-run on the same day repeats rather than skips.
        start = (
            datetime.now(timezone.utc).date().toordinal() * self._MAX_SYMBOLS
        ) % len(symbols)
        rotated = symbols[start:] + symbols[:start]
        selected = rotated[: self._MAX_SYMBOLS]
        logger.info(
            "Enriching %s of %s symbols this run (offset %s): %s",
            len(selected),
            len(symbols),
            start,
            ",".join(selected),
        )
        return selected

    def _parse_symbol_page(self, response, symbol, page, base, scraped_at):
        """Emit view items rebuilt from one per-symbol page."""
        try:
            views = stockanalysis_pages.parse_symbol_page(
                page,
                response.text,
                self._normalize_metric_value,
                self._loads_js_like,
                base=base,
            )
        except Exception:
            logger.exception("Failed to parse %s page for %s", page, symbol)
            return

        if not views:
            logger.warning("No fields parsed from %s page for %s", page, symbol)
            self._inc_stat(f"stockanalysis/empty_page/{page}")
            return

        for view_name, metrics_raw in views.items():
            yield self._build_view_item(
                view_name, symbol, base, metrics_raw, scraped_at
            )

    def _handle_symbol_page_error(self, failure):
        request = failure.request
        logger.warning(
            "Per-symbol page request failed: %s (%s)", request.url, failure.value
        )
        self._inc_stat("stockanalysis/symbol_page_failed")

    def _inc_stat(self, key):
        """Bump a crawl stat; no-op when the spider is used outside a crawler."""
        crawler = getattr(self, "crawler", None)
        if crawler is not None and getattr(crawler, "stats", None) is not None:
            crawler.stats.inc_value(key)

    def _build_view_item(self, view_name, symbol, base, metrics_raw, scraped_at):
        """Build an item in the shape StockAnalysisPipeline already consumes."""
        base = base or {}
        return {
            "source": "stockanalysis",
            "view": view_name,
            "symbol": symbol,
            "ticker_symbol": symbol,
            "rank": base.get("no"),
            "company_name": base.get("n"),
            "stock_name": base.get("n"),
            "stock_price": base.get("price"),
            "stock_change": base.get("change"),
            "created_at": scraped_at,
            "metrics_raw": dict(metrics_raw),
            "metrics": {
                key: self._normalize_metric_value(value)
                for key, value in metrics_raw.items()
            },
            "scraped_at": scraped_at,
        }

    def _view_map_from_payload(self, views_payload):
        items = views_payload.get("items", [])
        view_map = {}
        for item in items:
            name = (item.get("name") or "").strip()
            ids = item.get("ids") or []
            if not name or not isinstance(ids, list):
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if slug:
                view_map[slug] = ids

        # Force the five required tabs and use the full unlocked overview columns.
        for view_name, default_ids in self._TARGET_VIEW_COLUMNS.items():
            if view_name == "overview":
                view_map[view_name] = default_ids
            else:
                view_map.setdefault(view_name, default_ids)

        ordered_map = {}
        for view_name in self._TARGET_VIEW_COLUMNS:
            if view_name in view_map:
                ordered_map[view_name] = view_map[view_name]
        return ordered_map

    def _loads_js_like(self, js_text):
        text = js_text.strip()
        text = text.replace("void 0", "null")
        text = re.sub(r"\bundefined\b", "null", text)
        text = re.sub(r"([:\[,]\s*)\.(\d+)", r"\g<1>0.\2", text)
        text = re.sub(r"([:\[,]\s*)-(\.\d+)", r"\g<1>-0\2", text)
        text = re.sub(r"([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(text)

    def _parse_visible_table(self, response, scraped_at):
        table = response.css("#main-table-wrap table#main-table")
        if not table:
            return

        headers = []
        for th in table.css("thead tr th"):
            header_id = (th.attrib.get("id") or "").strip()
            label = " ".join(th.css("::text").getall()).strip()
            headers.append((header_id or label.lower().replace(" ", "_"), label))

        for tr in table.css("tbody tr"):
            cells = tr.css("td")
            if not cells:
                continue

            row_data = {}
            for idx, cell in enumerate(cells):
                if idx >= len(headers):
                    continue
                col_id = headers[idx][0]
                text_value = " ".join(cell.css("::text").getall()).strip()
                row_data[col_id] = text_value

            symbol_raw = row_data.get("s") or row_data.get("symbol")
            symbol = self._extract_symbol(symbol_raw)
            if not symbol:
                continue

            metrics_raw = {}
            metrics = {}
            for key, value in row_data.items():
                if key in {"no", "s", "n", "symbol", "company_name"}:
                    continue
                metrics_raw[key] = value
                metrics[key] = self._normalize_metric_value(value)

            yield {
                "source": "stockanalysis",
                "view": "overview",
                "symbol": symbol,
                "ticker_symbol": symbol,
                "rank": self._normalize_metric_value(row_data.get("no")),
                "company_name": row_data.get("n") or row_data.get("company_name"),
                "stock_name": row_data.get("n") or row_data.get("company_name"),
                "stock_price": self._normalize_metric_value(row_data.get("price")),
                "stock_change": self._normalize_metric_value(row_data.get("change")),
                "created_at": scraped_at,
                "metrics_raw": metrics_raw,
                "metrics": metrics,
                "scraped_at": scraped_at,
            }

    @staticmethod
    def _extract_symbol(value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if "/" in text:
            text = text.split("/")[-1]
        return text.upper()

    def _normalize_metric_value(self, value):
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return value

        text = str(value).strip()
        if text.lower() in self._KEYWORDS_TO_NULL:
            return None

        if text.endswith("%"):
            percent = text[:-1].replace(",", "").strip()
            try:
                return float(percent)
            except ValueError:
                return text

        compact = text.replace(",", "")
        if compact and compact[-1].upper() in self._UNIT_MULTIPLIERS:
            unit = compact[-1].upper()
            number_part = compact[:-1]
            try:
                return float(number_part) * self._UNIT_MULTIPLIERS[unit]
            except ValueError:
                return text

        try:
            if "." in compact:
                return float(compact)
            return int(compact)
        except ValueError:
            return text
