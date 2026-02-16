import json
import logging
import os
import re
from urllib.parse import quote
from datetime import datetime, timezone

from scrapy import Request, Spider


logger = logging.getLogger(__name__)


def _stockanalysis_pipelines():
    if os.getenv("DB_BACKEND", "").strip().lower() == "supabase":
        return {"nse_scraper.pipelines.StockAnalysisPipeline": 300}
    return {}


class StockAnalysisScraperSpider(Spider):
    name = "stockanalysis_scraper"
    allowed_domains = ["stockanalysis.com", "api.stockanalysis.com"]
    start_urls = ["https://stockanalysis.com/list/nairobi-stock-exchange/"]
    custom_settings = {"ITEM_PIPELINES": _stockanalysis_pipelines()}
    _SCREENER_API_BASE = "https://api.stockanalysis.com/api"
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
            if stock_query and self._should_fetch_views_from_api(stock_data):
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

                for view_name, column_ids in self._TARGET_VIEW_COLUMNS.items():
                    if view_name == "overview":
                        continue
                    api_url = self._build_screener_api_url(stock_query, column_ids)
                    if not api_url:
                        continue
                    yield Request(
                        url=api_url,
                        callback=self._parse_screener_api_view,
                        cb_kwargs={
                            "view_name": view_name,
                            "column_ids": column_ids,
                            "base_by_symbol": base_by_symbol,
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

    def _should_fetch_views_from_api(self, stock_data):
        """Detect whether payload only includes overview fields and needs API enrichment."""
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
                    "View '%s' missing in embedded payload; fetching via screener API",
                    view_name,
                )
                return True
        return False

    def _build_screener_api_url(self, stock_query, column_ids):
        if not stock_query:
            return None

        query_type = stock_query.get("type") or "s"
        main = stock_query.get("main") or "marketCap"
        sort_direction = stock_query.get("sortDirection") or "desc"
        sort_column = stock_query.get("sortColumn")
        count = stock_query.get("count")
        filters = stock_query.get("filters") or []
        dedupe = stock_query.get("dedupe")
        index = stock_query.get("index")

        # Match StockAnalysis client behavior: ensure main column is always requested.
        ordered_columns = list(dict.fromkeys(column_ids))
        if main not in ordered_columns:
            ordered_columns.append(main)
        columns_csv = ",".join(ordered_columns)

        parts = [
            f"{self._SCREENER_API_BASE}/screener/{query_type}/f",
            f"m={main}",
            f"s={sort_direction}",
            f"c={quote(columns_csv, safe=',')}",
        ]
        if sort_column:
            parts.append(f"sc={quote(str(sort_column), safe='')}")
        if count:
            parts.append(f"cn={count}")
        if filters:
            encoded_filters = ",".join(
                quote(str(v).replace("%", " "), safe="") for v in filters
            )
            parts.append(f"f={encoded_filters}")
        if dedupe:
            parts.append("dd=true")
        if index:
            parts.append(f"i={quote(str(index), safe='')}")

        query_string = "&".join(parts[1:])
        return f"{parts[0]}?{query_string}" if query_string else parts[0]

    def _parse_screener_api_view(
        self, response, view_name, column_ids, base_by_symbol, scraped_at
    ):
        try:
            payload = json.loads(response.text)
            rows = (payload.get("data") or {}).get("data") or []
        except Exception:
            logger.exception("Failed to parse screener API JSON for view '%s'", view_name)
            return

        if not rows:
            logger.warning("Screener API returned no rows for view '%s'", view_name)
            return

        for row in rows:
            symbol = self._extract_symbol(row.get("s"))
            if not symbol:
                continue

            base = base_by_symbol.get(symbol, {})
            metrics_raw = {}
            metrics = {}
            for column_id in column_ids:
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
                "rank": row.get("no") if row.get("no") is not None else base.get("no"),
                "company_name": row.get("n") or base.get("n"),
                "stock_name": row.get("n") or base.get("n"),
                "stock_price": (
                    row.get("price") if row.get("price") is not None else base.get("price")
                ),
                "stock_change": (
                    row.get("change")
                    if row.get("change") is not None
                    else base.get("change")
                ),
                "created_at": scraped_at,
                "metrics_raw": metrics_raw,
                "metrics": metrics,
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
