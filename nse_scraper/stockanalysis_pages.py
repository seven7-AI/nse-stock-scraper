"""Field extraction for StockAnalysis per-symbol pages.

The ``api.stockanalysis.com/api/screener/*`` endpoints the spider used to enrich the
performance/dividends/price/profile views were retired and now return 404 for every
variant, leaving only the overview view in the list page's embedded payload. These
helpers rebuild the missing views from the per-symbol pages, which are still
server-rendered.

Each page embeds the same SvelteKit ``kit.start(...)`` payload the list page uses, so
values are read from structured objects rather than from generated Tailwind classes
that churn between deploys. Only the 52-week range and volume come from visible
markup, and those are keyed on the row's label text rather than its classes.

Functions here are pure: they take HTML plus the spider's normalizer and return
``{view_name: {column_id: value}}``.
"""

import logging
import re

from parsel import Selector

logger = logging.getLogger(__name__)

QUOTE_PAGE = "quote"
DIVIDEND_PAGE = "dividend"
COMPANY_PAGE = "company"

# Path suffix appended to https://stockanalysis.com/quote/<exchange>/<symbol>/
SYMBOL_PAGE_PATHS = {
    QUOTE_PAGE: "",
    DIVIDEND_PAGE: "dividend/",
    COMPANY_PAGE: "company/",
}

# Every page this module can parse.
SYMBOL_PAGES = (QUOTE_PAGE, DIVIDEND_PAGE, COMPANY_PAGE)

# Fetched by default. The company page is excluded because the quote page already
# carries industry/founded/employees, so including it would add a third more requests
# to gain only `country` -- and the site returns 403 once a full-catalogue crawl runs
# too hot. Re-enable it with STOCKANALYSIS_SYMBOL_PAGES=quote,dividend,company.
DEFAULT_SYMBOL_PAGES = (QUOTE_PAGE, DIVIDEND_PAGE)

# Profile labels carried by the quote page's own infoTable. Having these means the
# company page can be dropped (a third of all requests) at the cost of `country`,
# which matters because the site rate-limits a full-catalogue crawl.
_QUOTE_PROFILE_LABELS = {"Industry": "industry", "Founded": "founded", "Employees": "employees"}

_BASE_URL = "https://stockanalysis.com/quote"


def symbol_page_url(symbol, page, exchange="nase"):
    """URL of a per-symbol page, e.g. ``.../quote/nase/SCOM/dividend/``."""
    suffix = SYMBOL_PAGE_PATHS.get(page)
    if suffix is None:
        raise ValueError("Unknown StockAnalysis page: {!r}".format(page))
    return "{}/{}/{}/{}".format(_BASE_URL, exchange, symbol.upper(), suffix)


def extract_js_object(text, key):
    """Return the source of the ``key:{...}`` object, honouring nested braces.

    A non-greedy regex would stop at the first closing brace and truncate nested
    objects such as ``profile:{industry:{value:...}}``.
    """
    match = re.search(r"\b{}\s*:\s*\{{".format(re.escape(key)), text)
    if not match:
        return None

    start = match.end() - 1
    depth = 0
    in_string = None
    index = start
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == in_string:
                in_string = None
        elif char in "\"'":
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
        index += 1
    return None


def _load_object(text, key, loads):
    raw = extract_js_object(text, key)
    if not raw:
        return None
    try:
        return loads(raw)
    except Exception:
        logger.warning("Could not decode '%s' object from StockAnalysis page", key)
        return None


def _clean(value):
    """Collapse whitespace in a visible-text value, or None if it is empty."""
    if value is None:
        return None
    text = " ".join(value.split()).strip()
    return text or None


def label_value_pairs(html):
    """Map visible ``<td>Label</td><td>Value</td>`` rows to ``{label: value}``.

    Keyed on label text because the surrounding classes are generated and unstable.
    """
    pairs = {}
    for row in Selector(text=html).css("tr"):
        cells = row.css("td")
        if len(cells) != 2:
            continue
        label = _clean(" ".join(cells[0].css("::text").getall()))
        value = _clean(" ".join(cells[1].css("::text").getall()))
        if label and value and label not in pairs:
            pairs[label] = value
    return pairs


def split_range(text):
    """``"25.50 - 37.30"`` -> ``("25.50", "37.30")``."""
    if not text:
        return None, None
    parts = [part.strip() for part in re.split(r"\s+-\s+", text, maxsplit=1)]
    if len(parts) != 2:
        return None, None
    return parts[0] or None, parts[1] or None


def strip_currency(text):
    """``"2.30 KES"`` -> ``"2.30"``; leaves values without a currency suffix alone."""
    if not isinstance(text, str):
        return text
    match = re.match(r"^\s*(-?[\d.,]+)\s+[A-Za-z]{2,5}\s*$", text)
    return match.group(1) if match else text


def _percent_change(current, reference):
    """Percentage move from ``reference`` to ``current``, or None if not computable."""
    try:
        current = float(current)
        reference = float(reference)
    except (TypeError, ValueError):
        return None
    if not reference:
        return None
    return round((current - reference) / reference * 100, 2)


def parse_quote_page(html, normalize, base=None):
    """Price view (52-week range, volume) plus the one recoverable return horizon."""
    base = base or {}
    pairs = label_value_pairs(html)

    low52_raw, high52_raw = split_range(pairs.get("52-Week Range"))
    low52 = normalize(low52_raw)
    high52 = normalize(high52_raw)
    price = base.get("price")
    if price is None:
        price = normalize(pairs.get("Price"))

    price_metrics = {
        "volume": normalize(pairs.get("Volume")),
        "low52": low52,
        "high52": high52,
        "low52ch": _percent_change(price, low52),
        "high52ch": _percent_change(price, high52),
    }

    views = {}
    if any(value is not None for value in price_metrics.values()):
        views["price"] = price_metrics

    # Only the 1-year horizon is published for NSE tickers; tr1m/tr6m/trYTD/tr5y/tr10y
    # are not served anywhere server-side, so they are omitted rather than nulled.
    match = re.search(r'\bch1y\s*:\s*"([^"]*)"', html)
    tr1y = normalize(match.group(1)) if match else None
    if tr1y is None:
        tr1y = normalize(pairs.get("52-Week Price Change"))
    if tr1y is not None:
        views["performance"] = {"tr1y": tr1y}

    profile = _quote_profile(html, normalize)
    if profile:
        views["profile"] = profile

    return views


def _quote_profile(html, normalize):
    """Profile fields from the quote page's ``infoTable:[{t:"Industry",v:...}]`` array."""
    metrics = {}
    for label, column in _QUOTE_PROFILE_LABELS.items():
        match = re.search(
            r'\{\s*t\s*:\s*"%s"\s*,\s*v\s*:\s*("([^"]*)"|[^,}]+)' % re.escape(label), html
        )
        if not match:
            continue
        raw = match.group(2) if match.group(2) is not None else match.group(1)
        value = normalize(raw.strip())
        if value is not None:
            metrics[column] = value
    return metrics


def parse_dividend_page(html, normalize, loads):
    """Dividends view from the page's ``infoTable`` object."""
    info = _load_object(html, "infoTable", loads)
    if not isinstance(info, dict):
        return {}

    metrics = {
        "dps": normalize(strip_currency(info.get("annual"))),
        "dividendYield": normalize(info.get("yield")),
        "dividendGrowth": normalize(info.get("growth")),
        "exDivDate": info.get("exdiv") or None,
        "payoutRatio": normalize(info.get("payoutRatio")),
        "payoutFrequency": info.get("frequency") or None,
    }
    if all(value is None for value in metrics.values()):
        return {}
    return {"dividends": metrics}


def parse_company_page(html, normalize, loads):
    """Profile view from the page's ``profile`` object."""
    profile = _load_object(html, "profile", loads)
    if not isinstance(profile, dict):
        return {}

    def _nested(key):
        value = profile.get(key)
        if isinstance(value, dict):
            return value.get("value")
        return value

    metrics = {
        "industry": _nested("industry"),
        "country": profile.get("country"),
        "employees": normalize(_nested("employees")),
        "founded": normalize(profile.get("founded")),
    }
    if all(value is None for value in metrics.values()):
        return {}
    return {"profile": metrics}


def parse_symbol_page(page, html, normalize, loads, base=None):
    """Dispatch to the parser for ``page``, returning ``{view: {column: value}}``."""
    if page == QUOTE_PAGE:
        return parse_quote_page(html, normalize, base=base)
    if page == DIVIDEND_PAGE:
        return parse_dividend_page(html, normalize, loads)
    if page == COMPANY_PAGE:
        return parse_company_page(html, normalize, loads)
    raise ValueError("Unknown StockAnalysis page: {!r}".format(page))
