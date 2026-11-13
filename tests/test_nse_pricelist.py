"""Tests for the NSE daily price-list parser.

Every fixture line below is copied verbatim from tesseract's output for the real list
dated 11-NOV-26, OCR noise included. Inventing clean input would test a scan that does
not exist: the mangled ISINs, the comma-for-decimal and the split volume column are the
actual conditions this parser has to survive.
"""
import unittest

from nse_scraper.nse_pricelist import (
    normalise_company,
    parse_line,
    parse_pricelist,
    resolve_ticker,
    to_number,
    validate,
)

# Verbatim OCR, 11-NOV-26.
KCB = "101.00 35.00 KCB Group Plc Ord 1.00 KE0000000315 91.00 89.50 89.75 89.75 768,131"
# Volume split into two tokens by the scan: "166 895".
EQTY = (
    "109.00 41.20 Equity Group Holdings Plc Ord 0.50 KE0000000554 "
    "100.00 99.00 99.50 99.25 166 895"
)
# ISIN mangled past any digit-confusion allow-list ("oovo"), comma used as a decimal.
DTB = (
    "198.50 66.00 Diamond Trust Bank Kenya Ltd Ord 4.00 KEoovo000158 "
    "190,00 186.50 187.75 188.00 15,603"
)
# Dropped decimal points: the day's low 1.36 read as 136, previous 1.34 as 134.
NBV = (
    "5.00 114 Nairobi Business Ventures Ple Ord. 0.50sue KE5000000090 "
    "1.47 136 1.40 134 65,574"
)
# Suspended: a status flag and only two numbers, so no day's range at all.
DEACONS = "0.45 0.45 Deacons (East Africa) Ple Ord 2.50 KE5000005438 s 0.45 0.45"
LEGEND = "Low: The lowest transaction price inthe last 12 months"
DISCLAIMER = "| DISCLAIMER: Utmost care has been taken in the preparation of this report."


class TestToNumber(unittest.TestCase):
    def test_thousands_separator_is_removed(self):
        self.assertEqual(to_number("768,131"), 768131.0)

    def test_comma_with_two_digits_is_a_decimal_point(self):
        """The scan renders 554.00 as 554,00. Reading it as 55400 is a 100x error."""
        self.assertEqual(to_number("554,00"), 554.0)
        self.assertEqual(to_number("23,35"), 23.35)

    def test_a_letter_in_the_number_is_not_a_number(self):
        """OCR reads 1,741 as L741. Guessing at it would invent a price."""
        self.assertIsNone(to_number("L741"))

    def test_spaces_inside_a_number_are_closed_up(self):
        self.assertEqual(to_number("166 895"), 166895.0)


class TestParseLine(unittest.TestCase):
    def test_a_clean_row(self):
        row = parse_line(KCB)
        self.assertEqual(row.name, "KCB Group Plc Ord 1.00")
        self.assertEqual((row.wk52_high, row.wk52_low), (101.0, 35.0))
        self.assertEqual((row.high, row.low, row.vwap), (91.0, 89.5, 89.75))
        self.assertEqual(row.previous, 89.75)
        self.assertEqual(row.volume, 768131.0)

    def test_a_split_volume_does_not_shift_the_price_columns(self):
        """Anchoring on the ISIN rather than counting back from the end.

        With a "last five tokens" rule, "166 895" makes 99.25 look like the volume and
        every price shifts one column left - silently, with plausible numbers.
        """
        row = parse_line(EQTY)
        self.assertEqual(row.previous, 99.25)
        self.assertEqual(row.volume, 166895.0)

    def test_a_badly_mangled_isin_still_anchors_the_row(self):
        row = parse_line(DTB)
        self.assertEqual(row.name, "Diamond Trust Bank Kenya Ltd Ord 4.00")
        self.assertEqual(row.high, 190.0)  # "190,00"
        self.assertEqual(row.previous, 188.0)

    def test_a_suspended_row_without_a_day_range_is_not_a_row(self):
        self.assertIsNone(parse_line(DEACONS))

    def test_legend_and_disclaimer_lines_are_not_rows(self):
        self.assertIsNone(parse_line(LEGEND))
        self.assertIsNone(parse_line(DISCLAIMER))


class TestValidate(unittest.TestCase):
    def test_a_sound_row_passes(self):
        self.assertIsNone(validate(parse_line(KCB)))

    def test_a_dropped_decimal_point_is_refused(self):
        """1.36 read as 136 cannot sit inside a 1.40-1.47 day range.

        This is the check that makes OCR safe to store: the error is loud instead of
        becoming a hundredfold-wrong close price.
        """
        reason = validate(parse_line(NBV))
        self.assertIsNotNone(reason)
        self.assertIn("136", reason)

    def test_a_close_outside_its_own_52_week_band_is_refused(self):
        row = parse_line(KCB)
        row.previous = 4200.0  # a misread, not a move
        self.assertIn("52-week band", validate(row))

    def test_a_vwap_outside_the_day_range_is_refused(self):
        row = parse_line(KCB)
        row.vwap = 427.5
        self.assertIn("outside the day's range", validate(row))


class TestResolveTicker(unittest.TestCase):
    """The list prints company names; stock_observations keys on tickers."""

    UNIVERSE = {
        "KCB": "KCB Group Plc",
        "CGEN": "Car and General (K) Ltd",
        "COOP": "Co-operative Bank of Kenya Ltd",
        "CIC": "CIC Insurance Group Ltd",
        "TPSE": "TPS Eastern Africa (Serena) Ltd",
        "CTUM": "Centum Investment Company Plc",
        "ICDC": "Centum Investment",
    }

    def resolve(self, printed):
        return resolve_ticker(printed, self.UNIVERSE)

    def test_the_share_class_is_not_part_of_the_name(self):
        self.assertEqual(self.resolve("KCB Group Plc Ord 1.00"), "KCB")

    def test_ampersand_matches_the_word_and(self):
        """The exchange prints "Car & General", the master "Car and General"."""
        self.assertEqual(self.resolve("Car & General (K) Ltd Ord 5.00"), "CGEN")

    def test_a_leading_the_is_ignored(self):
        self.assertEqual(
            self.resolve("The Co-operative Bank of Kenya Ltd Ord 1.00"), "COOP"
        )

    def test_the_corporate_form_need_not_agree(self):
        """The list prints CIC as Plc - and the scan as "Ple" - the master holds Ltd."""
        self.assertEqual(self.resolve("CIC Insurance Group Ple Ord.1.00"), "CIC")

    def test_the_master_may_hold_the_longer_name(self):
        """"TPS Eastern Africa" on the list, "(Serena)" only in the master."""
        self.assertEqual(self.resolve("TPS Eastern Africa Ltd Ord 1.00"), "TPSE")

    def test_an_unknown_company_resolves_to_nothing(self):
        self.assertIsNone(self.resolve("Some Unlisted Holdings Plc Ord 1.00"))

    def test_two_equally_good_candidates_resolve_to_nothing(self):
        """Guessing would put a real price against the wrong instrument."""
        self.assertIsNone(
            resolve_ticker(
                "Example Holdings Plc Ord 1.00",
                {"AAA": "Example Holdings Plc", "BBB": "Example Holdings Ltd"},
            )
        )

    def test_an_alias_outranks_an_ambiguous_master(self):
        """CTUM and ICDC both carry "Centum Investment" and both are active ordinary
        lines, so token matching cannot separate them and would refuse the row. The
        alias is how that is settled - explicitly, and visible in review.
        """
        ambiguous = {"CTUM": "Centum Investment Company Plc", "ICDC": "Centum Investment"}
        self.assertEqual(resolve_ticker("Centum Investment Co Plc Ord 0.50", ambiguous), "CTUM")

    def test_an_alias_settles_what_the_scan_corrupted(self):
        """The scan reads HF Group as "HFCB Group"; no token match can recover that."""
        self.assertEqual(resolve_ticker("HFCB Group Plc Ord 5.00", self.UNIVERSE), "HFCK")
        self.assertEqual(resolve_ticker("Brita Holdings Ple Ord 0.10", self.UNIVERSE), "BRIT")

    def test_a_rights_line_cannot_absorb_an_ordinary_price(self):
        """Callers pass ordinary lines only; a rights line shares the whole name.

        Included so the constraint is recorded where it is relied upon: with the rights
        line present there is no unique answer, which is why the runner filters on
        instrument_type before it ever gets here.
        """
        with_rights = dict(self.UNIVERSE)
        with_rights["TPSE-R"] = "TPS Eastern Africa (Serena) (Rights)"
        self.assertIsNone(resolve_ticker("TPS Eastern Africa Ltd Ord 1.00", with_rights))


class TestParsePricelist(unittest.TestCase):
    def test_accepted_and_rejected_are_reported_separately(self):
        """A caller must be able to say how much of the scan was unreadable."""
        accepted, rejected = parse_pricelist(
            "\n".join([LEGEND, KCB, EQTY, NBV, DISCLAIMER, DEACONS])
        )
        self.assertEqual([row.name for row in accepted],
                         ["KCB Group Plc Ord 1.00", "Equity Group Holdings Plc Ord 0.50"])
        self.assertEqual(len(rejected), 1)
        self.assertIn("Nairobi Business Ventures", rejected[0][0].name)


if __name__ == "__main__":
    unittest.main()
