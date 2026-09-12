"""Historical NSE archive ingestion (2007-2024 yearly CSVs -> stock_observations).

Kept separate from the daily scraper: the scraper never imports this package, and this
package never scrapes. Both write to the same canonical tables through
nse_scraper.db.backends.SQLiteBackend.

    readers    -> raw rows out of the four header variants
    normalize  -> dates, numbers (sign preserved), tickers, names
    lineage    -> ticker aliases and instrument typing, with evidence
    sectors    -> official NSE sector labels from the five sector files
    repairs    -> the three evidence-based 2009 date corrections
    importer   -> idempotent load into the canonical tables
    validate   -> the post-import report
"""
