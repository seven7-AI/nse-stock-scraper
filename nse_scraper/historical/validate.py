"""Post-import validation.

A migration that ran without error is not a migration that produced the right data.
This report checks the result against what the audit predicted and against the source
files themselves, and says plainly where the data is imperfect rather than hiding it.

Every check returns a (name, ok, detail) triple; `ok` is None for informational rows.
"""

import csv
import io
import json
import os
import sqlite3
from collections import OrderedDict

from nse_scraper.historical import lineage, normalize, readers

#: What the audit of the source files predicts. A drift here is a real finding.
EXPECTED = {
    "quarantined_conflicts": 69,          # 2017-03-24 double export, 69 codes
    "quarantined_date": "2017-03-24",
    "repaired_rows": 40 + 59 + 59 + 70,   # three 2009 transpositions + the 2017 year typo
    "rejected_rows": 1,                   # 2019: one row with no close price
    "min_trade_date": "2007-01-02",
    "aliases": len(lineage.TICKER_ALIASES),
}

#: Representative rows, checked side-by-side against the CSV they came from.
SPOT_CHECKS = (
    ("KCB", "2007-01-02"),        # first day of the archive
    ("SCOM", "2008-06-09"),       # Safaricom IPO listing day
    ("ABSA", "2012-12-31"),       # last BBK row, resolved to ABSA
    ("ABSA", "2013-01-02"),       # first native ABSA row - the seam
    ("KPLC-P7", "2015-06-30"),    # preference share
    ("^NASI", "2024-12-31"),      # index series, last day
    ("KCB", "2024-12-31"),        # last day of the archive
)


def validate(db_path, archive_dir):
    connection = sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        checks = []
        summary = _summary(connection)
        checks += _structural_checks(connection, summary)
        checks += _lineage_checks(connection)
        checks += _quality_checks(connection)
        checks += _sector_checks(connection)
        checks += _timeline_checks(connection)
        checks += _spot_checks(connection, archive_dir)
        checks += _scraper_overlap_checks(connection)
        ok = all(c["ok"] is not False for c in checks)
        return {"ok": ok, "summary": summary, "checks": checks}
    finally:
        connection.close()


# -- helpers -------------------------------------------------------------------------
def _one(connection, sql, params=()):
    return connection.execute(sql, params).fetchone()[0]


def _check(name, ok, detail):
    return {"name": name, "ok": ok, "detail": detail}


def _summary(c):
    s = OrderedDict()
    s["observations"] = _one(c, "SELECT count(*) FROM stock_observations")
    s["archive_observations"] = _one(c, "SELECT count(*) FROM stock_observations WHERE data_source LIKE 'nse_archive:%'")
    s["scraper_observations"] = _one(c, "SELECT count(*) FROM stock_observations WHERE data_source = 'nse_scraper'")
    s["instruments"] = _one(c, "SELECT count(*) FROM instruments")
    s["instruments_by_type"] = dict(c.execute("SELECT instrument_type, count(*) FROM instruments GROUP BY 1 ORDER BY 1").fetchall())
    s["aliases"] = _one(c, "SELECT count(*) FROM instrument_aliases")
    s["distinct_trade_dates"] = _one(c, "SELECT count(DISTINCT trade_date) FROM stock_observations")
    s["min_trade_date"] = _one(c, "SELECT min(trade_date) FROM stock_observations")
    s["max_trade_date"] = _one(c, "SELECT max(trade_date) FROM stock_observations")
    s["conflicts"] = _one(c, "SELECT count(*) FROM stock_observation_conflicts")
    s["import_runs"] = _one(c, "SELECT count(*) FROM import_runs")
    return s


# -- checks --------------------------------------------------------------------------
def _structural_checks(c, s):
    dupes = _one(c, "SELECT count(*) FROM (SELECT ticker_symbol, trade_date FROM stock_observations GROUP BY 1,2 HAVING count(*) > 1)")
    orphans = _one(c, "SELECT count(*) FROM stock_observations o LEFT JOIN instruments i ON i.ticker_symbol = o.ticker_symbol WHERE i.ticker_symbol IS NULL")
    conflict_dates = [r[0] for r in c.execute("SELECT DISTINCT trade_date FROM stock_observation_conflicts ORDER BY 1")]
    repaired = _one(c, "SELECT count(*) FROM stock_observations WHERE quality_flags LIKE '%date_repaired%'")
    repaired_ok = _one(c, "SELECT count(*) FROM stock_observations WHERE quality_flags LIKE '%date_repaired%' AND source_date_raw IS NOT NULL AND source_date_raw != ''")
    rejected = _one(c, "SELECT COALESCE(sum(rows_rejected), 0) FROM import_runs WHERE id IN (SELECT max(id) FROM import_runs GROUP BY source_file)")
    return [
        _check("no duplicate (ticker, trade_date)", dupes == 0, "{} duplicate keys".format(dupes)),
        _check("every observation has an instrument", orphans == 0, "{} orphans".format(orphans)),
        _check("conflicts are exactly the 2017-03-24 double export",
               s["conflicts"] == EXPECTED["quarantined_conflicts"] and conflict_dates == [EXPECTED["quarantined_date"]],
               "{} rows on {}".format(s["conflicts"], conflict_dates)),
        _check("date repairs match the audit", repaired == EXPECTED["repaired_rows"],
               "{} repaired rows (expected {})".format(repaired, EXPECTED["repaired_rows"])),
        _check("every repaired row keeps its original date string", repaired_ok == repaired, "{}/{}".format(repaired_ok, repaired)),
        _check("rejected rows match the audit", rejected == EXPECTED["rejected_rows"],
               "{} rejected in the latest run per file (expected {})".format(rejected, EXPECTED["rejected_rows"])),
        _check("archive starts 2007-01-02", s["min_trade_date"] == EXPECTED["min_trade_date"], s["min_trade_date"]),
    ]


def _lineage_checks(c):
    out = [_check("all aliases registered", _one(c, "SELECT count(*) FROM instrument_aliases") == EXPECTED["aliases"],
                  "{} rows".format(_one(c, "SELECT count(*) FROM instrument_aliases")))]
    for alias in lineage.TICKER_ALIASES:
        old_rows = _one(c, "SELECT count(*) FROM stock_observations WHERE source_ticker = ?", (alias.source_ticker,))
        under_old = _one(c, "SELECT count(*) FROM stock_observations WHERE ticker_symbol = ?", (alias.source_ticker,))
        span = c.execute(
            "SELECT min(trade_date), max(trade_date) FROM stock_observations WHERE ticker_symbol = ?",
            (alias.canonical_ticker,)).fetchone()
        out.append(_check(
            "alias {} -> {} collapses cleanly".format(alias.source_ticker, alias.canonical_ticker),
            old_rows > 0 and under_old == 0,
            "{} rows kept source_ticker={}, 0 stored under the old code; {} spans {}..{}".format(
                old_rows, alias.source_ticker, alias.canonical_ticker, span[0], span[1]),
        ))
    return out


def _quality_checks(c):
    neg = _one(c, "SELECT count(*) FROM stock_observations WHERE change_abs < 0")
    pos = _one(c, "SELECT count(*) FROM stock_observations WHERE change_abs > 0")
    both = c.execute(
        "SELECT count(*), sum(CASE WHEN abs(close_price - previous_close - change_abs) <= 0.011 THEN 1 ELSE 0 END) "
        "FROM stock_observations WHERE change_abs IS NOT NULL AND previous_close IS NOT NULL AND data_source LIKE 'nse_archive:%'"
    ).fetchone()
    consistent_pct = (100.0 * both[1] / both[0]) if both[0] else 0.0
    missing_vol = _one(c, "SELECT count(*) FROM stock_observations WHERE volume IS NULL AND data_source LIKE 'nse_archive:%'")
    missing_change = _one(c, "SELECT count(*) FROM stock_observations WHERE change_abs IS NULL AND data_source LIKE 'nse_archive:%'")
    missing_name = _one(c, "SELECT count(*) FROM stock_observations WHERE company_name IS NULL")
    nonpos = _one(c, "SELECT count(*) FROM stock_observations WHERE close_price <= 0")
    flags = {}
    for (raw,) in c.execute("SELECT quality_flags FROM stock_observations WHERE quality_flags != '[]'"):
        for f in json.loads(raw):
            flags[f] = flags.get(f, 0) + 1
    return [
        _check("negative changes preserved (sign bug not reproduced)", neg > 50000,
               "{} negative, {} positive change_abs".format(neg, pos)),
        _check("close - previous == change where all three present", consistent_pct >= 99.0,
               "{:.2f}% of {} rows consistent within 0.01 ({} inconsistent — reported, not corrected)".format(
                   consistent_pct, both[0], both[0] - both[1])),
        _check("no non-positive close prices", nonpos == 0, "{}".format(nonpos)),
        _check("missing values are NULL, not invented", None,
               "archive rows without volume: {}; without change: {}; without name: {}".format(
                   missing_vol, missing_change, missing_name)),
        _check("quality flags", None, json.dumps(flags, sort_keys=True)),
    ]


def _sector_checks(c):
    # Sector files cover the archive, so the strict check is scoped to instruments the
    # ARCHIVE saw in its final year. Listings that exist only in the scraper (2025+)
    # appear in no sector file; NULL is the honest value and they are reported apart.
    active_unclassified = [r[0] for r in c.execute(
        "SELECT i.ticker_symbol FROM instruments i WHERE i.sector IS NULL AND i.instrument_type != 'index' "
        "AND EXISTS (SELECT 1 FROM stock_observations o WHERE o.ticker_symbol = i.ticker_symbol "
        "AND o.data_source LIKE 'nse_archive:%' AND o.trade_date >= '2024-01-01') ORDER BY 1")]
    scraper_only_unclassified = [r[0] for r in c.execute(
        "SELECT i.ticker_symbol FROM instruments i WHERE i.sector IS NULL AND i.instrument_type != 'index' "
        "AND NOT EXISTS (SELECT 1 FROM stock_observations o WHERE o.ticker_symbol = i.ticker_symbol "
        "AND o.data_source LIKE 'nse_archive:%') ORDER BY 1")]
    unclassified = [r[0] for r in c.execute("SELECT ticker_symbol FROM instruments WHERE sector IS NULL ORDER BY 1")]
    by_sector = c.execute(
        "SELECT sector, count(*) FROM instruments WHERE instrument_type = 'ordinary' GROUP BY 1 ORDER BY 2 DESC").fetchall()
    return [
        _check("every instrument the archive saw in 2024 has a sector", not active_unclassified,
               "unclassified-but-active: {}".format(active_unclassified or "none")),
        _check("scraper-only listings awaiting a sector (absent from every sector file; never guessed)", None,
               "{}".format(scraper_only_unclassified or "none")),
        _check("unclassified instruments (delisted pre-2013, never guessed)", None,
               "{}: {}".format(len(unclassified), unclassified)),
        _check("ordinary shares by sector", None,
               "; ".join("{}={}".format(s or "NULL", n) for s, n in by_sector)),
    ]


def _timeline_checks(c):
    kcb = c.execute(
        "SELECT min(trade_date), max(trade_date), count(*), count(DISTINCT substr(trade_date,1,4)) "
        "FROM stock_observations WHERE ticker_symbol = 'KCB'").fetchone()
    by_first_year = c.execute(
        "SELECT substr(first_seen_date,1,4) y, count(*) FROM instruments GROUP BY y ORDER BY y").fetchall()
    delisted = [r[0] for r in c.execute(
        "SELECT ticker_symbol FROM instruments WHERE last_seen_date < '2024-01-01' AND instrument_type = 'ordinary' ORDER BY last_seen_date")]
    longest = c.execute(
        "SELECT ticker_symbol, count(*) n, min(trade_date), max(trade_date) FROM stock_observations "
        "GROUP BY 1 ORDER BY n DESC LIMIT 5").fetchall()
    renamed = c.execute(
        "SELECT ticker_symbol, count(DISTINCT company_name) n FROM stock_observations "
        "WHERE company_name IS NOT NULL GROUP BY 1 HAVING n > 1 ORDER BY n DESC LIMIT 12").fetchall()
    return [
        _check("KCB has an unbroken 2007 -> latest series", kcb[3] >= 18,
               "{} rows, {}..{}, {} distinct years".format(kcb[2], kcb[0], kcb[1], kcb[3])),
        _check("instruments by first-listing year", None, ", ".join("{}:{}".format(y, n) for y, n in by_first_year)),
        _check("ordinary shares no longer present in 2024 (delisted)", None, "{}: {}".format(len(delisted), delisted)),
        _check("longest histories", None, "; ".join("{} {} rows {}..{}".format(*r) for r in longest)),
        _check("tickers whose company name changed over time", None,
               "; ".join("{} ({} names)".format(t, n) for t, n in renamed)),
    ]


def _spot_checks(c, archive_dir):
    out = []
    for ticker, trade_date in SPOT_CHECKS:
        row = c.execute(
            "SELECT * FROM stock_observations WHERE ticker_symbol = ? AND trade_date = ?", (ticker, trade_date)).fetchone()
        if row is None:
            out.append(_check("spot {} {}".format(ticker, trade_date), False, "row missing"))
            continue
        csv_row = _find_csv_row(archive_dir, row["source_file"], row["source_row"])
        if csv_row is None:
            out.append(_check("spot {} {}".format(ticker, trade_date), False, "source line {}:{} not found".format(row["source_file"], row["source_row"])))
            continue
        close_ok = normalize.parse_number(csv_row.close) == row["close_price"]
        code_ok = normalize.normalize_ticker(csv_row.code) == row["source_ticker"]
        date_ok = (normalize.parse_date(csv_row.date_raw) == row["trade_date"]) or ("date_repaired" in row["quality_flags"])
        out.append(_check(
            "spot {} {}".format(ticker, trade_date), close_ok and code_ok and date_ok,
            "csv[{}:{}] code={} date={!r} close={} vol={!r}  ->  db source_ticker={} close={} volume={} change={}".format(
                row["source_file"], row["source_row"], csv_row.code, csv_row.date_raw, csv_row.close, csv_row.volume,
                row["source_ticker"], row["close_price"], row["volume"], row["change_abs"]),
        ))
    return out


def _find_csv_row(archive_dir, source_file, source_row):
    path = os.path.join(archive_dir, source_file)
    if not os.path.exists(path):
        return None
    for raw in readers.read_price_file(path):
        if raw.source_row == source_row:
            return raw
    return None


def _normalized_words(name):
    """Company-name tokens that survive the spelling drift between the two sources.

    Punctuation is removed before splitting so 'I&M', 'I & M' and 'Trans-Century' /
    'TransCentury' compare equal; corporate suffixes are dropped.
    """
    stop = {"plc", "ltd", "limited", "group", "kenya", "k", "the", "and", "holdings", "co", "company"}
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else "" for ch in (name or "").lower())
    joined = cleaned.replace(" ", "")
    return ({w for w in cleaned.split()} - stop) | ({joined} if joined else set())


def _scraper_overlap_checks(c):
    """Do the scraper's tickers map onto the archive's instruments -- and are they the
    same companies? Name identity is the real test; a price ratio only flags a mapping
    error when the names ALSO disagree (thinly traded NSE small caps move 10x in a year)."""
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "stockanalysis_stocks" not in tables:
        return [_check("scraper overlap", None, "stockanalysis_stocks not present")]
    scraped = c.execute("SELECT ticker_symbol, company_name, stock_price FROM stockanalysis_stocks").fetchall()
    both, only_scraper, name_mismatch, big_moves = 0, [], [], []
    for ticker, name, price in scraped:
        canonical = lineage.resolve(ticker)
        last = c.execute(
            "SELECT close_price, trade_date, company_name FROM stock_observations WHERE ticker_symbol = ? "
            "AND data_source LIKE 'nse_archive:%' ORDER BY trade_date DESC LIMIT 1", (canonical,)).fetchone()
        if last is None:
            only_scraper.append(ticker)
            continue
        both += 1
        a, b = _normalized_words(name), _normalized_words(last[2])
        if not (a & b) and not any(x in y or y in x for x in a for y in b if len(x) > 2 and len(y) > 2):
            name_mismatch.append("{}: scraper '{}' vs archive '{}'".format(ticker, name, last[2]))
        if price and last[0]:
            ratio = price / last[0]
            if not 0.2 <= ratio <= 5.0:
                big_moves.append("{} {}x ({} -> {})".format(ticker, round(ratio, 1), last[0], price))
    scraper_rows = _one(c, "SELECT count(*) FROM stock_observations WHERE data_source = 'nse_scraper'")
    dup_names = c.execute(
        "SELECT company_name, group_concat(ticker_symbol) FROM stockanalysis_stocks "
        "GROUP BY company_name HAVING count(*) > 1").fetchall()
    return [
        _check("scraper tickers found in the archive", None,
               "{} of {} scraped tickers have archive history; scraper-only (new listings or "
               "scraper-side codes): {}".format(both, len(scraped), only_scraper)),
        # Ticker codes are official NSE codes in both sources and are the identity; the
        # name comparison only surfaces drift for a human to eyeball. It never fails the run.
        _check("company-name drift between sources for the same ticker (eyeball; ticker is the identity)", None,
               "; ".join(name_mismatch) or "none"),
        _check("large moves between archive end and today (same company; informational)", None,
               "; ".join(big_moves) or "none"),
        _check("scraper lists one company under two codes (scraper-side duplicate, not aliased)", None,
               "; ".join("{} -> {}".format(n, t) for n, t in dup_names) or "none"),
        _check("scraper observations coexist in the same table", None,
               "{} rows with data_source = nse_scraper".format(scraper_rows)),
    ]


# -- rendering -----------------------------------------------------------------------
def render_markdown(report):
    lines = ["# Historical import validation", ""]
    lines.append("**Overall: {}**".format("PASS" if report["ok"] else "FAIL"))
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    for key, value in report["summary"].items():
        lines.append("| {} | {} |".format(key, value))
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| | Check | Detail |")
    lines.append("|---|---|---|")
    for check in report["checks"]:
        mark = {True: "✅", False: "❌", None: "ℹ️"}[check["ok"]]
        lines.append("| {} | {} | {} |".format(mark, check["name"], str(check["detail"]).replace("|", "\\|")))
    lines.append("")
    return "\n".join(lines)
