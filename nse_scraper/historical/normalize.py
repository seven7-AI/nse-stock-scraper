"""Value normalisation for the archive.

The one rule that matters most: **the sign of a number is data**. 91,276 Change cells in
the archive are negative. A previous cleaning pass stripped every '-' character, which
turned all of them positive and produced tens of thousands of "change does not match
price" mismatches in its own quality report. Here '-' is a missing marker only when it is
the entire cell.
"""

import re
from datetime import date
from functools import lru_cache

MISSING_TOKENS = frozenset({"", "-", "--", "n/a", "na", "null", "none"})

# The two date layouts in the archive: M/D/YYYY (2007-2012) and D-Mon-YY (2013-2024).
# Hand-parsed rather than strptime: strptime costs ~300us a call and every date string
# repeats once per ticker, so a memoised regex parse is two orders of magnitude faster.
_MDY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DMONY_RE = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
)}


def is_missing(text):
    return (text or "").strip().lower() in MISSING_TOKENS


@lru_cache(maxsize=8192)
def _parse_date_cached(cleaned):
    match = _MDY_RE.match(cleaned)
    if match:
        month, day, year = (int(g) for g in match.groups())
    else:
        match = _DMONY_RE.match(cleaned)
        if match:
            day = int(match.group(1))
            month = _MONTHS.get(match.group(2).lower())
            year = int(match.group(3))
            if year < 100:
                year += 2000
            if month is None:
                return None
        else:
            match = _ISO_RE.match(cleaned)
            if not match:
                return None
            year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_date(text):
    """ISO date string, or None if the cell is missing or unparseable."""
    if is_missing(text):
        return None
    return _parse_date_cached(text.strip())


_NUMBER_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")


def parse_number(text):
    """float, or None. Handles thousands separators and a leading sign. Never strips '-'."""
    if is_missing(text):
        return None
    cleaned = text.strip().replace(" ", "")
    if not _NUMBER_RE.match(cleaned):
        return None
    return float(cleaned.replace(",", ""))


def parse_percent(text):
    """Percentage as a float (e.g. '-0.81%' -> -0.81). Sign preserved."""
    if is_missing(text):
        return None
    cleaned = text.strip().replace(" ", "")
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    return parse_number(cleaned)


def parse_volume(text):
    """Integer share count, or None. Volumes are written with thousands separators."""
    value = parse_number(text)
    if value is None:
        return None
    if value < 0:
        return None
    return int(round(value))


def normalize_ticker(text):
    """Upper-cased, whitespace-trimmed source code. '' if missing."""
    return (text or "").strip().upper()


def normalize_name(text):
    """Collapsed whitespace; '' if missing."""
    return " ".join((text or "").split())
