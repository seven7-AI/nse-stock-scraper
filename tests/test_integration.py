"""
Integration tests for nse_scraper - End-to-end functionality
"""
import unittest
import os
import sys
from pathlib import Path
from nse_scraper.db import create_backend


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

    def test_pymongo_installed(self):
        """Test PyMongo is installed"""
        try:
            import pymongo
            self.assertTrue(True)
        except ImportError:
            self.fail("PyMongo not installed")

    def test_sqlalchemy_installed(self):
        """Test SQLAlchemy is installed"""
        try:
            import sqlalchemy
            self.assertTrue(True)
        except ImportError:
            self.fail("SQLAlchemy not installed")

    def test_alembic_installed(self):
        """Test Alembic is installed"""
        try:
            import alembic
            self.assertTrue(True)
        except ImportError:
            self.fail("Alembic not installed")

    def test_supabase_installed(self):
        """Test Supabase client is installed"""
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
        dockerfile = project_root / "Dockerfile"
        self.assertTrue(dockerfile.exists())

    def test_docker_compose_exists(self):
        """Test docker-compose.yml exists"""
        project_root = Path(__file__).parent.parent
        docker_compose = project_root / "docker-compose.yml"
        self.assertTrue(docker_compose.exists())


class TestBackendFactory(unittest.TestCase):
    """Test storage backend factory behavior"""

    def test_invalid_backend_raises(self):
        with self.assertRaises(ValueError):
            create_backend("invalid-backend")

    def test_mongo_backend_requires_uri(self):
        with self.assertRaises(ValueError):
            create_backend("mongo", mongodb_uri=None)


if __name__ == "__main__":
    unittest.main()
