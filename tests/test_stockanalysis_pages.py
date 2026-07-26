"""
Tests for StockAnalysis per-symbol page extraction.

These rebuild the performance/dividends/price/profile views that were lost when the
screener API was retired, so the fixtures mirror the real page shapes: values live in
the embedded kit.start payload, and the 52-week range and volume live in visible
two-cell table rows whose classes are generated and unstable.
"""
import unittest

from nse_scraper import stockanalysis_pages as pages
from nse_scraper.spiders.stockanalysis_scraper import StockAnalysisScraperSpider


QUOTE_PAGE_HTML = """
<html><body>
  <table><tbody>
    <tr class="flex flex-col border-b"><td class="whitespace-nowrap">Volume</td>
      <td class="text-smaller font-semibold">707,627</td></tr>
    <tr class="flex flex-col border-b"><td class="whitespace-nowrap">52-Week Range</td>
      <td class="text-smaller font-semibold">25.50 - 37.30</td></tr>
    <tr class="flex flex-col border-b"><td>Open</td><td>35.45 - 35.70</td></tr>
  </tbody></table>
  <script>kit.start(app, element, {data:[{type:"data",data:{
    infoTable:[{t:"Industry",v:"Radiotelephone Communications",u:null},{t:"Founded",v:1997},
               {t:"Employees",v:"6,616",u:"quote/nase/SCOM/employees/"}],
    payoutRatio:"83.81%",ch1y:"+30.88%",description:"Safaricom PLC provides services."
  }}]});</script>
</body></html>
"""

DIVIDEND_PAGE_HTML = """
<html><body>
  <script>kit.start(app, element, {data:[{type:"data",data:{
    infoBox:"Safaricom has an annual dividend of 2.30 KES per share.",
    infoTable:{yield:"6.46%",annual:"2.30 KES",exdiv:"Aug 5, 2026",frequency:"Semi-Annual",
      dividendFrequencyListUrl:"",payoutRatio:"83.81%",growth:"66.67%",years:"n/a"},
    history:[{dt:"2026-08-05",amt:"1.150 KES"}]
  }}]});</script>
</body></html>
"""

COMPANY_PAGE_HTML = """
<html><body>
  <script>kit.start(app, element, {data:[{type:"data",data:{
    profile:{name:"Safaricom PLC",country:"Kenya",founded:1997,ipoDate:null,
      industry:{value:"Radiotelephone Communications",url:void 0},
      sector:{value:void 0,url:void 0},
      employees:{value:6616,url:"stocks/nase-scom/employees/"}}
  }}]});</script>
</body></html>
"""


class TestSymbolPageUrls(unittest.TestCase):
    def test_symbol_page_url_per_page(self):
        self.assertEqual(
            pages.symbol_page_url("SCOM", pages.QUOTE_PAGE),
            "https://stockanalysis.com/quote/nase/SCOM/",
        )
        self.assertEqual(
            pages.symbol_page_url("scom", pages.DIVIDEND_PAGE),
            "https://stockanalysis.com/quote/nase/SCOM/dividend/",
        )
        self.assertEqual(
            pages.symbol_page_url("SCOM", pages.COMPANY_PAGE),
            "https://stockanalysis.com/quote/nase/SCOM/company/",
        )

    def test_unknown_page_is_rejected(self):
        with self.assertRaises(ValueError):
            pages.symbol_page_url("SCOM", "not-a-page")

    def test_default_pages_exclude_company_to_limit_request_volume(self):
        self.assertEqual(
            pages.DEFAULT_SYMBOL_PAGES, (pages.QUOTE_PAGE, pages.DIVIDEND_PAGE)
        )
        self.assertIn(pages.COMPANY_PAGE, pages.SYMBOL_PAGES)


class TestHelpers(unittest.TestCase):
    def test_extract_js_object_handles_nested_braces(self):
        text = 'profile:{a:1,industry:{value:"X"},b:2} ,other:{}'
        self.assertEqual(
            pages.extract_js_object(text, "profile"),
            '{a:1,industry:{value:"X"},b:2}',
        )

    def test_extract_js_object_ignores_braces_inside_strings(self):
        text = 'infoTable:{note:"a } brace",yield:"6%"}'
        self.assertEqual(
            pages.extract_js_object(text, "infoTable"),
            '{note:"a } brace",yield:"6%"}',
        )

    def test_extract_js_object_missing_key(self):
        self.assertIsNone(pages.extract_js_object("nothing here", "profile"))

    def test_split_range(self):
        self.assertEqual(pages.split_range("25.50 - 37.30"), ("25.50", "37.30"))
        self.assertEqual(pages.split_range(""), (None, None))
        self.assertEqual(pages.split_range("no dash"), (None, None))

    def test_strip_currency(self):
        self.assertEqual(pages.strip_currency("2.30 KES"), "2.30")
        self.assertEqual(pages.strip_currency("6.46%"), "6.46%")
        self.assertEqual(pages.strip_currency(None), None)

    def test_label_value_pairs_keys_on_label_text(self):
        pairs = pages.label_value_pairs(QUOTE_PAGE_HTML)
        self.assertEqual(pairs["Volume"], "707,627")
        self.assertEqual(pairs["52-Week Range"], "25.50 - 37.30")


class TestPageParsers(unittest.TestCase):
    def setUp(self):
        spider = StockAnalysisScraperSpider()
        self.normalize = spider._normalize_metric_value
        self.loads = spider._loads_js_like

    def test_quote_page_yields_price_performance_and_profile(self):
        base = {"price": 35.6}
        views = pages.parse_quote_page(QUOTE_PAGE_HTML, self.normalize, base=base)

        self.assertEqual(set(views), {"price", "performance", "profile"})
        price = views["price"]
        self.assertEqual(price["volume"], 707627)
        self.assertEqual(price["low52"], 25.5)
        self.assertEqual(price["high52"], 37.3)
        # Derived from the scraped range against the current price.
        self.assertEqual(price["low52ch"], 39.61)
        self.assertEqual(price["high52ch"], -4.56)
        # Only the 1-year horizon is published for NSE tickers.
        self.assertEqual(views["performance"], {"tr1y": 30.88})
        # Enough profile to make the extra company-page request optional.
        self.assertEqual(
            views["profile"],
            {
                "industry": "Radiotelephone Communications",
                "founded": 1997,
                "employees": 6616,
            },
        )

    def test_dividend_page_yields_dividends_view(self):
        views = pages.parse_dividend_page(DIVIDEND_PAGE_HTML, self.normalize, self.loads)

        self.assertEqual(set(views), {"dividends"})
        self.assertEqual(
            views["dividends"],
            {
                "dps": 2.3,
                "dividendYield": 6.46,
                "dividendGrowth": 66.67,
                "exDivDate": "Aug 5, 2026",
                "payoutRatio": 83.81,
                "payoutFrequency": "Semi-Annual",
            },
        )

    def test_company_page_yields_profile_view(self):
        views = pages.parse_company_page(COMPANY_PAGE_HTML, self.normalize, self.loads)

        self.assertEqual(set(views), {"profile"})
        self.assertEqual(
            views["profile"],
            {
                "industry": "Radiotelephone Communications",
                "country": "Kenya",
                "employees": 6616,
                "founded": 1997,
            },
        )

    def test_pages_without_payload_yield_nothing(self):
        empty = "<html><body>no payload</body></html>"
        self.assertEqual(pages.parse_dividend_page(empty, self.normalize, self.loads), {})
        self.assertEqual(pages.parse_company_page(empty, self.normalize, self.loads), {})
        self.assertEqual(pages.parse_quote_page(empty, self.normalize), {})

    def test_parse_symbol_page_dispatches(self):
        views = pages.parse_symbol_page(
            pages.COMPANY_PAGE, COMPANY_PAGE_HTML, self.normalize, self.loads
        )
        self.assertIn("profile", views)
        with self.assertRaises(ValueError):
            pages.parse_symbol_page("bogus", "", self.normalize, self.loads)


if __name__ == "__main__":
    unittest.main()
