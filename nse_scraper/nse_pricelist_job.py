"""Fetch, OCR and store one day of the NSE daily price list.

The I/O half of ``nse_scraper.nse_pricelist``, kept apart from it so the parsing and
validation rules stay pure and testable without a network or a database.

Shape of a run: resolve the day's URL, fetch it conditionally, render the pages to
images, OCR them, parse and validate the rows, resolve each company name to a ticker,
and insert what survives. Every stage reports what it dropped, because the failure this
whole effort came from was a pipeline that reported success while delivering nothing.

Conditional fetching is not an optimisation. The list is about a megabyte and does not
change after it is published, so re-downloading it on every run is load the exchange
has no reason to carry - and asking for less is this project's recorded answer to being
rate-limited, rather than disguising the client.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sqlite3
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone

from nse_scraper.nse_pricelist import parse_pricelist, resolve_ticker

logger = logging.getLogger(__name__)

BASE_URL = "https://www.nse.co.ke/dataservices/wp-content/uploads/"

#: Identifies this client and gives an operator somewhere to look before blocking it.
USER_AGENT = "nse-stock-scraper/1.0 (+https://github.com/seven7-AI/nse-stock-scraper)"

DATA_SOURCE = "nse_pricelist"

#: What a stored row declares about itself. ``ocr_extracted`` because the exchange
#: publishes only a scan; ``previous_close_as_observation`` because the value kept is
#: the list's PREVIOUS PRICE stamped with the list's own date - the same one-day lag the
#: rows from the daily scrape already carry, continued deliberately so the series does
#: not change convention halfway through.
QUALITY_FLAGS = ["ocr_extracted", "previous_close_as_observation"]

OBSERVATION_COLUMNS = (
    "ticker_symbol", "trade_date", "source_ticker", "company_name",
    "close_price", "day_low", "day_high", "year_low", "year_high", "volume",
    "data_source", "source_file", "source_date_raw", "quality_flags",
    "created_at", "updated_at",
)

_INSERT = "INSERT OR IGNORE INTO stock_observations ({}) VALUES ({})".format(
    ", ".join(OBSERVATION_COLUMNS), ", ".join("?" for _ in OBSERVATION_COLUMNS)
)

#: "Statistics as of 11-Nov-2026" / "November 11, 2026" on the sheet itself. Used only
#: to record what the scan claimed; the filename is what dates the rows.
PRINTED_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2},? \d{4})")


class ImportResult:
    """What one day's import did, in enough detail to explain a thin run."""

    def __init__(self, day):
        self.day = day
        self.fetched = False
        self.not_modified = False
        self.rows_accepted = 0
        self.rows_refused = 0
        self.rows_unresolved = 0
        self.inserted = 0
        self.already_present = 0
        self.refusals = []
        self.unresolved = []
        self.error = None

    def as_dict(self):
        return {
            "day": self.day.isoformat(),
            "fetched": self.fetched,
            "not_modified": self.not_modified,
            "rows_accepted": self.rows_accepted,
            "rows_refused": self.rows_refused,
            "rows_unresolved": self.rows_unresolved,
            "inserted": self.inserted,
            "already_present": self.already_present,
            "refusals": self.refusals[:20],
            "unresolved": self.unresolved[:20],
            "error": self.error,
        }

    def __repr__(self):
        return "ImportResult({})".format(self.as_dict())


def list_filename(day):
    """``2026-11-11`` -> ``11-NOV-26.pdf``, the exchange's own naming."""
    return "{:02d}-{}-{:02d}.pdf".format(
        day.day, day.strftime("%b").upper(), day.year % 100
    )


def list_url(day):
    return BASE_URL + list_filename(day)


def fetch_list(day, cache_dir, timeout=60):
    """The day's PDF on disk, fetched only when we do not already hold it.

    Returns ``(path, not_modified)``. A 404 is not an error worth raising: the exchange
    publishes nothing on a weekend or a public holiday, and a caller walking a date
    range needs to step over those quietly.
    """
    os.makedirs(cache_dir, exist_ok=True)
    name = list_filename(day)
    path = os.path.join(cache_dir, name)
    meta_path = path + ".meta.json"

    headers = {"User-Agent": USER_AGENT}
    if os.path.exists(path) and os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as handle:
                last_modified = json.load(handle).get("last_modified")
            if last_modified:
                headers["If-Modified-Since"] = last_modified
        except (OSError, ValueError):
            pass

    request = urllib.request.Request(list_url(day), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            last_modified = response.headers.get("Last-Modified")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            logger.info("price list for %s unchanged, using the cached copy", day)
            return path, True
        if exc.code == 404:
            logger.info("no price list published for %s", day)
            return None, False
        raise

    with open(path, "wb") as handle:
        handle.write(body)
    if last_modified:
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump({"last_modified": last_modified}, handle)
    return path, False


def ocr_pdf(pdf_path, dpi=600, psm=6):
    """The scan as text.

    ``--psm 6`` - a single uniform block - keeps the columns in reading order; the
    default segmentation interleaves them and the price columns end up shuffled between
    instruments.

    600 dpi rather than the more usual 300, measured on the list dated 05-NOV-26: 300
    yields 45 usable rows and 7 refusals, 600 yields 50 and 2, because what the scan
    loses first is the decimal point. It costs about 48 seconds and 390 MB for the
    whole list, once a day.
    """
    for binary in ("pdftoppm", "tesseract"):
        if shutil.which(binary) is None:
            raise RuntimeError(
                "{} is not installed; the exchange publishes this list only as a scan "
                "(apt-get install tesseract-ocr poppler-utils)".format(binary)
            )
    workdir = tempfile.mkdtemp(prefix="nse-pricelist-")
    try:
        prefix = os.path.join(workdir, "page")
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", pdf_path, prefix],
            check=True, capture_output=True,
        )
        pages = sorted(
            os.path.join(workdir, name)
            for name in os.listdir(workdir)
            if name.endswith(".png")
        )
        chunks = []
        for page in pages:
            done = subprocess.run(
                ["tesseract", page, "stdout", "--psm", str(psm)],
                check=True, capture_output=True,
            )
            chunks.append(done.stdout.decode("utf-8", errors="replace"))
        return "\n".join(chunks)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def ordinary_instruments(connection):
    """Ticker -> company name for ordinary lines only.

    A rights line carries its parent's whole name, so leaving those in makes every such
    row ambiguous and drops a real price.
    """
    rows = connection.execute(
        "SELECT ticker_symbol, company_name FROM instruments "
        "WHERE instrument_type = 'ordinary'"
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def import_day(db_path, day, cache_dir, ocr_text=None):
    """Fetch, read and store one day. ``ocr_text`` bypasses the network, for tests."""
    result = ImportResult(day)
    try:
        if ocr_text is None:
            path, not_modified = fetch_list(day, cache_dir)
            if path is None:
                return result
            result.fetched = True
            result.not_modified = not_modified
            ocr_text = ocr_pdf(path)
        else:
            result.fetched = True
    except Exception as exc:  # noqa: BLE001 - reported, never silently swallowed
        result.error = "{}: {}".format(type(exc).__name__, exc)
        logger.exception("price list for %s could not be read", day)
        return result

    accepted, refused = parse_pricelist(ocr_text)
    result.rows_accepted = len(accepted)
    result.rows_refused = len(refused)
    result.refusals = ["{}: {}".format(row.name, why) for row, why in refused]

    printed = PRINTED_DATE.search(ocr_text)
    source_date_raw = printed.group(1) if printed else None
    now = datetime.now(timezone.utc).isoformat()
    flags = json.dumps(QUALITY_FLAGS)
    source_file = list_filename(day)

    connection = sqlite3.connect(db_path)
    try:
        universe = ordinary_instruments(connection)
        payload = []
        for row in accepted:
            ticker = resolve_ticker(row.name, universe)
            if ticker is None:
                result.rows_unresolved += 1
                result.unresolved.append(row.name)
                continue
            payload.append((
                ticker, day.isoformat(), ticker, row.name,
                row.previous, row.low, row.high, row.wk52_low, row.wk52_high, row.volume,
                DATA_SOURCE, source_file, source_date_raw, flags, now, now,
            ))
        with connection:
            before = connection.total_changes
            connection.executemany(_INSERT, payload)
            result.inserted = connection.total_changes - before
        result.already_present = len(payload) - result.inserted
    finally:
        connection.close()

    logger.info("price list %s: %s", day, result.as_dict())
    return result
