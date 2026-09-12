import os
import shutil
import tempfile
import unittest

from nse_scraper.historical import sectors


class TestSectorFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def _write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_2023_2024_header_leak_is_corrected(self):
        """Replicates line 39 of the real file: a sector header in the CODE column."""
        self._write("NSE_data_stock_market_sectors_2023_2024.csv",
                    "Sector,Stock_code,Stock_name\n"
                    "Construction and Allied,BAMB,Bamburi Cement Ltd\n"
                    "Construction and Allied,Energy and Petroleum,\n"
                    "Construction and Allied,KPLC,Kenya Power and Lighting Company Plc\n"
                    "Construction and Allied,TOTL,TotalEnergies Marketing Kenya Plc\n")
        mapping = sectors.build_sector_map(self.dir)
        self.assertEqual(mapping["BAMB"][0], "Construction and Allied")
        self.assertEqual(mapping["KPLC"][0], "Energy and Petroleum")
        self.assertEqual(mapping["TOTL"][0], "Energy and Petroleum")
        self.assertNotIn("ENERGY AND PETROLEUM", mapping)

    def test_label_rename_and_2013_index_rows(self):
        self._write("NSE_data_stock_market_sectors_2013.csv",
                    "SECTOR,CODE,NAME\n"
                    "Telecommunication and Technology,SCOM,Safaricom Ltd\n"
                    "^NASI,^NASI,NSE All-Share Index\n"
                    ",,\n")
        mapping = sectors.build_sector_map(self.dir)
        self.assertEqual(mapping["SCOM"][0], "Telecommunication")
        self.assertEqual(mapping["^NASI"][0], "Indices")
        self.assertEqual(len(mapping), 2)

    def test_newest_file_wins_and_aliases_resolve(self):
        self._write("NSE_data_stock_market_sectors_2013.csv", "SECTOR,CODE,NAME\nBanking,BBK,Barclays Bank\n")
        self._write("NSE_data_stock_market_sectors_2022.csv", "Sector,Stock_code,Stock_name\nBanking,ABSA,Absa Bank Kenya Plc\n")
        mapping = sectors.build_sector_map(self.dir)
        self.assertIn("ABSA", mapping)
        self.assertNotIn("BBK", mapping)
        self.assertEqual(mapping["ABSA"][1], "NSE_data_stock_market_sectors_2022.csv")


if __name__ == "__main__":
    unittest.main()
