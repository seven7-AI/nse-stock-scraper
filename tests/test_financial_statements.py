"""Financial statements: parser, storage, pipeline routing and spider requests.

The parser fixtures under tests/fixtures/financials/ are the real StockAnalysis pages
for three NSE tickers with different fiscal year ends, trimmed to the unit note and the
statement tables (SVG icons and framework comments stripped, nothing else changed):

    KCB   December year end, banking-style income statement, no quarterly cash flow
    SCOM  March year end, half-yearly reporter (H1/H2 columns on the quarterly page)
    KEGN  June year end, half-yearly reporter
"""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from nse_scraper import stockanalysis_financials as fin
from nse_scraper.db.backends import SQLiteBackend
from nse_scraper.extensions import FINANCIALS_FAILED_STAT, FINANCIALS_OK_STAT
from nse_scraper.pipelines import StockAnalysisPipeline
from nse_scraper.spiders.stockanalysis_scraper import StockAnalysisScraperSpider

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "financials")


def fixture(symbol, statement, period_type):
    path = os.path.join(FIXTURES, "{}_{}_{}.html".format(symbol, statement, period_type))
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse(symbol, statement, period_type):
    return fin.parse_statement_page(fixture(symbol, statement, period_type), symbol, statement, period_type)


def cell(parsed, line_item, fiscal_label):
    for record in parsed["records"]:
        if record["line_item"] == line_item and record["fiscal_label"] == fiscal_label:
            return record
    raise AssertionError("{} / {} not parsed".format(line_item, fiscal_label))


# --- helpers -------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):
    def test_statement_urls(self):
        self.assertEqual(
            fin.statement_url("kcb", fin.INCOME),
            "https://stockanalysis.com/quote/nase/KCB/financials/income-statement/",
        )
        self.assertEqual(
            fin.statement_url("KCB", fin.RATIOS, fin.QUARTERLY),
            "https://stockanalysis.com/quote/nase/KCB/financials/ratios/?p=quarterly",
        )
        with self.assertRaises(ValueError):
            fin.statement_url("KCB", "profits")
        with self.assertRaises(ValueError):
            fin.statement_url("KCB", fin.INCOME, "monthly")

    def test_parse_number_handles_every_displayed_shape(self):
        self.assertEqual(fin.parse_number("173,395"), 173395.0)
        self.assertEqual(fin.parse_number("-100,192"), -100192.0)
        self.assertEqual(fin.parse_number("38.69%"), 38.69)
        self.assertEqual(fin.parse_number("-92.32%"), -92.32)
        self.assertEqual(fin.parse_number("970.6"), 970.6)
        self.assertEqual(fin.parse_number("(1,234)"), -1234.0)
        self.assertEqual(fin.parse_number("−5.5"), -5.5)
        for not_available in ("-", "", " ", "n/a", "Upgrade", None):
            self.assertIsNone(fin.parse_number(not_available), not_available)
        self.assertIsNone(fin.parse_number("Jun 30, 2026"))

    def test_slugify(self):
        self.assertEqual(fin.slugify("Cash &amp; Equivalents"), "cash_and_equivalents")
        self.assertEqual(fin.slugify("EPS (Diluted)"), "eps_diluted")
        self.assertEqual(fin.slugify("Return on Equity (ROE)"), "return_on_equity_roe")
        self.assertEqual(fin.slugify("  Net Income  "), "net_income")

    def test_units_per_row(self):
        self.assertEqual(fin.unit_for(fin.INCOME, "Revenue", "revenue", "173,395", "millions", "KES"), "millions_kes")
        self.assertEqual(fin.unit_for(fin.INCOME, "EPS (Diluted)", "epsdil", "20.80", "millions", "KES"), "kes")
        self.assertEqual(fin.unit_for(fin.INCOME, "Dividend Per Share", None, "6.000", "millions", "KES"), "kes")
        self.assertEqual(fin.unit_for(fin.INCOME, "Profit Margin", None, "38.69%", "millions", "KES"), "percent")
        self.assertEqual(fin.unit_for(fin.INCOME, "Revenue Growth", None, "-", "millions", "KES"), "percent")
        self.assertEqual(fin.unit_for(fin.INCOME, "Basic Shares Outstanding", None, "3,213", "millions", "KES"), "millions")
        self.assertEqual(fin.unit_for(fin.RATIOS, "PE Ratio", "pe", "4.43", "millions", "KES"), "ratio")
        self.assertEqual(fin.unit_for(fin.RATIOS, "Market Capitalization", "marketcap", "302,066", "millions", "KES"), "millions_kes")
        self.assertEqual(fin.unit_for(fin.RATIOS, "Last Close Price", None, "94.00", "millions", "KES"), "kes")
        # "Earnings from Continuing Operations" must not be mistaken for a ratio ("opeRATIOns")
        self.assertEqual(fin.unit_for(fin.INCOME, "Earnings From Continuing Operations", None, "66,819", "millions", "KES"), "millions_kes")
        self.assertEqual(fin.unit_for(fin.CASHFLOW, "Change in Other Net Operating Assets", None, "-1,200", "millions", "KES"), "millions_kes")
        # Page in thousands USD would be honoured, not assumed
        self.assertEqual(fin.unit_for(fin.INCOME, "Revenue", None, "1", "thousands", "USD"), "thousands_usd")


# --- real pages ----------------------------------------------------------------------


class TestIncomeStatement(unittest.TestCase):
    def test_kcb_annual_columns_and_units(self):
        parsed = parse("KCB", fin.INCOME, fin.ANNUAL)
        self.assertEqual(parsed["units"], {"scale": "millions", "currency": "KES", "fiscal_year": "January - December"})
        self.assertEqual(
            [(c["label"], c["period_end"], c["period_type"]) for c in parsed["columns"]],
            [
                ("TTM", "2026-06-30", fin.TTM),
                ("FY 2025", "2025-12-31", fin.ANNUAL),
                ("FY 2024", "2024-12-31", fin.ANNUAL),
                ("FY 2023", "2023-12-31", fin.ANNUAL),
                ("FY 2022", "2022-12-31", fin.ANNUAL),
                ("FY 2021", "2021-12-31", fin.ANNUAL),
            ],
        )

    def test_kcb_annual_values(self):
        parsed = parse("KCB", fin.INCOME, fin.ANNUAL)
        revenue = cell(parsed, "revenue", "FY 2025")
        self.assertEqual(revenue["value"], 173395.0)
        self.assertEqual(revenue["value_raw"], "173,395")
        self.assertEqual(revenue["unit"], "millions_kes")
        self.assertEqual(revenue["fiscal_period_end"], "2025-12-31")
        self.assertEqual(cell(parsed, "net_income", "FY 2021")["value"], 34092.0)
        eps = cell(parsed, "eps_diluted", "FY 2025")
        self.assertEqual(eps["unit"], "kes")
        self.assertAlmostEqual(eps["value"], 20.80, places=2)
        ttm = cell(parsed, "revenue", "TTM")
        self.assertEqual(ttm["period_type"], fin.TTM)
        self.assertEqual(ttm["value"], 184508.0)
        # bank-style line items are kept, not forced into an industrial template
        items = {r["line_item"] for r in parsed["records"]}
        self.assertIn("interest_income_on_loans", items)
        self.assertIn("provision_for_loan_losses", items)
        self.assertNotIn("gross_profit", items)

    def test_growth_rows_are_percent_even_when_blank(self):
        parsed = parse("KCB", fin.INCOME, fin.ANNUAL)
        self.assertEqual(cell(parsed, "revenue_growth", "FY 2025")["unit"], "percent")
        blank = [r for r in parsed["records"] if r["line_item"].endswith("_growth") and r["value_raw"] == "-"]
        self.assertTrue(blank, "expected at least one blank growth cell in the fixture")
        self.assertTrue(all(r["unit"] == "percent" and r["value"] is None for r in blank))

    def test_not_available_cells_are_kept_as_none(self):
        parsed = parse("KCB", fin.INCOME, fin.ANNUAL)
        interest = cell(parsed, "interest_income_on_investments", "FY 2025")
        self.assertIsNone(interest["value"])
        self.assertEqual(interest["value_raw"], "-")

    def test_negative_values(self):
        parsed = parse("KCB", fin.CASHFLOW, fin.ANNUAL)
        ocf = cell(parsed, "operating_cash_flow", "FY 2025")
        self.assertEqual(ocf["value"], -126832.0)
        self.assertEqual(ocf["value_raw"], "-126,832")

    def test_kcb_quarterly_has_twenty_quarters_back_to_q3_2021(self):
        parsed = parse("KCB", fin.INCOME, fin.QUARTERLY)
        labels = [c["label"] for c in parsed["columns"]]
        self.assertEqual(labels[0], "Q2 2026")
        self.assertEqual(labels[-1], "Q3 2021")
        self.assertEqual(len(labels), 20)
        self.assertTrue(all(c["period_type"] == fin.QUARTERLY for c in parsed["columns"]))
        self.assertEqual(cell(parsed, "revenue", "Q2 2026")["fiscal_period_end"], "2026-06-30")

    def test_scom_march_year_end(self):
        parsed = parse("SCOM", fin.INCOME, fin.ANNUAL)
        self.assertEqual(parsed["units"]["fiscal_year"], "April - March")
        fy2026 = cell(parsed, "revenue", "FY 2026")
        self.assertEqual(fy2026["fiscal_period_end"], "2026-03-31")
        self.assertEqual(fy2026["value"], 423866.0)
        self.assertEqual(cell(parsed, "gross_profit", "FY 2025")["unit"], "millions_kes")
        self.assertEqual(cell(parsed, "operating_margin", "FY 2025")["unit"], "percent")

    def test_half_yearly_reporters_are_typed_semiannual(self):
        parsed = parse("SCOM", fin.INCOME, fin.QUARTERLY)
        self.assertEqual(parsed["columns"][0]["label"], "H2 2026")
        self.assertTrue(all(c["period_type"] == fin.SEMIANNUAL for c in parsed["columns"]))
        kegn = parse("KEGN", fin.BALANCE, fin.QUARTERLY)
        self.assertEqual(kegn["columns"][0], {"label": "H1 2026", "period_end": "2025-12-31", "period_type": fin.SEMIANNUAL})

    def test_kegn_june_year_end(self):
        parsed = parse("KEGN", fin.RATIOS, fin.ANNUAL)
        self.assertEqual(parsed["units"]["fiscal_year"], "July - June")
        self.assertEqual(cell(parsed, "return_on_equity_roe", "FY 2026")["fiscal_period_end"], "2026-06-30")


class TestOtherStatements(unittest.TestCase):
    def test_balance_sheet_spans_every_section_table(self):
        parsed = parse("KCB", fin.BALANCE, fin.ANNUAL)
        items = {r["line_item"] for r in parsed["records"]}
        # assets, liabilities and equity sections are separate <table>s on the page
        for expected in ("cash_and_equivalents", "total_assets", "total_liabilities", "shareholders_equity", "total_debt", "book_value_per_share"):
            self.assertIn(expected, items)
        self.assertEqual(cell(parsed, "book_value_per_share", "FY 2025")["unit"], "kes")
        self.assertEqual(cell(parsed, "total_assets", "FY 2025")["unit"], "millions_kes")

    def test_ratios_page_units(self):
        parsed = parse("KCB", fin.RATIOS, fin.ANNUAL)
        current = parsed["columns"][0]
        self.assertEqual(current["label"], "Current")
        self.assertEqual(current["period_type"], fin.CURRENT)
        self.assertEqual(cell(parsed, "pe_ratio", "FY 2025")["unit"], "ratio")
        self.assertEqual(cell(parsed, "return_on_equity_roe", "FY 2025")["unit"], "percent")
        self.assertEqual(cell(parsed, "market_capitalization", "FY 2025")["unit"], "millions_kes")
        self.assertEqual(cell(parsed, "dividend_yield", "FY 2025")["unit"], "percent")

    def test_one_unit_per_line_item(self):
        for symbol in ("KCB", "SCOM", "KEGN"):
            for statement in fin.STATEMENTS:
                for period in fin.PERIOD_TYPES:
                    parsed = parse(symbol, statement, period)
                    units = {}
                    for record in parsed["records"]:
                        units.setdefault(record["line_item"], set()).add(record["unit"])
                    mixed = {k: v for k, v in units.items() if len(v) > 1}
                    self.assertEqual(mixed, {}, "{} {} {}".format(symbol, statement, period))

    def test_no_duplicate_cells(self):
        parsed = parse("SCOM", fin.CASHFLOW, fin.QUARTERLY)
        keys = [(r["fiscal_period_end"], r["period_type"], r["line_item"]) for r in parsed["records"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_missing_quarterly_cash_flow_is_empty_not_an_error(self):
        parsed = parse("KCB", fin.CASHFLOW, fin.QUARTERLY)
        self.assertEqual(parsed["records"], [])
        self.assertEqual(parsed["columns"], [])

    def test_page_without_tables(self):
        parsed = fin.parse_statement_page("<html><body><p>Nothing here</p></body></html>", "KCB", fin.INCOME, fin.ANNUAL)
        self.assertEqual(parsed, {"units": {"scale": None, "currency": None, "fiscal_year": None}, "columns": [], "records": []})

    def test_columns_without_a_period_end_are_dropped_not_guessed(self):
        html = """<html><body><div>Financials in millions KES. Fiscal year is January - December.</div>
        <table id="main-table"><thead>
          <tr><th>Fiscal Year</th><th id="2025-12-31">FY 2025</th><th>FY 2024</th></tr>
          <tr><th>Period Ending</th><th><span>Dec 31, 2025</span></th><th><span>unknown</span></th></tr>
        </thead><tbody>
          <tr><td><div class="truncate">Revenue</div></td><td>10</td><td>9</td></tr>
        </tbody></table></body></html>"""
        parsed = fin.parse_statement_page(html, "X", fin.INCOME, fin.ANNUAL)
        self.assertEqual([c["period_end"] for c in parsed["columns"]], ["2025-12-31"])
        self.assertEqual(len(parsed["records"]), 1)

    def test_period_end_falls_back_to_the_period_ending_row(self):
        html = """<html><body><table id="main-table"><thead>
          <tr><th>Fiscal Year</th><th>FY 2025</th></tr>
          <tr><th>Period Ending</th><th><span class="inline">Dec '25</span> <span class="hidden">Dec 31, 2025</span></th></tr>
        </thead><tbody>
          <tr><td>Revenue</td><td>10</td></tr>
        </tbody></table></body></html>"""
        parsed = fin.parse_statement_page(html, "X", fin.INCOME, fin.ANNUAL)
        self.assertEqual(parsed["columns"], [{"label": "FY 2025", "period_end": "2025-12-31", "period_type": fin.ANNUAL}])
        record = parsed["records"][0]
        self.assertEqual((record["line_item"], record["value"], record["unit"]), ("revenue", 10.0, "millions_kes"))


# --- storage ---------------------------------------------------------------------------


def _item(symbol="KCB", statement=fin.INCOME, period_type=fin.ANNUAL, scraped_at="2026-09-13T07:02:00+00:00", records=None):
    parsed = parse(symbol, statement, period_type) if records is None else {"records": records, "columns": [], "units": {}}
    return {
        "source": "stockanalysis",
        "view": "financial_statements",
        "symbol": symbol,
        "ticker_symbol": symbol,
        "company_name": "KCB Group PLC",
        "statement": statement,
        "period_type": period_type,
        "source_url": fin.statement_url(symbol, statement, period_type),
        "units": parsed.get("units"),
        "columns": parsed.get("columns"),
        "records": parsed["records"],
        "scraped_at": scraped_at,
    }


class _SqliteCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "test.sqlite3")
        self.backend = SQLiteBackend(db_path=self.db_path)
        self.backend.local_fallback_dir = os.path.join(self._tmp.name, "fallback")
        self.backend.open()
        self.addCleanup(self.backend.close)

    def query(self, sql, *params):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()


class TestFinancialStatementsStorage(_SqliteCase):
    def test_schema_matches_shipped_sql_and_alembic_uses_the_same_ddl(self):
        from nse_scraper.db.canonical_schema import FINANCIALS_TABLES

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        reference = sqlite3.connect(":memory:")
        self.addCleanup(reference.close)
        with open(os.path.join(root, "sql", "sqlite", "003_financials.sql"), encoding="utf-8") as handle:
            reference.executescript(handle.read())
        live = sqlite3.connect(self.db_path)
        self.addCleanup(live.close)
        for table in FINANCIALS_TABLES:
            expected = [(r[1], r[2], r[3], r[5]) for r in reference.execute("PRAGMA table_info({})".format(table))]
            actual = [(r[1], r[2], r[3], r[5]) for r in live.execute("PRAGMA table_info({})".format(table))]
            self.assertTrue(expected, "{} missing from the shipped DDL".format(table))
            self.assertEqual(expected, actual, table)
        with open(os.path.join(root, "alembic", "versions", "20260913_0003_financial_statements.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("from nse_scraper.db.canonical_schema import FINANCIALS_SCHEMA_SQL, FINANCIALS_TABLES", source)
        self.assertNotIn("CREATE TABLE", source)

    def test_records_are_stored_with_first_seen_at(self):
        self.assertTrue(self.backend.record_financial_statements(_item()))
        rows = self.query(
            "SELECT ticker_symbol, statement, period_type, fiscal_period_end, line_item, value, value_raw, unit, first_seen_at "
            "FROM financial_statements WHERE line_item='revenue' ORDER BY fiscal_period_end DESC"
        )
        self.assertEqual(len(rows), 6)  # TTM + 5 fiscal years
        self.assertEqual(rows[1], ("KCB", "income", "annual", "2025-12-31", "revenue", 173395.0, "173,395", "millions_kes", "2026-09-13T07:02:00+00:00"))
        # the instrument row is created on first sight, like observations do
        self.assertEqual(self.query("SELECT ticker_symbol FROM instruments"), [("KCB",)])

    def test_rescrape_of_an_unchanged_page_inserts_nothing(self):
        self.backend.record_financial_statements(_item())
        before = self.query("SELECT COUNT(*) FROM financial_statements")[0][0]
        self.backend.record_financial_statements(_item(scraped_at="2026-09-20T07:02:00+00:00"))
        self.assertEqual(self.query("SELECT COUNT(*) FROM financial_statements")[0][0], before)
        first, last = self.query("SELECT first_seen_at, last_seen_at FROM financial_statements WHERE line_item='revenue' AND fiscal_label='FY 2025'")[0]
        self.assertEqual(first, "2026-09-13T07:02:00+00:00")
        self.assertEqual(last, "2026-09-20T07:02:00+00:00")

    def test_a_restated_value_is_appended_and_the_original_kept(self):
        self.backend.record_financial_statements(_item())
        restated = _item(scraped_at="2026-11-01T07:02:00+00:00")
        for record in restated["records"]:
            if record["line_item"] == "revenue" and record["fiscal_label"] == "FY 2025":
                record["value"] = 175000.0
                record["value_raw"] = "175,000"
        self.backend.record_financial_statements(restated)
        rows = self.query(
            "SELECT value, first_seen_at FROM financial_statements WHERE line_item='revenue' AND fiscal_label='FY 2025' ORDER BY first_seen_at"
        )
        self.assertEqual(rows, [(173395.0, "2026-09-13T07:02:00+00:00"), (175000.0, "2026-11-01T07:02:00+00:00")])
        # point-in-time: on 2026-10-01 only the original was known
        known = self.query(
            "SELECT value FROM financial_statements WHERE line_item='revenue' AND fiscal_label='FY 2025' AND first_seen_at <= '2026-10-01'"
        )
        self.assertEqual(known, [(173395.0,)])

    def test_alias_resolves_to_the_canonical_ticker(self):
        connection = sqlite3.connect(self.db_path)
        now = "2026-09-13T00:00:00+00:00"
        connection.execute("INSERT INTO instruments (ticker_symbol, company_name, created_at, updated_at) VALUES ('ABSA','Absa Bank Kenya',?,?)", (now, now))
        connection.execute("INSERT INTO instrument_aliases (source_ticker, canonical_ticker, reason, evidence, created_at) VALUES ('BBK','ABSA','rename','test',?)", (now,))
        connection.commit()
        connection.close()
        self.backend.record_financial_statements(_item(symbol="BBK", records=[{
            "ticker_symbol": "BBK", "statement": "income", "period_type": "annual", "fiscal_period_end": "2025-12-31",
            "fiscal_label": "FY 2025", "line_item": "revenue", "label": "Revenue", "row_key": None,
            "value": 1.0, "value_raw": "1", "unit": "millions_kes", "currency": "KES",
        }]))
        self.assertEqual(self.query("SELECT ticker_symbol, source_ticker FROM financial_statements"), [("ABSA", "BBK")])

    def test_empty_item_is_rejected_without_touching_the_database(self):
        self.assertFalse(self.backend.record_financial_statements(_item(records=[])))
        self.assertFalse(self.backend.record_financial_statements({"records": [{"x": 1}]}))
        self.assertEqual(self.query("SELECT COUNT(*) FROM financial_statements")[0][0], 0)

    def test_a_malformed_record_goes_to_the_fallback_file(self):
        item = _item(records=[{"ticker_symbol": "KCB", "statement": "income"}])  # missing keys
        self.assertFalse(self.backend.record_financial_statements(item))
        files = os.listdir(self.backend.local_fallback_dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].startswith("financial_statements_fallback-"))

    def test_every_fixture_page_stores_and_is_idempotent(self):
        # The annual and quarterly ratios pages both carry the same "Current" column,
        # so the stored count is the number of distinct keys, not of parsed cells.
        keys = set()
        for symbol in ("KCB", "SCOM", "KEGN"):
            for statement in fin.STATEMENTS:
                for period in fin.PERIOD_TYPES:
                    item = _item(symbol, statement, period)
                    if item["records"]:
                        self.assertTrue(self.backend.record_financial_statements(item))
                        for r in item["records"]:
                            keys.add((symbol, r["statement"], r["period_type"], r["fiscal_period_end"], r["line_item"], r["value_raw"]))
        total = len(keys)
        self.assertGreater(total, 7000)
        self.assertEqual(self.query("SELECT COUNT(*) FROM financial_statements")[0][0], total)
        for symbol in ("KCB", "SCOM", "KEGN"):
            for statement in fin.STATEMENTS:
                for period in fin.PERIOD_TYPES:
                    item = _item(symbol, statement, period)
                    if item["records"]:
                        self.backend.record_financial_statements(item)
        self.assertEqual(self.query("SELECT COUNT(*) FROM financial_statements")[0][0], total)
        self.assertEqual(sorted(r[0] for r in self.query("SELECT DISTINCT ticker_symbol FROM financial_statements")), ["KCB", "KEGN", "SCOM"])


class TestFundamentalSnapshots(_SqliteCase):
    def _record(self, scraped_at, price=94.0):
        return {
            "ticker_symbol": "KCB",
            "company_name": "KCB Group PLC",
            "rank": 3,
            "stock_price": price,
            "stock_change": -0.265,
            "scraped_at": scraped_at,
            "overview_metrics": {"marketCap": 302065504610, "revenue": 184508072000},
            "performance_metrics": None,
            "dividends_metrics": {"dps": 6.0, "dividendYield": 6.23, "payoutRatio": 29.26},
            "price_metrics": {"volume": 375298, "low52": 52.5, "high52": 101.0},
            "profile_metrics": {"industry": "Commercial Banks"},
        }

    def test_each_scraped_view_is_snapshotted_once_per_day(self):
        self.assertTrue(self.backend.upsert_stockanalysis_stock(self._record("2026-09-13T07:02:00+00:00")))
        rows = self.query("SELECT snapshot_date, view, metrics, stock_price FROM fundamental_snapshots ORDER BY view")
        self.assertEqual([r[1] for r in rows], ["dividends", "overview", "price", "profile"])
        self.assertTrue(all(r[0] == "2026-09-13" for r in rows))
        self.assertEqual(json.loads(rows[0][2]), {"dps": 6.0, "dividendYield": 6.23, "payoutRatio": 29.26})
        self.assertEqual(rows[0][3], 94.0)

    def test_second_run_same_day_is_a_no_op_but_next_day_appends(self):
        self.backend.upsert_stockanalysis_stock(self._record("2026-09-13T07:02:00+00:00"))
        self.backend.upsert_stockanalysis_stock(self._record("2026-09-13T18:00:00+00:00", price=95.0))
        self.assertEqual(self.query("SELECT COUNT(*) FROM fundamental_snapshots")[0][0], 4)
        self.assertEqual(self.query("SELECT stock_price FROM fundamental_snapshots WHERE view='overview'"), [(94.0,)])
        self.backend.upsert_stockanalysis_stock(self._record("2026-09-14T07:02:00+00:00", price=96.0))
        self.assertEqual(self.query("SELECT COUNT(*) FROM fundamental_snapshots")[0][0], 8)
        # the per-ticker row is still overwritten as before
        self.assertEqual(self.query("SELECT stock_price FROM stockanalysis_stocks"), [(96.0,)])

    def test_snapshot_failure_does_not_fail_the_upsert(self):
        with mock.patch.object(self.backend, "_record_fundamental_snapshot", side_effect=RuntimeError("boom")):
            # the upsert wraps everything; a snapshot error is logged and the record
            # falls back like any other failure - but the stockanalysis row was written
            self.assertFalse(self.backend.upsert_stockanalysis_stock(self._record("2026-09-13T07:02:00+00:00")))
        self.assertEqual(self.query("SELECT COUNT(*) FROM stockanalysis_stocks")[0][0], 1)


# --- pipeline ------------------------------------------------------------------------


class _RecordingStorage:
    def __init__(self, ok=True):
        self.items = []
        self.ok = ok

    def open(self):
        pass

    def close(self):
        pass

    def record_financial_statements(self, item):
        self.items.append(item)
        return self.ok

    def upsert_stockanalysis_stock(self, record):
        return True


class _Stats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1):
        self.values[key] = self.values.get(key, 0) + count


class TestPipelineRouting(unittest.TestCase):
    def _pipeline(self, storage):
        pipeline = StockAnalysisPipeline(
            db_backend="supabase", supabase_url="https://example.supabase.co", supabase_key="fake",
            stockanalysis_table="stockanalysis_stocks", stats=_Stats(),
        )
        pipeline.storage = storage
        return pipeline

    def test_statement_items_are_written_immediately_not_buffered(self):
        storage = _RecordingStorage()
        pipeline = self._pipeline(storage)
        item = _item()
        self.assertIs(pipeline.process_item(item), item)
        self.assertEqual(len(storage.items), 1)
        self.assertEqual(pipeline._buffer, {})
        self.assertEqual(pipeline.stats.values, {FINANCIALS_OK_STAT: 1})

    def test_failed_statement_write_is_counted(self):
        pipeline = self._pipeline(_RecordingStorage(ok=False))
        pipeline.process_item(_item())
        self.assertEqual(pipeline.stats.values, {FINANCIALS_FAILED_STAT: 1})

    def test_storage_exception_is_counted_not_raised(self):
        storage = _RecordingStorage()
        storage.record_financial_statements = mock.Mock(side_effect=RuntimeError("disk"))
        pipeline = self._pipeline(storage)
        pipeline.process_item(_item())
        self.assertEqual(pipeline.stats.values, {FINANCIALS_FAILED_STAT: 1})

    def test_without_storage_items_pass_through(self):
        pipeline = self._pipeline(None)
        item = _item()
        self.assertIs(pipeline.process_item(item), item)


# --- spider --------------------------------------------------------------------------


class TestSpiderStatementRequests(unittest.TestCase):
    def test_eight_requests_per_symbol(self):
        spider = StockAnalysisScraperSpider()
        with mock.patch.object(StockAnalysisScraperSpider, "_FINANCIALS_SYMBOLS", ("KCB",)):
            requests = list(spider._financial_statement_requests(["KCB", "SCOM"], {"KCB": {"n": "KCB Group"}}, "2026-09-13T07:00:00+00:00"))
        self.assertEqual(len(requests), 8)
        urls = {r.url for r in requests}
        self.assertIn("https://stockanalysis.com/quote/nase/KCB/financials/income-statement/", urls)
        self.assertIn("https://stockanalysis.com/quote/nase/KCB/financials/ratios/?p=quarterly", urls)
        self.assertEqual(requests[0].cb_kwargs["base"], {"n": "KCB Group"})

    def test_rotation_is_a_daily_window_with_its_own_cap(self):
        spider = StockAnalysisScraperSpider()
        symbols = ["S{}".format(i) for i in range(20)]
        with mock.patch.object(StockAnalysisScraperSpider, "_FINANCIALS_SYMBOLS", ()), \
             mock.patch.object(StockAnalysisScraperSpider, "_FINANCIALS_MAX_SYMBOLS", 8):
            first = spider._financial_symbols_for_this_run(symbols)
            again = spider._financial_symbols_for_this_run(symbols)
        self.assertEqual(len(first), 8)
        self.assertEqual(first, again)  # same day, same slice
        self.assertTrue(set(first) <= set(symbols))

    def test_disabled_yields_nothing(self):
        spider = StockAnalysisScraperSpider()
        with mock.patch.object(StockAnalysisScraperSpider, "_FINANCIALS_ENABLED", False):
            self.assertEqual(spider._financial_symbols_for_this_run(["KCB"]), [])

    def test_pinned_symbols_are_filtered_to_the_known_list(self):
        spider = StockAnalysisScraperSpider()
        with mock.patch.object(StockAnalysisScraperSpider, "_FINANCIALS_SYMBOLS", ("KCB", "NOPE")):
            self.assertEqual(spider._financial_symbols_for_this_run(["SCOM", "KCB"]), ["KCB"])

    def test_parse_statement_page_emits_one_item(self):
        from scrapy.http import HtmlResponse

        spider = StockAnalysisScraperSpider()
        response = HtmlResponse(
            url=fin.statement_url("KCB", fin.INCOME), body=fixture("KCB", fin.INCOME, fin.ANNUAL).encode("utf-8"), encoding="utf-8"
        )
        items = list(spider._parse_statement_page(response, "KCB", fin.INCOME, fin.ANNUAL, {"n": "KCB Group PLC"}, "2026-09-13T07:00:00+00:00"))
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["view"], "financial_statements")
        self.assertEqual(item["company_name"], "KCB Group PLC")
        self.assertEqual(item["source_url"], fin.statement_url("KCB", fin.INCOME))
        self.assertGreater(len(item["records"]), 200)

    def test_empty_page_emits_nothing(self):
        from scrapy.http import HtmlResponse

        spider = StockAnalysisScraperSpider()
        response = HtmlResponse(url="https://x/", body=fixture("KCB", fin.CASHFLOW, fin.QUARTERLY).encode("utf-8"), encoding="utf-8")
        self.assertEqual(list(spider._parse_statement_page(response, "KCB", fin.CASHFLOW, fin.QUARTERLY, {}, "t")), [])


if __name__ == "__main__":
    unittest.main()
