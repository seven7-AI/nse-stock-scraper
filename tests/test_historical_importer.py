"""The importer against a small synthetic archive laid out exactly like the real one."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from nse_scraper.db.backends import SQLiteBackend
from nse_scraper.historical.importer import HistoricalImporter

HEADER_OLD = "DATE,CODE,NAME,12m Low,12m High,Day Low,Day High,Day Price,Previous,Change,Change%,Volume,Adjust\n"
HEADER_NEW = "Date,Code,Name,12m Low,12m High,Day Low,Day High,Day Price,Previous,Change,Change%,Volume,Adjusted Price\n"


class _ArchiveCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.db = os.path.join(self.dir, "db.sqlite3")
        self._write("NSE_data_stock_market_sectors_2022.csv",
                    "Sector,Stock_code,Stock_name\nBanking,KCB,KCB Group Plc\nBanking,ABSA,Absa Bank Kenya Plc\n")

    def _write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def _run(self, **kwargs):
        with HistoricalImporter(self.db, self.dir) as importer:
            return [r.as_dict() for r in importer.run(**kwargs)]

    def _q(self, sql, params=()):
        connection = sqlite3.connect(self.db)
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()


class TestImportBasics(_ArchiveCase):
    def setUp(self):
        super().setUp()
        self._write("NSE_data_all_stocks_2012.csv", HEADER_OLD +
                    "1/2/2012,KCB,Kenya Commercial Bank,15,25,20.5,21,20.75,20.5,0.25,1.22%,\"1,200,000\",-\n"
                    "1/2/2012,BBK,Barclays Bank Kenya,10,14,12,12.5,12.25,12.5,-0.25,-2.00%,\"300,000\",-\n"
                    "1/3/2012,KCB,Kenya Commercial Bank,15,25,20,21,20.5,20.75,-0.25,-1.20%,-,-\n"
                    ",,,,,,,,,,,,\n")
        self._write("NSE_data_all_stocks_2013.csv", HEADER_NEW +
                    "2-Jan-13,KCB,KCB Group Plc,15,25,21,22,21.5,20.5,1,4.88%,\"2,000,000\",21.5\n"
                    "2-Jan-13,ABSA,Absa Bank Kenya Plc,10,14,12,12.5,12.5,12.25,0.25,2.04%,\"400,000\",12.5\n")

    def test_rows_land_with_signs_and_volumes_intact(self):
        results = self._run()
        self.assertEqual(sum(r["rows_inserted"] for r in results), 5)
        self.assertEqual(sum(r["rows_rejected"] for r in results), 0)
        row = self._q("SELECT close_price, change_abs, change_pct, volume, previous_close FROM stock_observations "
                      "WHERE ticker_symbol='KCB' AND trade_date='2012-01-03'")[0]
        self.assertEqual(row, (20.5, -0.25, -1.2, None, 20.75))   # negative kept; '-' volume is NULL

    def test_alias_resolves_and_source_ticker_is_kept(self):
        self._run()
        rows = self._q("SELECT trade_date, source_ticker FROM stock_observations WHERE ticker_symbol='ABSA' ORDER BY 1")
        self.assertEqual(rows, [("2012-01-02", "BBK"), ("2013-01-02", "ABSA")])
        self.assertEqual(self._q("SELECT count(*) FROM stock_observations WHERE ticker_symbol='BBK'")[0][0], 0)
        self.assertEqual(self._q("SELECT canonical_ticker FROM instrument_aliases WHERE source_ticker='BBK'")[0][0], "ABSA")

    def test_instrument_gets_sector_and_latest_name(self):
        self._run()
        self.assertEqual(self._q("SELECT company_name, sector, first_seen_date, last_seen_date FROM instruments WHERE ticker_symbol='KCB'")[0],
                         ("KCB Group Plc", "Banking", "2012-01-02", "2013-01-02"))

    def test_import_is_idempotent(self):
        first = self._run()
        second = self._run()
        self.assertEqual(sum(r["rows_inserted"] for r in second), 0)
        self.assertEqual(sum(r["rows_already_present"] for r in second), sum(r["rows_read"] for r in first))
        self.assertEqual(self._q("SELECT count(*) FROM stock_observations")[0][0], 5)
        self.assertEqual(self._q("SELECT count(*) FROM stock_observation_conflicts")[0][0], 0)
        self.assertEqual(self._q("SELECT count(*) FROM import_runs")[0][0], 4)  # 2 files x 2 runs

    def test_dry_run_writes_nothing(self):
        results = self._run(dry_run=True)
        self.assertEqual(sum(r["rows_inserted"] for r in results), 5)
        for table in ("stock_observations", "instruments", "instrument_aliases", "import_runs"):
            self.assertEqual(self._q("SELECT count(*) FROM {}".format(table))[0][0], 0, table)

    def test_year_filter(self):
        results = self._run(years=[2013])
        self.assertEqual([r["source_file"] for r in results], ["NSE_data_all_stocks_2013.csv"])


class TestRejectionsAndConflicts(_ArchiveCase):
    def test_row_without_close_is_rejected_and_counted(self):
        self._write("NSE_data_all_stocks_2019.csv", HEADER_OLD +
                    "02-Jan-19,KCB,KCB Group Plc,-,-,-,-,-,-,-,-,-,-\n"
                    "03-Jan-19,KCB,KCB Group Plc,30,45,40,41,40.5,40,0.5,1.25%,100,-\n")
        results = self._run()
        self.assertEqual(results[0]["rows_rejected"], 1)
        self.assertEqual(results[0]["rejections"], {"missing_or_nonpositive_close": 1})
        self.assertEqual(results[0]["rows_inserted"], 1)
        notes = json.loads(self._q("SELECT notes FROM import_runs")[0][0])
        self.assertEqual(notes["rejections"], {"missing_or_nonpositive_close": 1})

    def test_in_file_duplicate_is_quarantined_not_dropped(self):
        """The 2017-03-24 shape: the same (code, date) twice with different prices."""
        self._write("NSE_data_all_stocks_2017.csv", HEADER_OLD +
                    "24-Mar-17,KCB,KCB Group Plc,20,40,30,31,30.5,30,0.5,1.67%,100,-\n"
                    "24-Mar-17,KCB,KCB Group Plc,20,40,30,31,30.75,30,0.75,2.50%,120,-\n")
        results = self._run()
        self.assertEqual((results[0]["rows_inserted"], results[0]["rows_quarantined"]), (1, 1))
        kept = self._q("SELECT id, close_price, source_row FROM stock_observations")[0]
        conflict = self._q("SELECT close_price, source_row, conflict_reason, kept_observation_id FROM stock_observation_conflicts")[0]
        self.assertEqual(kept[1:], (30.5, 2))          # first occurrence kept
        self.assertEqual(conflict, (30.75, 3, "duplicate_in_file", kept[0]))

    def test_date_repair_is_applied_and_audited(self):
        """The 2009-04-02 shape: the first block carrying a repairable date is really 02-04."""
        self._write("NSE_data_all_stocks_2009.csv", HEADER_OLD +
                    "2/3/2009,KCB,Kenya Commercial Bank,15,25,20,21,20.5,20,0.5,2.5%,100,-\n"
                    "4/2/2009,KCB,Kenya Commercial Bank,15,25,20,21,20.6,20.5,0.1,0.49%,100,-\n"   # really 02-04
                    "2/5/2009,KCB,Kenya Commercial Bank,15,25,20,21,20.7,20.6,0.1,0.49%,100,-\n"
                    "4/1/2009,KCB,Kenya Commercial Bank,15,25,20,21,22,21.9,0.1,0.46%,100,-\n"
                    "4/2/2009,KCB,Kenya Commercial Bank,15,25,20,21,22.1,22,0.1,0.45%,100,-\n"   # the real 04-02
                    "4/3/2009,KCB,Kenya Commercial Bank,15,25,20,21,22.2,22.1,0.1,0.45%,100,-\n")
        results = self._run()
        self.assertEqual(results[0]["repairs"], {"2009-02-04": 1})
        self.assertEqual(results[0]["rows_quarantined"], 0)
        repaired = self._q("SELECT close_price, source_date_raw, quality_flags FROM stock_observations WHERE trade_date='2009-02-04'")[0]
        self.assertEqual(repaired, (20.6, "4/2/2009", '["date_repaired"]'))
        self.assertEqual(self._q("SELECT close_price FROM stock_observations WHERE trade_date='2009-04-02'")[0][0], 22.1)


class TestScraperCoexistence(_ArchiveCase):
    """Archive rows and daily scraper rows share the table without treading on each other."""

    def test_scrape_after_import_appends_and_is_idempotent(self):
        self._write("NSE_data_all_stocks_2024.csv", HEADER_NEW +
                    "31-Dec-24,KCB,KCB Group Plc,20,45,40,41,40.5,40,0.5,1.25%,100,40.5\n"
                    "31-Dec-24,ABSA,Absa Bank Kenya Plc,10,20,17,18,17.5,17,0.5,2.94%,100,17.5\n")
        self._run()

        backend = SQLiteBackend(db_path=self.db)
        backend.open()
        self.addCleanup(backend.close)
        scraped_at = "2026-09-12T06:02:00+00:00"
        record = {"ticker_symbol": "BBK", "company_name": "Absa Bank Kenya PLC", "stock_price": 34.95,
                  "stock_change": 0.143, "scraped_at": scraped_at,
                  "price_metrics": {"volume": 2264117, "low52": 25.8, "high52": 39.5}}
        self.assertTrue(backend.upsert_stockanalysis_stock(record))
        self.assertTrue(backend.upsert_stockanalysis_stock(record))   # same day again

        rows = self._q("SELECT trade_date, source_ticker, close_price, volume, data_source FROM stock_observations "
                       "WHERE ticker_symbol='ABSA' ORDER BY trade_date")
        self.assertEqual(rows, [("2024-12-31", "ABSA", 17.5, 100, "nse_archive:2024"),
                                ("2026-09-12", "BBK", 34.95, 2264117, "nse_scraper")])
        # and the per-ticker table the rest of the system reads is unchanged in shape
        self.assertEqual(self._q("SELECT count(*) FROM stockanalysis_stocks")[0][0], 1)

    def test_rerunning_the_import_never_overwrites_a_scraper_row(self):
        self._write("NSE_data_all_stocks_2024.csv", HEADER_NEW +
                    "31-Dec-24,KCB,KCB Group Plc,20,45,40,41,40.5,40,0.5,1.25%,100,40.5\n")
        self._run()
        backend = SQLiteBackend(db_path=self.db); backend.open(); self.addCleanup(backend.close)
        backend.upsert_stockanalysis_stock({"ticker_symbol": "KCB", "company_name": "KCB Group PLC",
                                            "stock_price": 41.0, "scraped_at": "2026-09-12T06:00:00+00:00"})
        self._run()
        self.assertEqual(self._q("SELECT count(*), sum(data_source='nse_scraper') FROM stock_observations WHERE ticker_symbol='KCB'")[0], (2, 1))


if __name__ == "__main__":
    unittest.main()
