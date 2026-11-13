"""Tests for the price-list import.

``import_day`` takes OCR text directly, so the storage behaviour is testable without a
network, a PDF or tesseract. The fixture rows are verbatim scan output.
"""
import os
import sqlite3
import tempfile
import unittest
from datetime import date

from nse_scraper.db.canonical_schema import CANONICAL_SCHEMA_SQL
from nse_scraper.nse_pricelist_job import (
    DATA_SOURCE,
    import_day,
    list_filename,
    list_url,
    ordinary_instruments,
)

SCAN = "\n".join([
    "NSE Bectrities paILy price List November 11, 2026",
    "101.00 35.00 KCB Group Plc Ord 1.00 KE0000000315 91.00 89.50 89.75 89.75 768,131",
    "109.00 41.20 Equity Group Holdings Plc Ord 0.50 KE0000000554 "
    "100.00 99.00 99.50 99.25 166 895",
    # A dropped decimal: refused, never stored.
    "5.00 114 Nairobi Business Ventures Ple Ord. 0.50sue KE5000000090 "
    "1.47 136 1.40 134 65,574",
    # Not in the instrument master: reported as unresolved.
    "10.00 1.00 Entirely Unknown Holdings Plc Ord 1.00 KE9999999999 "
    "9.00 8.00 8.50 8.25 1,000",
])


class TestListNaming(unittest.TestCase):
    def test_filename_follows_the_exchange(self):
        self.assertEqual(list_filename(date(2026, 11, 11)), "11-NOV-26.pdf")
        self.assertEqual(list_filename(date(2026, 1, 5)), "05-JAN-26.pdf")

    def test_url_is_under_the_dataservices_uploads(self):
        self.assertTrue(
            list_url(date(2026, 11, 11)).endswith(
                "/dataservices/wp-content/uploads/11-NOV-26.pdf"
            )
        )


class TestImportDay(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = os.path.join(self._tmp.name, "store.sqlite3")
        self.cache = os.path.join(self._tmp.name, "cache")
        connection = sqlite3.connect(self.db)
        connection.executescript(CANONICAL_SCHEMA_SQL)
        connection.executemany(
            "INSERT INTO instruments (ticker_symbol, company_name, instrument_type, "
            "created_at, updated_at) VALUES (?,?,?,datetime(),datetime())",
            [
                ("KCB", "KCB Group Plc", "ordinary"),
                ("EQTY", "Equity Group Holdings Plc", "ordinary"),
                ("TPSE", "TPS Eastern Africa (Serena) Ltd", "ordinary"),
                ("TPSE-R", "TPS Eastern Africa (Serena) (Rights)", "rights"),
            ],
        )
        connection.commit()
        connection.close()

    def rows(self):
        connection = sqlite3.connect(self.db)
        try:
            return {
                row[0]: row[1:]
                for row in connection.execute(
                    "SELECT ticker_symbol, trade_date, close_price, day_low, day_high, "
                    "year_low, year_high, volume, data_source FROM stock_observations"
                )
            }
        finally:
            connection.close()

    def test_the_stored_close_is_the_previous_price_column(self):
        """Measured, not chosen: this is the column the existing series matches."""
        import_day(self.db, date(2026, 11, 11), self.cache, ocr_text=SCAN)
        stored = self.rows()["KCB"]
        self.assertEqual(stored[0], "2026-11-11")
        self.assertEqual(stored[1], 89.75)          # close = PREVIOUS
        self.assertEqual((stored[2], stored[3]), (89.5, 91.0))   # day low/high
        self.assertEqual((stored[4], stored[5]), (35.0, 101.0))  # 52-week band
        self.assertEqual(stored[6], 768131)
        self.assertEqual(stored[7], DATA_SOURCE)

    def test_a_row_whose_numbers_failed_validation_is_not_stored(self):
        result = import_day(self.db, date(2026, 11, 11), self.cache, ocr_text=SCAN)
        self.assertNotIn("NBV", self.rows())
        self.assertEqual(result.rows_refused, 1)
        self.assertIn("Nairobi Business Ventures", result.refusals[0])

    def test_an_unknown_company_is_reported_not_guessed(self):
        result = import_day(self.db, date(2026, 11, 11), self.cache, ocr_text=SCAN)
        self.assertEqual(result.rows_unresolved, 1)
        self.assertIn("Entirely Unknown Holdings", result.unresolved[0])
        self.assertEqual(result.inserted, 2)  # KCB and EQTY only

    def test_a_second_run_of_the_same_day_stores_nothing_new(self):
        """Idempotency comes from the UNIQUE (ticker, trade_date) key, not bookkeeping."""
        first = import_day(self.db, date(2026, 11, 11), self.cache, ocr_text=SCAN)
        second = import_day(self.db, date(2026, 11, 11), self.cache, ocr_text=SCAN)
        self.assertEqual(first.inserted, 2)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.already_present, 2)

    def test_the_run_declares_how_the_numbers_were_obtained(self):
        import_day(self.db, date(2026, 11, 11), self.cache, ocr_text=SCAN)
        connection = sqlite3.connect(self.db)
        flags = connection.execute(
            "SELECT quality_flags FROM stock_observations WHERE ticker_symbol = 'KCB'"
        ).fetchone()[0]
        connection.close()
        self.assertIn("ocr_extracted", flags)
        self.assertIn("previous_close_as_observation", flags)

    def test_only_ordinary_instruments_are_offered_for_matching(self):
        """A rights line carries its parent's whole name and would make it ambiguous."""
        connection = sqlite3.connect(self.db)
        try:
            universe = ordinary_instruments(connection)
        finally:
            connection.close()
        self.assertIn("TPSE", universe)
        self.assertNotIn("TPSE-R", universe)


if __name__ == "__main__":
    unittest.main()
