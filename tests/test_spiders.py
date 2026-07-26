"""
Tests for nse_scraper spiders - Spider functionality
"""
import unittest
from scrapy import Request
from nse_scraper.middlewares import NseScraperDownloaderMiddleware
from nse_scraper.spiders.afx_scraper import AfxScraperSpider


class TestAfxScraperSpider(unittest.TestCase):
    """Test AfxScraperSpider configuration and methods"""

    def setUp(self):
        """Set up spider instance for testing"""
        self.spider = AfxScraperSpider()

    def test_spider_name(self):
        """Test spider has correct name"""
        self.assertEqual(self.spider.name, "afx_scraper")

    def test_spider_allowed_domains(self):
        """Test spider allowed domains are configured"""
        self.assertIn("afx.kwayisi.org", self.spider.allowed_domains)

    def test_spider_start_urls(self):
        """Test spider has start URLs"""
        self.assertTrue(len(self.spider.start_urls) > 0)
        self.assertIn("afx.kwayisi.org", self.spider.start_urls[0])

    def test_clean_text_method(self):
        """Test _clean_text removes whitespace"""
        result = self.spider._clean_text(["  Hello", "World  "])
        self.assertEqual(result, "Hello World")
        
        result = self.spider._clean_text(["Multiple", "Spaces"])
        self.assertNotIn("  ", result)

    def test_clean_price_conversion(self):
        """Test _clean_price converts string to float"""
        # Valid price
        result = self.spider._clean_price("42.50")
        self.assertEqual(result, 42.50)
        self.assertIsInstance(result, float)
        
        # Integer price
        result = self.spider._clean_price("100")
        self.assertEqual(result, 100.0)

    def test_clean_price_invalid(self):
        """Test _clean_price handles invalid input"""
        result = self.spider._clean_price("invalid")
        self.assertIsNone(result)
        
        result = self.spider._clean_price("")
        self.assertIsNone(result)
        
        result = self.spider._clean_price(None)
        self.assertIsNone(result)

    def test_spider_has_parse_method(self):
        """Test spider has parse method"""
        self.assertTrue(hasattr(self.spider, "parse"))
        self.assertTrue(callable(self.spider.parse))

    def test_spider_does_not_shadow_the_settings_user_agent(self):
        """The old spider-level UA was truncated and overrode the full one in settings."""
        self.assertIsNone(getattr(self.spider, "user_agent", None))


class _FakeSettings(dict):
    def get(self, name, default=None):
        return dict.get(self, name, default)


class TestAfxProxySupport(unittest.TestCase):
    """afx.kwayisi.org refuses this host, so its traffic can optionally be proxied."""

    def setUp(self):
        self.spider = AfxScraperSpider()
        self.request = Request(url="https://afx.kwayisi.org/nse/")

    def _process(self, settings):
        middleware = NseScraperDownloaderMiddleware(settings=_FakeSettings(settings))
        middleware.process_request(self.request, self.spider)
        return self.request.meta.get("proxy")

    def test_no_proxy_when_unset(self):
        self.assertIsNone(self._process({}))
        self.assertIsNone(self._process({"AFX_PROXY_URL": "   "}))

    def test_proxy_applied_when_configured(self):
        self.assertEqual(
            self._process({"AFX_PROXY_URL": "http://proxy.example:3128"}),
            "http://proxy.example:3128",
        )

    def test_proxy_is_scoped_to_afx_only(self):
        class _Other:
            name = "stockanalysis_scraper"

        middleware = NseScraperDownloaderMiddleware(
            settings=_FakeSettings({"AFX_PROXY_URL": "http://proxy.example:3128"})
        )
        request = Request(url="https://stockanalysis.com/list/nairobi-stock-exchange/")
        middleware.process_request(request, _Other())
        self.assertNotIn("proxy", request.meta)

    def test_explicit_request_proxy_is_not_overridden(self):
        self.request.meta["proxy"] = "http://explicit:8080"
        self.assertEqual(
            self._process({"AFX_PROXY_URL": "http://proxy.example:3128"}),
            "http://explicit:8080",
        )


if __name__ == "__main__":
    unittest.main()
