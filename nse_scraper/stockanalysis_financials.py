"""Parsing of StockAnalysis financial-statement pages for NSE tickers.

``https://stockanalysis.com/quote/nase/<SYMBOL>/financials/<statement>/`` serves the
income statement, balance sheet, cash-flow statement and ratios as server-rendered
tables, annual by default and quarterly with ``?p=quarterly``. Verified 2026-09-13:
FY2021-FY2025 annual plus a trailing-twelve-month column, Q3-2021 to Q2-2026
quarterly, with company-specific fiscal year ends (KCB December, SCOM March, KEGN
June). This module turns one such page into flat line-item records that the pipeline
appends to ``financial_statements`` without ever overwriting an earlier value.

Structure relied on (the generated Tailwind/Svelte classes are not):

* ``<thead>`` row 1: ``Fiscal Year`` | ``TTM`` | ``FY 2025`` ... (or ``Fiscal Quarter``
  | ``Q2 2026`` ..., or ``Current`` on the ratios page); every column ``<th>`` carries
  the period end as ``id="YYYY-MM-DD"``.
* ``<thead>`` row 2: ``Period Ending`` | ``Jun 30, 2026`` ... - the fallback when a
  ``<th>`` has no id.
* ``<tbody>`` rows: first ``<td>`` holds the label (inside an element whose class
  contains ``truncate``; a chevron button with "Show X Growth" text sits beside it and
  is ignored), the remaining ``<td>``s hold the values as displayed: ``173,395``,
  ``-100,192``, ``38.69%``, ``22.22`` or ``-`` for not available.
* A note near the table says what the numbers are in: ``Financials in millions KES.
  Fiscal year is January - December.``

Values are stored **as displayed** together with a ``unit`` (``millions_kes``,
``kes`` for per-share rows, ``percent``, ``ratio``, ``millions`` for share counts) so
the consumer decides how to scale them and nothing is silently multiplied here.
Functions are pure: HTML in, records out.
"""

import logging
import re
from datetime import datetime

from parsel import Selector

logger = logging.getLogger(__name__)

INCOME = "income"
BALANCE = "balance"
CASHFLOW = "cashflow"
RATIOS = "ratios"

#: statement -> path suffix under https://stockanalysis.com/quote/<exchange>/<symbol>/
STATEMENT_PATHS = {
    INCOME: "financials/income-statement/",
    BALANCE: "financials/balance-sheet/",
    CASHFLOW: "financials/cash-flow-statement/",
    RATIOS: "financials/ratios/",
}
STATEMENTS = tuple(STATEMENT_PATHS)

ANNUAL = "annual"
QUARTERLY = "quarterly"
#: Page kinds that can be requested. Companies reporting half-yearly show ``H1``/``H2``
#: columns on the quarterly page; those columns are typed ``semiannual``.
PERIOD_TYPES = (ANNUAL, QUARTERLY)
SEMIANNUAL = "semiannual"

#: Column kinds beyond the fiscal periods themselves.
TTM = "ttm"
CURRENT = "current"

_BASE_URL = "https://stockanalysis.com/quote"

_NOT_AVAILABLE = {"", "-", "--", "n/a", "na", "upgrade"}
_NUMBER_RE = re.compile(r"^[-+]?\d[\d,]*(?:\.\d+)?$")
_PERIOD_END_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNITS_RE = re.compile(
    r"(?P<what>[A-Za-z ]+?)\s+in\s+(?P<scale>thousands|millions|billions)\s+(?P<currency>[A-Z]{3})\."
    r"(?:\s*Fiscal year is\s+(?P<fy>[A-Za-z]+\s*-\s*[A-Za-z]+)\.)?",
    re.I,
)

#: Row keys (the site's own ids) and label fragments that are per-share amounts.
_PER_SHARE_KEYS = {"eps", "epsdil", "epsbasic", "bvps", "dps", "netcashpershare", "fcfps", "ocfps", "tbvps"}
_PER_SHARE_LABEL = re.compile(r"per share|\bEPS\b", re.I)
_SHARE_COUNT_LABEL = re.compile(r"shares outstanding", re.I)
_RATIO_LABEL = re.compile(
    r"\bratio\b|\bmargin\b|\byield\b|\bturnover\b|\bcoverage\b|\bpayout\b|\breturn on\b|"
    r"\bP/|\bPE\b|\bPS\b|\bPB\b|\bEV/|\bmultiple\b|\btax rate\b|"
    r"\bdebt / |/ equity\b|/ ebitda\b|/ fcf\b",
    re.I,
)
_MONEY_ON_RATIOS_PAGE = re.compile(r"market cap|enterprise value", re.I)
_PRICE_LABEL = re.compile(r"\bprice\b", re.I)
#: Rows that are percentages even when every displayed cell is "-".
_PERCENT_LABEL = re.compile(r"\bgrowth\b|shares change|\bmargin\b|\byield\b|\bpayout\b|\breturn on\b|tax rate", re.I)


def statement_url(symbol, statement, period_type=ANNUAL, exchange="nase"):
    """URL of one statement page, e.g. ``.../quote/nase/KCB/financials/ratios/?p=quarterly``."""
    suffix = STATEMENT_PATHS.get(statement)
    if suffix is None:
        raise ValueError("Unknown statement: {!r}".format(statement))
    if period_type not in PERIOD_TYPES:
        raise ValueError("Unknown period type: {!r}".format(period_type))
    url = "{}/{}/{}/{}".format(_BASE_URL, exchange, symbol.upper(), suffix)
    if period_type == QUARTERLY:
        url += "?p=quarterly"
    return url


def slugify(label):
    """``Cash & Equivalents`` -> ``cash_and_equivalents``; ``EPS (Diluted)`` -> ``eps_diluted``."""
    text = label.replace("&amp;", "&").replace("&", " and ")
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text


def parse_number(raw):
    """``'173,395'`` -> 173395.0, ``'-100,192'`` -> -100192.0, ``'38.69%'`` -> 38.69, ``'-'`` -> None."""
    if raw is None:
        return None
    text = raw.strip().replace("−", "-")
    if text.lower() in _NOT_AVAILABLE:
        return None
    text = text.rstrip("%").replace(",", "").replace("$", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if not _NUMBER_RE.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_units(html):
    """The page's unit note -> ``{"scale": "millions", "currency": "KES", "fiscal_year": "January - December"}``."""
    text = " ".join(Selector(text=html).xpath("//body//text()").getall())
    text = " ".join(text.split())
    match = _UNITS_RE.search(text)
    if not match:
        return {"scale": None, "currency": None, "fiscal_year": None}
    return {
        "scale": match.group("scale").lower(),
        "currency": match.group("currency").upper(),
        "fiscal_year": " ".join(match.group("fy").split()) if match.group("fy") else None,
    }


def _period_end_from_text(text):
    """``Jun 30, 2026`` -> ``2026-06-30``; anything else -> None."""
    cleaned = " ".join((text or "").split())
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _column_kind(label, page_period_type):
    upper = (label or "").strip().upper()
    if upper == "TTM":
        return TTM
    if upper == "CURRENT":
        return CURRENT
    if upper.startswith("FY"):
        return ANNUAL
    if re.match(r"^Q[1-4]\s", upper):
        return QUARTERLY
    if re.match(r"^H[12]\s", upper):
        return SEMIANNUAL
    return page_period_type


def parse_columns(table, page_period_type):
    """Header cells -> ``[{"label": "FY 2025", "period_end": "2025-12-31", "period_type": "annual"}]``.

    The first header cell is the row-label column and is skipped. A column with no
    resolvable period end is dropped rather than guessed.
    """
    header_rows = table.css("thead tr")
    if not header_rows:
        return []
    labels = [" ".join(th.css("::text").getall()).split() for th in header_rows[0].css("th")]
    ids = [th.attrib.get("id") for th in header_rows[0].css("th")]
    endings = []
    if len(header_rows) > 1:
        for th in header_rows[1].css("th"):
            spans = th.css("span::text").getall()
            endings.append(spans[-1] if spans else " ".join(th.css("::text").getall()))
    columns = []
    for index in range(1, len(labels)):
        label = " ".join(labels[index])
        period_end = ids[index] if ids[index] and _PERIOD_END_RE.match(ids[index]) else None
        if period_end is None and index < len(endings):
            period_end = _period_end_from_text(endings[index])
        if period_end is None:
            logger.warning("Dropping statement column %r: no period end", label)
            continue
        columns.append(
            {"label": label, "period_end": period_end, "period_type": _column_kind(label, page_period_type)}
        )
    return columns


def _row_label(cell):
    for node in cell.css("[class*=truncate]"):
        text = " ".join(" ".join(node.css("::text").getall()).split())
        if text:
            return text
    # No truncating wrapper: take the cell text minus the chevron button's text.
    texts = []
    for node in cell.xpath(".//text()[not(ancestor::button)]"):
        texts.append(node.get())
    return " ".join(" ".join(texts).split()) or None


def _row_key(cell):
    node = cell.css("[class*=icon][id]")
    return node.attrib.get("id") if node else None


def unit_for(statement, label, row_key, raw, scale, currency):
    """Which unit a row's values are in. Percent wins; then per-share; then the page scale.

    ``raw`` is a representative displayed value from the row (a ``%`` one if any).
    """
    text = (raw or "").strip()
    if text.endswith("%") or _PERCENT_LABEL.search(label or ""):
        return "percent"
    if (row_key and row_key.lower() in _PER_SHARE_KEYS) or _PER_SHARE_LABEL.search(label or ""):
        return (currency or "KES").lower()
    if _SHARE_COUNT_LABEL.search(label or ""):
        return scale or "millions"
    if statement == RATIOS and _PRICE_LABEL.search(label or ""):
        return (currency or "KES").lower()
    if statement == RATIOS and not _MONEY_ON_RATIOS_PAGE.search(label or ""):
        return "ratio"
    if _RATIO_LABEL.search(label or "") and statement != RATIOS:
        return "ratio"
    return "{}_{}".format(scale or "millions", (currency or "KES").lower())


def parse_statement_page(html, symbol, statement, period_type):
    """One page -> ``{"units": {...}, "columns": [...], "records": [...]}``.

    Each record is one (line item, period) cell::

        {"ticker_symbol": "KCB", "statement": "income", "period_type": "annual",
         "fiscal_period_end": "2025-12-31", "fiscal_label": "FY 2025",
         "line_item": "net_income", "label": "Net Income", "row_key": "netinc",
         "value": 66819.0, "value_raw": "66,819", "unit": "millions_kes", "currency": "KES"}

    Cells showing ``-`` are kept with ``value=None`` and ``value_raw="-"``: the site
    explicitly reporting "not available" is itself information a consumer needs.
    """
    if statement not in STATEMENT_PATHS:
        raise ValueError("Unknown statement: {!r}".format(statement))
    selector = Selector(text=html)
    units = parse_units(html)
    tables = _statement_tables(selector)
    if not tables:
        return {"units": units, "columns": [], "records": []}

    records = []
    columns_seen = []
    seen = set()
    for table in tables:
        columns = parse_columns(table, period_type)
        if not columns:
            continue
        if not columns_seen:
            columns_seen = columns
        _collect_rows(table, columns, symbol, statement, units, records, seen)
    return {"units": units, "columns": columns_seen, "records": records}


def _statement_tables(selector):
    """Every statement table on the page.

    A page is split into sections - the ratios page has "Total Valuation",
    "Price Ratios", "Financial Efficiency" and "Yields" - each rendered as its own
    ``<table id="main-table-...">`` with its own header. All of them belong to the
    same statement.
    """
    tables = selector.css("table[id^=main-table], table.financials-table")
    unique = []
    seen_ids = set()
    for table in tables:
        marker = table.attrib.get("id") or id(table.root)
        if marker in seen_ids:
            continue
        seen_ids.add(marker)
        unique.append(table)
    return unique or list(selector.css("table"))


def _collect_rows(table, columns, symbol, statement, units, records, seen):
    for row in table.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        label = _row_label(cells[0])
        if not label:
            continue
        line_item = slugify(label)
        if not line_item:
            continue
        row_key = _row_key(cells[0])
        raws = [" ".join(" ".join(cell.css("::text").getall()).split()) for cell in cells[1:]]
        # One unit per row: a "-" cell in a percent row is still a percent row.
        sample = next((raw for raw in raws if raw.endswith("%")), next((raw for raw in raws if raw), ""))
        unit = unit_for(statement, label, row_key, sample, units["scale"], units["currency"])
        for column, raw in zip(columns, raws):
            key = (column["period_end"], column["period_type"], line_item)
            if key in seen:
                # A label repeated in two sections (e.g. "Total" per segment) - keep the first.
                continue
            seen.add(key)
            records.append(
                {
                    "ticker_symbol": symbol.upper(),
                    "statement": statement,
                    "period_type": column["period_type"],
                    "fiscal_period_end": column["period_end"],
                    "fiscal_label": column["label"],
                    "line_item": line_item,
                    "label": label,
                    "row_key": row_key,
                    "value": parse_number(raw),
                    "value_raw": raw or "-",
                    "unit": unit,
                    "currency": units["currency"] or "KES",
                }
            )
