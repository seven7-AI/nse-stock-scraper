"""
Tests for nse_scraper settings - Configuration validation
"""
import unittest
import os
from nse_scraper import settings
from nse_scraper.db import SUPPORTED_BACKENDS


class TestScrapySettings(unittest.TestCase):
    """Test Scrapy settings configuration"""

    def test_settings_module_exists(self):
        """Test settings module can be imported"""
        self.assertTrue(hasattr(settings, "BOT_NAME"))

    def test_bot_name_configured(self):
        """Test BOT_NAME is set"""
        self.assertIsNotNone(getattr(settings, "BOT_NAME", None))

    def test_spider_modules_configured(self):
        """Test spider modules are configured"""
        spider_modules = getattr(settings, "SPIDER_MODULES", [])
        self.assertTrue(len(spider_modules) > 0)

    def test_logging_configured(self):
        """Test logging level is configured"""
        log_level = getattr(settings, "LOG_LEVEL", None)
        self.assertIn(log_level, ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    def test_db_backend_configured(self):
        """Test DB backend setting exists and names a backend create_backend accepts.

        Asserts membership rather than one literal name: settings.py reads DB_BACKEND from
        the environment (and a repo-root .env), so pinning the value here fails for any
        developer who has selected a different backend, and again on every default change.
        """
        backend = getattr(settings, "DB_BACKEND", None)
        self.assertIn(backend, SUPPORTED_BACKENDS)

    def test_sqlite_path_configured(self):
        """SQLite needs a path; without one create_backend('sqlite') raises."""
        self.assertTrue(getattr(settings, "SQLITE_DB_PATH", None))

    def test_concurrent_requests(self):
        """Test concurrent requests setting"""
        concurrent = getattr(settings, "CONCURRENT_REQUESTS", None)
        self.assertIsNotNone(concurrent)
        self.assertGreater(concurrent, 0)

    def test_download_delay_configured(self):
        """Test download delay is set (respectful scraping)"""
        delay = getattr(settings, "DOWNLOAD_DELAY", 0)
        self.assertGreaterEqual(delay, 0)

    def test_retry_enabled(self):
        """Test retry mechanism is configured"""
        retry_times = getattr(settings, "RETRY_TIMES", 0)
        self.assertGreater(retry_times, 0)

    def test_user_agent_configured(self):
        """Test user agent is configured"""
        user_agent = getattr(settings, "USER_AGENT", None)
        self.assertIsNotNone(user_agent)
        self.assertIsInstance(user_agent, str)
        self.assertGreater(len(user_agent), 0)


class TestEnvironmentSettings(unittest.TestCase):
    """Test environment variable loading"""

    def test_dotenv_loading(self):
        """Test that .env files can be loaded"""
        # This tests that python-dotenv is available and working
        from dotenv import load_dotenv
        self.assertTrue(callable(load_dotenv))


if __name__ == "__main__":
    unittest.main()
