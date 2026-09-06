"""Database backend adapters for NSE scraper."""

from .backends import SUPPORTED_BACKENDS, SQLiteBackend, SupabaseBackend, create_backend

__all__ = ["SUPPORTED_BACKENDS", "SQLiteBackend", "SupabaseBackend", "create_backend"]
