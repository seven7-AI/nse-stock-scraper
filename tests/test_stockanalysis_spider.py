"""
Tests for StockAnalysis scraper spider.
"""
import unittest

from scrapy.http import HtmlResponse, Request

from nse_scraper.spiders.stockanalysis_scraper import StockAnalysisScraperSpider


EMBEDDED_FIXTURE_HTML = """
<html>
  <body>
    <script>
      {
        __sveltekit_i308kc = { base: "" };
        const element = document.currentScript.parentElement;
        Promise.resolve().then(() => {
          kit.start(app, element, {
            data: [{type:"data",data:{
              stockData:[
                {no:1,s:"nase/SCOM",n:"Safaricom PLC",marketCap:1360221280600,price:33.85,change:-.295,revenue:399964500000,tr1m:13.97,tr6m:25.84,trYTD:19.40,tr1y:97.77,tr5y:15.09,tr10y:275.63,dps:1.5,dividendYield:4.42,dividendGrowth:25,exDivDate:"Feb 26, 2026",payoutRatio:71.06,payoutFrequency:"Semi-Annual",volume:2235327,low52:17,low52ch:99.12,high52:34.2,high52ch:-1.02,industry:"Radiotelephone Communications",country:"Kenya",employees:6462,founded:1997},
                {no:2,s:"nase/EQTY",n:"Equity Group Holdings Plc",marketCap:283025610150,price:75,change:-2.28,revenue:176545609000,tr1m:8.70,tr6m:37.62,trYTD:12.36,tr1y:72.53,tr5y:183.24,tr10y:230.13,dps:4.25,dividendYield:5.54,dividendGrowth:6.25,exDivDate:"May 26, 2025",payoutRatio:0,payoutFrequency:"Annual",volume:415562,low52:41.2,low52ch:82.04,high52:78,high52ch:-3.85,industry:"Commercial Banks",country:"Kenya",employees:13083,founded:1984}
              ],
              pagination:false,
              stockFixed:{},
              initialDynamicViews:{default:"Overview",active:"Overview",items:[
                {name:"Overview",ids:["no","s","n","marketCap","price","change","revenue"]},
                {name:"Performance",ids:["no","s","tr1m","tr6m","trYTD","tr1y","tr5y","tr10y"]},
                {name:"Dividends",ids:["no","s","dps","dividendYield","dividendGrowth","exDivDate","payoutRatio","payoutFrequency"]},
                {name:"Price",ids:["no","s","price","change","volume","low52","low52ch","high52","high52ch"]},
                {name:"Profile",ids:["no","s","n","industry","country","employees","founded"]}
              ]},
              columnId:"exchange"
            },uses:{}}]
          });
        });
      }
    </script>
  </body>
</html>
"""


class TestStockAnalysisScraperSpider(unittest.TestCase):
    def setUp(self):
        self.spider = StockAnalysisScraperSpider()

    def _response_from_html(self, html):
        request = Request(url="https://stockanalysis.com/list/nairobi-stock-exchange/")
        return HtmlResponse(
            url=request.url,
            request=request,
            body=html.encode("utf-8"),
            encoding="utf-8",
        )

    def test_spider_configuration(self):
        self.assertEqual(self.spider.name, "stockanalysis_scraper")
        self.assertIn("stockanalysis.com", self.spider.allowed_domains)
        self.assertTrue(self.spider.start_urls)

    def test_parse_embedded_payload_for_all_views(self):
        response = self._response_from_html(EMBEDDED_FIXTURE_HTML)
        items = list(self.spider.parse(response))

        self.assertEqual(len(items), 10)
        views = {item["view"] for item in items}
        self.assertEqual(
            views, {"overview", "performance", "dividends", "price", "profile"}
        )

        perf_item = next(
            item
            for item in items
            if item["symbol"] == "SCOM" and item["view"] == "performance"
        )
        self.assertEqual(perf_item["rank"], 1)
        self.assertEqual(perf_item["metrics"]["tr1m"], 13.97)
        self.assertEqual(perf_item["metrics"]["tr10y"], 275.63)

        dividend_item = next(
            item
            for item in items
            if item["symbol"] == "SCOM" and item["view"] == "dividends"
        )
        self.assertEqual(dividend_item["metrics"]["dps"], 1.5)
        self.assertEqual(dividend_item["metrics"]["exDivDate"], "Feb 26, 2026")

        profile_item = next(
            item
            for item in items
            if item["symbol"] == "EQTY" and item["view"] == "profile"
        )
        self.assertEqual(profile_item["company_name"], "Equity Group Holdings Plc")
        self.assertEqual(profile_item["metrics"]["country"], "Kenya")

    def test_normalize_metric_value(self):
        self.assertEqual(self.spider._normalize_metric_value("1,500.00"), 1500.0)
        self.assertEqual(self.spider._normalize_metric_value("1.36T"), 1.36e12)
        self.assertEqual(self.spider._normalize_metric_value("-2.28%"), -2.28)
        self.assertIsNone(self.spider._normalize_metric_value("-"))
        self.assertEqual(self.spider._normalize_metric_value("Feb 26, 2026"), "Feb 26, 2026")


if __name__ == "__main__":
    unittest.main()
