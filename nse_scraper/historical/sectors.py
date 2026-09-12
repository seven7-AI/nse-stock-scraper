"""Official NSE sector membership from the five sector files.

The files are pure (SECTOR, CODE, NAME) maps with no price data, so they are used for
classification only. Three defects are corrected explicitly, each with the evidence
that justified it; nothing else is touched and no sector is ever guessed.
"""

import csv
import io
import os
import re

from nse_scraper.historical.lineage import resolve

SECTOR_FILE_RE = re.compile(r"NSE_data_stock_market_sectors_(?P<tag>[\d_]+)\.csv$")

#: Label renames the exchange itself made. Old -> current.
SECTOR_LABEL_ALIASES = {
    "Telecommunication and Technology": "Telecommunication",
}

#: Rows whose CODE cell is a sector header that slipped down a column. Dropped.
#: (2023_2024 line 39: "Construction and Allied,Energy and Petroleum," -- cross-checked
#: against 2022, where the six stocks beneath it are correctly Energy and Petroleum.)
HEADER_LEAK_CODES = frozenset({"ENERGY AND PETROLEUM"})

#: Corrections for stocks that inherited the wrong sector from that leaked header.
#: Applied only to the 2023_2024 file; every other file already has them right.
SECTOR_CORRECTIONS = {
    ("2023_2024", "KEGN"): "Energy and Petroleum",
    ("2023_2024", "KPLC"): "Energy and Petroleum",
    ("2023_2024", "KPLC-P4"): "Energy and Petroleum",
    ("2023_2024", "KPLC-P7"): "Energy and Petroleum",
    ("2023_2024", "TOTL"): "Energy and Petroleum",
    ("2023_2024", "UMME"): "Energy and Petroleum",
}

INDICES_LABEL = "Indices"


def list_sector_files(archive_dir):
    found = []
    for name in os.listdir(archive_dir):
        match = SECTOR_FILE_RE.match(name)
        if match:
            found.append((match.group("tag"), os.path.join(archive_dir, name)))
    # Sort so the newest file is last; "2023_2024" sorts after "2022".
    return [path for _, path in sorted(found)]


def file_tag(path):
    match = SECTOR_FILE_RE.search(os.path.basename(path))
    return match.group("tag") if match else None


def _normalize_label(label, code):
    label = " ".join((label or "").split())
    if code.startswith("^") or label.startswith("^"):
        # 2013 wrote each index's own code in the sector column.
        return INDICES_LABEL
    return SECTOR_LABEL_ALIASES.get(label, label)


def read_sector_file(path):
    """Yield (source_code, canonical_ticker, sector, name) from one file, corrected."""
    tag = file_tag(path)
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(io.StringIO(handle.read()))
        next(reader)  # header: SECTOR,CODE,NAME in some spelling
        for cells in reader:
            if len(cells) < 2:
                continue
            code = (cells[1] or "").strip().upper()
            if not code or code in HEADER_LEAK_CODES:
                continue
            sector = _normalize_label(cells[0], code)
            sector = SECTOR_CORRECTIONS.get((tag, code), sector)
            name = " ".join((cells[2] if len(cells) > 2 else "").split())
            yield code, resolve(code), sector, name


def build_sector_map(archive_dir):
    """canonical_ticker -> (sector, source_file). Newest file wins.

    Index rows are kept (sector 'Indices') so they classify as benchmarks; they are
    excluded from equity aggregates by instrument_type, not by absence.
    """
    mapping = {}
    for path in list_sector_files(archive_dir):
        basename = os.path.basename(path)
        for _code, canonical, sector, _name in read_sector_file(path):
            mapping[canonical] = (sector, basename)
    return mapping


def sector_names(archive_dir):
    """Every canonical sector label present after normalisation, sorted."""
    return sorted({sector for sector, _ in build_sector_map(archive_dir).values()})
