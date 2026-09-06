"""
Integration tests for nse_scraper - End-to-end functionality
"""
import unittest
import os
import sys
from pathlib import Path
from nse_scraper.db import SUPPORTED_BACKENDS, SQLiteBackend, create_backend


class TestProjectStructure(unittest.TestCase):
    """Test project file structure and imports"""

    def test_project_root_exists(self):
        """Test project root directory exists"""
        project_root = Path(__file__).parent.parent
        self.assertTrue(project_root.exists())

    def test_nse_scraper_package_exists(self):
        """Test nse_scraper package is importable"""
        try:
            import nse_scraper
            self.assertTrue(True)
        except ImportError:
            self.fail("nse_scraper package not importable")

    def test_spider_module_exists(self):
        """Test spider module can be imported"""
        try:
            from nse_scraper.spiders import afx_scraper
            self.assertTrue(True)
        except ImportError:
            self.fail("Spider module not found")

    def test_items_module_exists(self):
        """Test items module can be imported"""
        try:
            from nse_scraper import items
            self.assertTrue(True)
        except ImportError:
            self.fail("Items module not found")

    def test_settings_module_exists(self):
        """Test settings module can be imported"""
        try:
            from nse_scraper import settings
            self.assertTrue(True)
        except ImportError:
            self.fail("Settings module not found")

    def test_pipelines_module_exists(self):
        """Test pipelines module can be imported"""
        try:
            from nse_scraper import pipelines
            self.assertTrue(True)
        except ImportError:
            self.fail("Pipelines module not found")


class TestDependencies(unittest.TestCase):
    """Test required dependencies are installed"""

    def test_scrapy_installed(self):
        """Test Scrapy is installed"""
        try:
            import scrapy
            self.assertTrue(True)
        except ImportError:
            self.fail("Scrapy not installed")

    def test_sqlite3_available(self):
        """The default backend needs stdlib sqlite3 with the JSON1 extension.

        JSON1 is not optional here: the metrics columns are stored as JSON text and both
        the migration report and the documented queries use json_extract.
        """
        import sqlite3

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        value = connection.execute("SELECT json_extract('{\"a\": 1}', '$.a')").fetchone()[0]
        self.assertEqual(value, 1)

    def test_supabase_installed(self):
        """Test Supabase client is installed (alternate backend)"""
        try:
            import supabase
            self.assertTrue(True)
        except ImportError:
            self.fail("Supabase client not installed")

    def test_python_dotenv_installed(self):
        """Test python-dotenv is installed"""
        try:
            import dotenv
            self.assertTrue(True)
        except ImportError:
            self.fail("python-dotenv not installed")

    def test_requests_installed(self):
        """Test requests is installed"""
        try:
            import requests
            self.assertTrue(True)
        except ImportError:
            self.fail("requests not installed")


class TestConfigurationFiles(unittest.TestCase):
    """Test configuration files exist"""

    def test_requirements_file_exists(self):
        """Test requirements.txt exists"""
        project_root = Path(__file__).parent.parent
        requirements_file = project_root / "requirements.txt"
        self.assertTrue(requirements_file.exists())

    def test_scrapy_config_exists(self):
        """Test scrapy.cfg exists"""
        project_root = Path(__file__).parent.parent
        scrapy_config = project_root / "scrapy.cfg"
        self.assertTrue(scrapy_config.exists())

    def test_dockerfile_exists(self):
        """Test Dockerfile exists"""
        project_root = Path(__file__).parent.parent
        dockerfile = project_root / "deployment" / "Dockerfile"
        self.assertTrue(dockerfile.exists())

    def test_docker_compose_exists(self):
        """Test docker-compose.yml exists"""
        project_root = Path(__file__).parent.parent
        docker_compose = project_root / "deployment" / "docker-compose.yml"
        self.assertTrue(docker_compose.exists())


class TestBackendFactory(unittest.TestCase):
    """Test storage backend factory behavior"""

    def test_invalid_backend_raises(self):
        with self.assertRaises(ValueError):
            create_backend("invalid-backend")

    def test_supabase_backend_requires_credentials(self):
        with self.assertRaises(ValueError):
            create_backend("supabase", supabase_url=None, supabase_key=None)

    def test_sqlite_backend_requires_a_path(self):
        with self.assertRaises(ValueError):
            create_backend("sqlite", sqlite_path=None)

    def test_sqlite_backend_is_selectable(self):
        backend = create_backend("sqlite", sqlite_path="data/nse_scraper.sqlite3")
        self.assertIsInstance(backend, SQLiteBackend)

    def test_every_supported_backend_name_is_constructible(self):
        """SUPPORTED_BACKENDS is what the pipelines and the spider gate on.

        A name listed there but rejected by create_backend would make the stockanalysis
        spider install a pipeline whose constructor then raises.
        """
        self.assertIn("sqlite", SUPPORTED_BACKENDS)
        for name in SUPPORTED_BACKENDS:
            with self.subTest(backend=name):
                backend = create_backend(
                    name,
                    sqlite_path="data/nse_scraper.sqlite3",
                    supabase_url="https://example.supabase.co",
                    supabase_key="fake",
                )
                self.assertTrue(hasattr(backend, "upsert_stock"))
                self.assertTrue(hasattr(backend, "upsert_stockanalysis_stock"))


class TestSqlitePersistenceConfig(unittest.TestCase):
    """The database must live on a host-mounted volume, or `run --rm` discards it."""

    def setUp(self):
        project_root = Path(__file__).parent.parent
        self.compose = (project_root / "deployment" / "docker-compose.yml").read_text()

    def test_data_directory_is_bind_mounted(self):
        self.assertIn("../data:/app/data", self.compose)

    def test_sqlite_path_points_inside_the_mount(self):
        self.assertIn("SQLITE_DB_PATH: /app/data/", self.compose)

    def test_compose_selects_the_sqlite_backend(self):
        self.assertIn("DB_BACKEND: sqlite", self.compose)


if __name__ == "__main__":
    unittest.main()
