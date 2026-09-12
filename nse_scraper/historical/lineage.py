"""Ticker lineage and instrument typing.

Every alias here was verified against the archive's date spans before being written
down: the old code's last observation precedes the new code's first, with no overlap.
An alias whose spans overlapped (CFCI -> CIC, both trading throughout 2012) was rejected
because overlap proves two different companies. The evidence string is stored on the
instrument_aliases row so the justification travels with the data.
"""

import re
from collections import namedtuple

Alias = namedtuple("Alias", ["source_ticker", "canonical_ticker", "reason", "evidence"])

TICKER_ALIASES = (
    Alias("BBK", "ABSA", "rebrand",
          "BBK last 2012-12-31, ABSA first 2013-01-02; Barclays Bank Kenya -> Absa Bank Kenya"),
    Alias("CFC", "SBIC", "rebrand",
          "CFC last 2012-12-31, SBIC first 2013-01-02; CFC Stanbic -> Stanbic Holdings"),
    Alias("NIC", "NCBA", "merger",
          "NIC last 2012-12-31, NCBA first 2013-01-02; NIC Group merged into NCBA Group"),
    Alias("FIRE", "SMER", "listing_code_change",
          "FIRE last 2012-12-31, SMER first 2013-01-02; Sameer Africa (ex Firestone East Africa)"),
    Alias("C&G", "CGEN", "listing_code_change",
          "C&G last 2012-12-31, CGEN first 2013-01-02; Car & General"),
    Alias("FAHR", "LAPR", "rebrand",
          "FAHR last 2022-05-31, LAPR first 2023-03-22; Stanlib Fahari I-REIT -> Laptrust Imara I-REIT"),
    Alias("CFCI", "LBTY", "rebrand",
          "CFCI last 2012-12-31, LBTY first 2013-01-02; both rows named 'Liberty Kenya Holdings'"),
    # Scraper-side code change, not an archive one: the scraper's HFCK row went stale on
    # 2026-07-27 and HFCB appeared the same day, both named 'HFCB Group Plc'. The archive
    # (official NSE codes) knows the company as HFCK through 2024-12-31, so HFCK stays
    # canonical and the scraper's new code resolves onto it.
    Alias("HFCB", "HFCK", "listing_code_change",
          "scraper: HFCK last scraped 2026-07-27, HFCB from 2026-07-27, same name 'HFCB Group Plc'; "
          "archive knows HFCK 2007-01-02..2024-12-31"),
)

_ALIAS_INDEX = {a.source_ticker: a for a in TICKER_ALIASES}

# Suffix conventions used by the NSE data vendor.
_RIGHTS_RE = re.compile(r"^(?P<parent>.+)-R$")
_PREFERENCE_RE = re.compile(r"^(?P<parent>.+)-P\d+$")

# Codes that are not ordinary shares and carry no suffix to say so.
_KNOWN_TYPES = {
    "GLD": "etf",     # NewGold ETF
    "LAPR": "reit",   # Laptrust Imara I-REIT
    "FAHR": "reit",   # Stanlib Fahari I-REIT (alias source; typed for completeness)
}


def resolve(ticker):
    """Canonical ticker for a source code. Unaliased codes resolve to themselves."""
    alias = _ALIAS_INDEX.get(ticker)
    return alias.canonical_ticker if alias else ticker


def alias_for(ticker):
    return _ALIAS_INDEX.get(ticker)


def classify(ticker):
    """(instrument_type, parent_ticker) for a canonical ticker."""
    if ticker.startswith("^"):
        return "index", None
    match = _RIGHTS_RE.match(ticker)
    if match:
        return "rights", resolve(match.group("parent"))
    match = _PREFERENCE_RE.match(ticker)
    if match:
        return "preference", resolve(match.group("parent"))
    return _KNOWN_TYPES.get(ticker, "ordinary"), None
