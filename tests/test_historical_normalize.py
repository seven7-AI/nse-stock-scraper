import unittest

from nse_scraper.historical import normalize


class TestParseDate(unittest.TestCase):
    def test_both_archive_layouts(self):
        self.assertEqual(normalize.parse_date("1/2/2007"), "2007-01-02")      # 2007-2012
        self.assertEqual(normalize.parse_date("12/24/2007"), "2007-12-24")
        self.assertEqual(normalize.parse_date("2-Jan-13"), "2013-01-02")      # 2013-2024
        self.assertEqual(normalize.parse_date("02-Jan-14"), "2014-01-02")
        self.assertEqual(normalize.parse_date("31-Dec-24"), "2024-12-31")

    def test_missing_and_garbage(self):
        for text in ("", "-", "   ", "not a date", "2/30/2009", "31-Foo-13"):
            self.assertIsNone(normalize.parse_date(text), text)


class TestParseNumber(unittest.TestCase):
    def test_sign_is_preserved(self):
        """The bug this module exists to not have: '-' inside a number is a sign."""
        self.assertEqual(normalize.parse_number("-0.25"), -0.25)
        self.assertEqual(normalize.parse_number("-1,234.50"), -1234.5)
        self.assertEqual(normalize.parse_percent("-0.81%"), -0.81)

    def test_lone_dash_is_missing(self):
        self.assertIsNone(normalize.parse_number("-"))
        self.assertIsNone(normalize.parse_percent("-"))
        self.assertIsNone(normalize.parse_volume("-"))

    def test_thousands_separators(self):
        self.assertEqual(normalize.parse_number("3,282.00"), 3282.0)
        self.assertEqual(normalize.parse_volume("1,234,500"), 1234500)

    def test_percent_without_sign_char(self):
        self.assertEqual(normalize.parse_percent("8.24%"), 8.24)
        self.assertEqual(normalize.parse_percent("8.24"), 8.24)

    def test_volume_rejects_negative_and_garbage(self):
        self.assertIsNone(normalize.parse_volume("-5"))
        self.assertIsNone(normalize.parse_volume("abc"))
        self.assertIsNone(normalize.parse_number("1,23"))  # malformed grouping


class TestTickerAndName(unittest.TestCase):
    def test_ticker_upper_and_trim(self):
        self.assertEqual(normalize.normalize_ticker("  kcb "), "KCB")
        self.assertEqual(normalize.normalize_ticker(None), "")

    def test_name_collapses_whitespace(self):
        self.assertEqual(normalize.normalize_name("  KCB   Group  Plc "), "KCB Group Plc")


if __name__ == "__main__":
    unittest.main()
