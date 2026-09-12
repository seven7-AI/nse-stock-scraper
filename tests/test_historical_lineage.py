import os
import unittest

from nse_scraper.historical import lineage, normalize, readers

ARCHIVE = os.environ.get(
    "NSE_ARCHIVE_DIR",
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "Nairobi-stock-Exchange", "NSE_DATA")),
)


class TestResolve(unittest.TestCase):
    def test_known_aliases(self):
        self.assertEqual(lineage.resolve("BBK"), "ABSA")
        self.assertEqual(lineage.resolve("CFCI"), "LBTY")
        self.assertEqual(lineage.resolve("C&G"), "CGEN")

    def test_unaliased_is_identity(self):
        self.assertEqual(lineage.resolve("KCB"), "KCB")
        self.assertEqual(lineage.resolve("CIC"), "CIC")  # NOT an alias target; see test below

    def test_every_alias_has_evidence(self):
        for alias in lineage.TICKER_ALIASES:
            self.assertTrue(alias.evidence, alias.source_ticker)
            self.assertIn(alias.reason, ("rebrand", "merger", "listing_code_change"))


class TestClassify(unittest.TestCase):
    def test_suffix_conventions(self):
        self.assertEqual(lineage.classify("KCB-R"), ("rights", "KCB"))
        self.assertEqual(lineage.classify("KPLC-P7"), ("preference", "KPLC"))
        self.assertEqual(lineage.classify("^NASI"), ("index", None))

    def test_rights_on_aliased_parent_resolve_the_parent(self):
        self.assertEqual(lineage.classify("NIC-R"), ("rights", "NCBA"))
        self.assertEqual(lineage.classify("CFC-R"), ("rights", "SBIC"))

    def test_known_non_ordinary(self):
        self.assertEqual(lineage.classify("GLD"), ("etf", None))
        self.assertEqual(lineage.classify("LAPR"), ("reit", None))
        self.assertEqual(lineage.classify("KCB"), ("ordinary", None))


@unittest.skipUnless(os.path.isdir(ARCHIVE), "real archive not available")
class TestAliasesAgainstTheArchive(unittest.TestCase):
    """An alias is only valid if the two codes never trade at the same time."""

    @classmethod
    def setUpClass(cls):
        spans = {}
        for path in readers.list_price_files(ARCHIVE):
            for raw in readers.read_price_file(path):
                code = normalize.normalize_ticker(raw.code)
                date = normalize.parse_date(raw.date_raw)
                if not code or not date:
                    continue
                lo, hi = spans.get(code, (date, date))
                spans[code] = (min(lo, date), max(hi, date))
        cls.spans = spans

    def test_no_alias_pair_overlaps(self):
        for alias in lineage.TICKER_ALIASES:
            old = self.spans.get(alias.source_ticker)
            new = self.spans.get(alias.canonical_ticker)
            self.assertIsNotNone(old, alias.source_ticker)
            self.assertIsNotNone(new, alias.canonical_ticker)
            self.assertLess(old[1], new[0], "{} overlaps {}".format(alias.source_ticker, alias.canonical_ticker))

    def test_the_rejected_alias_really_does_overlap(self):
        """CFCI -> CIC was proposed and rejected; the archive shows why."""
        self.assertGreaterEqual(self.spans["CFCI"][1], self.spans["CIC"][0])


if __name__ == "__main__":
    unittest.main()
