# Canonical stock schema

One row per canonical ticker per trading day, 2007 → today, in the scraper's own SQLite
database (`data/nse_scraper.sqlite3`). The two per-ticker tables that predate it
(`stock_data`, `stockanalysis_stocks`) are untouched and still written every day.

```text
      NSE_DATA/NSE_data_all_stocks_2007..2024.csv          stockanalysis_scraper (cron 09:00 EAT)
                        │                                              │
        scripts/import_historical.py                 SQLiteBackend.upsert_stockanalysis_stock()
        nse_scraper/historical/*                            │                  │
   read → normalise → lineage → sectors → repairs           │   stockanalysis_stocks (per-ticker, unchanged)
                        │                                    │
                        ▼                                    ▼  _record_observation()
              ┌────────────────────────────────────────────────────────┐
              │  stock_observations   UNIQUE (ticker_symbol, trade_date) │
              │  instruments          canonical ticker, type, sector    │
              │  instrument_aliases   BBK → ABSA, with evidence         │
              │  stock_observation_conflicts   nothing silently dropped │
              │  import_runs          idempotency is auditable          │
              └────────────────────────────────────────────────────────┘
                                          │
                              nse-be reads (mode=ro)  →  analytics / reasoning engine
```

## Tables

### `instruments` — one row per canonical ticker

| Column | Meaning |
|---|---|
| `ticker_symbol` PK | the **current** code (`ABSA`, never `BBK`) |
| `company_name` | most recent name seen in the sources |
| `instrument_type` | `ordinary` · `preference` · `rights` · `index` · `etf` · `reit` |
| `parent_ticker` | `KPLC` for `KPLC-P4`; NULL for an ordinary share |
| `sector` | official NSE label from the sector files; **NULL means no source classifies it** |
| `sector_source` | which sector file supplied the label |
| `first_seen_date` / `last_seen_date` | derived from observations |
| `is_active` | 1 unless explicitly retired |

Rights and preference shares inherit their parent's sector. Indices carry `Indices` and
`instrument_type = 'index'`; exclude them from equity aggregates by type, not by absence.

### `instrument_aliases` — ticker lineage

| `source_ticker` | `canonical_ticker` | `reason` | `evidence` |
|---|---|---|---|
| BBK | ABSA | rebrand | spans hand off 2012-12-31 → 2013-01-02, no overlap |
| CFC | SBIC | rebrand | same seam |
| NIC | NCBA | merger | same seam |
| FIRE | SMER | listing_code_change | same seam |
| C&G | CGEN | listing_code_change | same seam |
| FAHR | LAPR | rebrand | 2022-05-31 → 2023-03-22 |
| CFCI | LBTY | rebrand | same seam; both named "Liberty Kenya Holdings" |
| HFCB | HFCK | listing_code_change | scraper-side: HFCK stale from 2026-07-27, HFCB from the same day, same name; archive uses HFCK |

The scraper resolves through this table on every write, so a code the exchange retires
tomorrow only needs a row here. `CFCI → CIC` was considered and rejected: both trade
throughout 2012, which proves two different companies.

### `stock_observations` — the source of truth

| Column | Archive source | Scraper source |
|---|---|---|
| `ticker_symbol` | resolved `CODE` | resolved `ticker_symbol` |
| `trade_date` | parsed `DATE` (two layouts) | `scraped_at` calendar day |
| `source_ticker` | `CODE` verbatim | `ticker_symbol` verbatim |
| `company_name` | `NAME` | `company_name` |
| `close_price` | `Day Price` | `stock_price` |
| `previous_close` | `Previous` | NULL |
| `day_low` / `day_high` | `Day Low` / `Day High` | NULL |
| `year_low` / `year_high` | `12m Low` / `12m High` | `price_metrics.low52` / `high52` |
| `change_abs` | `Change` — **sign preserved** | `stock_change` |
| `change_pct` | `Change%` as given, never recomputed | NULL |
| `volume` | `Volume` (commas stripped) | `price_metrics.volume` |
| `adjusted_price` | `Adjust` verbatim (semantics undocumented) | NULL |
| `data_source` | `nse_archive:<year>` | `nse_scraper` |
| `source_file` / `source_row` | file + 1-based line | NULL |
| `source_date_raw` | `DATE` verbatim | `scraped_at` |
| `quality_flags` | see below | `["scrape_date_is_observation_date"]` |

`UNIQUE (ticker_symbol, trade_date)` plus `INSERT OR IGNORE` everywhere is what makes
both the historical import and the daily scrape idempotent. A field a source does not
have is NULL. Nothing is derived that the source did not state.

**Quality flags** (JSON array): `date_repaired` (see repairs), `unparseable_volume`,
`unparseable_change`, `unparseable_change_pct`, `year_mismatch` (row's year ≠ file's
year — none remain after repairs), `scrape_date_is_observation_date`.

### `stock_observation_conflicts`

A row whose `(ticker, trade_date)` was already stored *with a different close* lands
here with `conflict_reason` and `kept_observation_id`. After the archive import it holds
exactly the 69 second-occurrence rows of the 2017-03-24 double export.

### `import_runs`

One row per file per invocation: `file_sha256`, counts of read / inserted /
already_present / quarantined / rejected, and a JSON `notes` of repairs, flags and
rejection reasons. The second run of a file must show `rows_already_present == rows_read`.

## Repairs — the four dates the source got wrong

| File | As written | Stored as | Evidence |
|---|---|---|---|
| 2009 | `1/29/2009` (first block) | 2009-01-21 | block sits between 01-20 and 01-22; 01-21 absent |
| 2009 | `4/2/2009` (first block) | 2009-02-04 | between 02-03 and 02-05; 02-04 absent; M/D transposed |
| 2009 | `10/8/2009` (first block) | 2009-08-10 | between 08-07 and 08-11; 08-10 absent; M/D transposed |
| 2017 | `09-May-15` | 2017-05-09 | between 2017-05-08 and 05-10; 05-09 absent; 2015-05-09 was a Saturday |

Every repaired row keeps `source_date_raw` and carries `date_repaired`. The 2017-03-24
double export is *not* repaired — there is no evidence for another date — and is
quarantined instead.

## Operating it

```bash
# one-time (and safe to repeat)
python -m alembic upgrade head                       # inside the image, or with alembic installed
python scripts/import_historical.py --validate --report reports/historical_validation.md

# every day: nothing. The cron job's scraper writes the observation row itself.

# query
sqlite3 data/nse_scraper.sqlite3 \
  "SELECT trade_date, close_price, data_source FROM stock_observations
   WHERE ticker_symbol='KCB' ORDER BY trade_date"
```

## Limitations

- **Trade date for scraped rows is the scrape's calendar day.** The scraper runs at
  09:00 EAT and observes the previous session's close; the rows are flagged so a later
  pass can shift them once an exchange calendar is added.
- Thirteen companies delisted before 2013 appear in no sector file and keep `sector = NULL`.
- `adjusted_price` semantics are undocumented in the source and are stored verbatim.
- The 2017-03-24 second block cannot be attributed and is quarantined, not guessed.
