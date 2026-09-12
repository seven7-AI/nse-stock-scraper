"""Evidence-based corrections to source dates.

Four dates in the archive are provably wrong. For three duplicated days in 2009 the
extra block sits, in file order, exactly where a missing weekday should be -- the classic
month/day transposition (4/2 written for 2/4). In 2017 a block is dated 09-May-15 (a
Saturday, two years early) and sits exactly where 2017-05-09 should be -- a year typo.
All four are repaired, and the repair is recorded on every affected row
(quality_flags: date_repaired, source_date_raw: what the file said).

The fourth (2017-03-24) is one contiguous block in which every code appears twice, with
no gap around it. It cannot be attributed to another date and is NOT repaired: the first
occurrence per code is kept and the second is quarantined in stock_observation_conflicts.

Rule for the repaired cases: the misdated block is always the FIRST block carrying that
date in the file, because it belongs to an earlier day and the file is in date order.
"""

from collections import namedtuple

DateRepair = namedtuple("DateRepair", ["source_file", "wrong_date", "correct_date", "evidence"])

DATE_REPAIRS = (
    DateRepair("NSE_data_all_stocks_2009.csv", "2009-01-29", "2009-01-21",
               "first '1/29/2009' block sits between 01-20 and 01-22; 2009-01-21 (Wed) absent"),
    DateRepair("NSE_data_all_stocks_2009.csv", "2009-04-02", "2009-02-04",
               "first '4/2/2009' block sits between 02-03 and 02-05; 2009-02-04 (Wed) absent; M/D transposed"),
    DateRepair("NSE_data_all_stocks_2009.csv", "2009-10-08", "2009-08-10",
               "first '10/8/2009' block sits between 08-07 and 08-11; 2009-08-10 (Mon) absent; M/D transposed"),
    DateRepair("NSE_data_all_stocks_2017.csv", "2015-05-09", "2017-05-09",
               "'09-May-15' block sits between 2017-05-08 and 2017-05-10; 2017-05-09 (Tue) absent; "
               "2015-05-09 was a Saturday; year typo"),
)

_REPAIRS_BY_FILE = {}
for _repair in DATE_REPAIRS:
    _REPAIRS_BY_FILE.setdefault(_repair.source_file, {})[_repair.wrong_date] = _repair


class DateRepairer:
    """Stateful, per-file: tracks which occurrence block of a repairable date we are in."""

    def __init__(self, source_file):
        self._repairs = _REPAIRS_BY_FILE.get(source_file, {})
        self._block_seen = {}     # wrong_date -> number of contiguous blocks started
        self._previous_date = None

    def apply(self, parsed_date):
        """(date_to_store, repair_or_None) for a row, given its parsed source date."""
        repair = self._repairs.get(parsed_date)
        if repair is None:
            self._previous_date = parsed_date
            return parsed_date, None
        if self._previous_date != parsed_date:
            self._block_seen[parsed_date] = self._block_seen.get(parsed_date, 0) + 1
        self._previous_date = parsed_date
        if self._block_seen[parsed_date] == 1:
            return repair.correct_date, repair
        return parsed_date, None
