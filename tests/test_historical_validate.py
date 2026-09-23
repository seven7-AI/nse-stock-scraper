"""The validation report's sector checks, against small synthetic archives.

The sector files cover a period, not "the archive". These tests pin both halves of
that: a listing that first trades after the newest sector file is reported, never
failed; a listing that traded inside the covered window without a sector still fails.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from nse_scraper.historical import sectors
from nse_scraper.historical.importer import HistoricalImporter
from nse_scraper.historical.validate import validate

HEADER = "Date,Code,Name,12m Low,12m High,Day Low,Day High,Day Price,Previous,Change,Change%,Volume,Adjusted Price\n"


def _row(day, code, name, price):
    return "{},{},{},10,30,{},{},{},{},0.25,1.00%,\"1,000\",-\n".format(
        day, code, name, price, price, price, price)


class _SectorCase(unittest.TestCase):
    """An archive whose newest price file is newer than its newest sector file."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = os.path.join(self.dir, "db.sqlite3")
        self._write("NSE_data_stock_market_sectors_2022.csv",
                    "Sector,Stock_code,Stock_name\nBanking,KCB,KCB Group Plc\n")
        self._write("NSE_data_all_stocks_2022.csv", HEADER +
                    _row("3-Jan-22", "KCB", "KCB Group Plc", "40") +
                    _row("4-Jan-22", "KCB", "KCB Group Plc", "41"))

    def _write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def _import(self):
        with HistoricalImporter(self.db, self.dir) as importer:
            importer.run()

    def _report(self):
        return validate(self.db, self.dir)

    def _check(self, report, needle):
        return next(c for c in report["checks"] if needle in c["name"])


class TestCoverageEnd(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def _write(self, name):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
            handle.write("Sector,Stock_code,Stock_name\nBanking,KCB,KCB Group Plc\n")

    def test_the_newest_file_tag_names_the_last_covered_day(self):
        self._write("NSE_data_stock_market_sectors_2020.csv")
        self._write("NSE_data_stock_market_sectors_2023_2024.csv")
        self.assertEqual(sectors.coverage_end(self.dir), "2024-12-31")

    def test_a_single_year_tag_covers_that_year(self):
        self._write("NSE_data_stock_market_sectors_2013.csv")
        self.assertEqual(sectors.coverage_end(self.dir), "2013-12-31")

    def test_no_sector_files_is_no_coverage(self):
        self.assertIsNone(sectors.coverage_end(self.dir))


class TestListingsNewerThanTheSectorFiles(_SectorCase):
    """The 2025 case: a price archive newer than every sector file."""

    def setUp(self):
        super().setUp()
        self._write("NSE_data_all_stocks_2023.csv", HEADER +
                    _row("3-Jan-23", "KCB", "KCB Group Plc", "42") +
                    _row("3-Jan-23", "NEWCO", "Newco Plc", "9"))
        self._import()

    def test_the_new_listing_is_reported_not_failed(self):
        report = self._report()
        strict = self._check(report, "has a sector")
        self.assertIs(strict["ok"], True, strict["detail"])
        self.assertIn("2022-01-01..2022-12-31", strict["detail"])
        reported = self._check(report, "listings newer than the sector files")
        self.assertIn("NEWCO", reported["detail"])
        self.assertIsNone(reported["ok"])

    def test_its_sector_stays_null_and_nothing_is_guessed(self):
        connection = sqlite3.connect(self.db)
        try:
            sector = connection.execute(
                "SELECT sector FROM instruments WHERE ticker_symbol = 'NEWCO'").fetchone()[0]
        finally:
            connection.close()
        self.assertIsNone(sector)


class TestSectorlessInsideTheCoveredWindow(_SectorCase):
    """The re-scope must not defang the check: inside the window it still bites."""

    def setUp(self):
        super().setUp()
        self._write("NSE_data_all_stocks_2022.csv", HEADER +
                    _row("3-Jan-22", "KCB", "KCB Group Plc", "40") +
                    _row("3-Jan-22", "BOGUS", "Bogus Plc", "7"))
        self._import()

    def test_a_code_the_sector_files_should_cover_fails_the_check(self):
        report = self._report()
        strict = self._check(report, "has a sector")
        self.assertIs(strict["ok"], False)
        self.assertIn("BOGUS", strict["detail"])
        self.assertIs(report["ok"], False)


class TestIndicesAndEtfTyping(_SectorCase):
    def setUp(self):
        super().setUp()
        self._write("NSE_data_all_stocks_2023.csv", HEADER +
                    _row("3-Jan-23", "KCB", "KCB Group Plc", "42") +
                    _row("3-Jan-23", "^NASI", "NSE All Share Index", "120") +
                    _row("3-Jan-23", "SMWF", "Satrix MSCI World Feeder ETF", "800"))
        self._import()

    def test_an_index_is_exempt_and_the_etf_is_typed(self):
        connection = sqlite3.connect(self.db)
        try:
            types = dict(connection.execute(
                "SELECT ticker_symbol, instrument_type FROM instruments "
                "WHERE ticker_symbol IN ('^NASI', 'SMWF')").fetchall())
        finally:
            connection.close()
        self.assertEqual(types["^NASI"], "index")
        self.assertEqual(types["SMWF"], "etf")
        strict = self._check(self._report(), "has a sector")
        self.assertIs(strict["ok"], True, strict["detail"])
        self.assertNotIn("^NASI", strict["detail"])


if __name__ == "__main__":
    unittest.main()
