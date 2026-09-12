"""Read the yearly NSE price CSVs into a uniform row shape.

Four header variants exist across 2007-2024 (case, UTF-8 BOM, and the last column named
Adjust / Adjusted / Adjusted Price). Everything downstream sees one shape.
"""

import csv
import hashlib
import io
import os
import re
from collections import namedtuple

# One archive row, before any value normalisation. Strings exactly as the file had them.
RawRow = namedtuple(
    "RawRow",
    [
        "source_file", "source_row", "date_raw", "code", "name",
        "year_low", "year_high", "day_low", "day_high", "close", "previous",
        "change_abs", "change_pct", "volume", "adjusted",
    ],
)

# Lower-cased header -> canonical field. Every variant seen in the archive is listed.
HEADER_MAP = {
    "date": "date_raw",
    "code": "code",
    "name": "name",
    "12m low": "year_low",
    "12m high": "year_high",
    "day low": "day_low",
    "day high": "day_high",
    "day price": "close",
    "previous": "previous",
    "change": "change_abs",
    "change%": "change_pct",
    "volume": "volume",
    "adjust": "adjusted",
    "adjusted": "adjusted",
    "adjusted price": "adjusted",
}

REQUIRED_FIELDS = ("date_raw", "code", "name", "close")

YEAR_FILE_RE = re.compile(r"NSE_data_all_stocks_(?P<year>20\d\d)\.csv$")


def list_price_files(archive_dir):
    """Yearly price files under the archive directory, in year order."""
    files = []
    for name in os.listdir(archive_dir):
        match = YEAR_FILE_RE.match(name)
        if match:
            files.append((int(match.group("year")), os.path.join(archive_dir, name)))
    return [path for _, path in sorted(files)]


def year_of(path):
    match = YEAR_FILE_RE.search(os.path.basename(path))
    return int(match.group("year")) if match else None


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _column_map(header):
    mapped = {}
    for index, raw in enumerate(header):
        key = raw.strip().lstrip("﻿").lower()
        field = HEADER_MAP.get(key)
        if field:
            mapped[field] = index
    missing = [f for f in REQUIRED_FIELDS if f not in mapped]
    if missing:
        raise ValueError("missing required columns {} in header {!r}".format(missing, header))
    return mapped


def read_price_file(path):
    """Yield RawRow for every data row, skipping fully blank lines.

    source_row is the 1-based line number in the file (header is line 1), so a row can
    be found again in the CSV by hand.
    """
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(io.StringIO(handle.read()))
        header = next(reader)
        columns = _column_map(header)
        basename = os.path.basename(path)
        order = ["date_raw", "code", "name", "year_low", "year_high", "day_low", "day_high",
                 "close", "previous", "change_abs", "change_pct", "volume", "adjusted"]
        indices = [columns.get(field, -1) for field in order]
        for line_no, cells in enumerate(reader, start=2):
            if not any(cell.strip() for cell in cells):
                continue
            width = len(cells)
            values = [cells[i].strip() if 0 <= i < width else "" for i in indices]
            yield RawRow(basename, line_no, *values)
