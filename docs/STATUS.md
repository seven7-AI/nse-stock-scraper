# STATUS — canonical stock observations (2007 archive → daily scraper)

Living document, updated per phase. Newest phase at the bottom.

---

## Phase 1 — CodeGraph & architecture audit  ✅ 2026-09-12

Queried both repositories through CodeGraph before touching anything.

**This repository**

| Finding | Where |
|---|---|
| Runtime storage is SQLite; schema is created by `SQLiteBackend._create_schema()` on every `open()` | `nse_scraper/db/backends.py:293` |
| `sql/sqlite/001_schema.sql` documents that schema and `tests/test_sqlite_backend.py` asserts the two agree | established convention, followed here |
| Alembic exists but targets **Postgres** (`alembic.ini` → `localhost:5432/nse_data`) and is never run against the runtime database | `alembic/env.py`, `alembic.ini` |
| Supabase host stopped resolving 2026-07-26 and never returned; storage migrated to SQLite 2026-09-06 | `docs/MIGRATION_SUPABASE_TO_SQLITE.md` |
| Both live tables key on `ticker_symbol` alone — **one row per ticker**, history compressed into a `price_history` JSON array | `_create_schema` |
| `stockanalysis_scraper` → `StockAnalysisPipeline._upsert_one` → `SQLiteBackend.upsert_stockanalysis_stock()` is the only daily write path that still succeeds (`afx_scraper` cannot reach its host; `stock_data` stale since 2026-08-18) | CodeGraph blast radius |
| `upsert_stockanalysis_stock` has **no test within 3 caller hops** | CodeGraph |
| Per-item record carries `stock_price`, `stock_change`, `scraped_at`, `price_metrics.{volume,low52,high52}` — sufficient for a canonical daily observation | `_build_view_item`, `_upsert_one` |

**Blast radius of what this work edits**

| Symbol | Callers | Tests |
|---|---|---|
| `SQLiteBackend` | 14 (pipelines, db/__init__, migrate_fallback_to_sqlite) | 4 modules |
| `upsert_stockanalysis_stock` | 1 (`StockAnalysisPipeline._upsert_one`) | none — gets its first |
| `_create_schema` | 1 | `test_sqlite_backend`, `test_migration` |

**Baseline before any change:** 89 tests, 78 pass; the 11 failures are all
`ModuleNotFoundError: scrapy / supabase` (deps live in the Docker image, not system
Python). Recorded so regressions are distinguishable. Live DB backed up to
`data/backups/nse_scraper.pre-canonical-20260912_171013.sqlite3` (gitignored).

**nse-be** (`~/Nairobi-stock-Exchange`) reads this database read-only through
`NseScraperSource` (`app/web/services/market_data/sources/nse_scraper.py`). Its
`price_bars`/`instruments` Postgres model exists but the parquet it was fed from is
corrupted (see Phase 2). Nothing there needs to change for this work; a read path for
the new table is added at the end.

---

## Phase 2 — Dataset audit  ✅ 2026-09-12

Source: `~/Nairobi-stock-Exchange/NSE_DATA/`, read in place.

### Yearly price files — SELECTED as the primary historical source

18 files, `NSE_data_all_stocks_2007..2024.csv`, ~270k rows, 103 distinct codes.

| Property | Finding |
|---|---|
| Header variants | 4: case differences, UTF-8 BOM on some, last column `Adjust` / `Adjusted` / `Adjusted Price` |
| Date formats | `M/D/YYYY` (2007–2012), `D-Mon-YY` (2013–2024) |
| Missing marker | `-` — 106,788 `Change` cells, most `Volume`/`Adjust` cells |
| Volumes | thousands separators (`1,234,500`) in ~170k cells |
| **Negative changes** | **91,276 `Change` and 10,594 `Change%` cells are negative** |
| Blank trailing rows | 2014, 2018, 2019 each end with one empty row |
| Index series | `^NASI`, `^N20I`, `^N25I`, `^NBDI`, `^FNK15/25`, `^ZKEQTK/U` carry real daily values |
| Non-ordinary codes | 10 rights issues (`*-R`), 2 preference shares (`KPLC-P4`, `KPLC-P7`) |

> **The existing research parquet (`~/Nairobi-stock-Exchange/research/data/canonical_nse_prices.parquet`) is corrupted and is NOT used.** The notebook that built it cleans numbers with `.str.replace("-", "")`, which turns every negative change positive. Its own quality report shows the symptom — "40,367 change-vs-price mismatches" — without diagnosing the cause. This import parses from the CSVs with sign preserved.

### Ticker lineage — verified by date span, not assumed

| Source | Canonical | Evidence | Decision |
|---|---|---|---|
| BBK | ABSA | BBK ends 2012-12-31, ABSA starts 2013-01-02, no overlap | resolve |
| CFC | SBIC | same seam | resolve |
| NIC | NCBA | same seam | resolve |
| FIRE | SMER | same seam | resolve |
| C&G | CGEN | same seam | resolve |
| FAHR | LAPR | FAHR ends 2022-05-31, LAPR starts 2023-03-22 | resolve |
| **CFCI** | **LBTY** | CFCI ends 2012-12-31, LBTY starts 2013-01-02; **both named "Liberty Kenya Holdings"** | resolve — the notebook missed this |
| CFCI | ~~CIC~~ | both trade throughout 2012 → different companies | **rejected** |

The five seams at exactly 2012→2013 are a file-export artifact (later files carry
current codes retroactively), not real rebrand dates. `source_ticker` preserves the
original code on every row.

### Duplicate observations — four whole days, not row noise

227 duplicate `(code, date)` pairs, 131 with **different** prices, on exactly four dates.
Positional analysis of each extra block inside its file:

| Date | Extra block sits between | Missing weekday | Decision |
|---|---|---|---|
| 2009-01-29 | 01-20 and 01-22 | 01-21 | **repair → 2009-01-21** |
| 2009-04-02 | 02-03 and 02-05 | 02-04 | `4/2`↔`2/4` transposition → **repair → 2009-02-04** |
| 2009-10-08 | 08-07 and 08-11 | 08-10 | `10/8`↔`8/10` transposition → **repair → 2009-08-10** |
| 2017-03-24 | one contiguous 138-row block (69 codes × 2) | none | genuine double export → **keep first, quarantine second** |

Repairs are applied only where the block fills the exact missing trading day; each
repaired row carries `quality_flags: ["date_repaired"]` and `source_date_raw`.

### Sector files — EVALUATED: classification source only

`NSE_data_stock_market_sectors_{2013,2020,2021,2022,2023_2024}.csv` are pure
`SECTOR, CODE, NAME` maps. **No price data**, so there is nothing to merge into the
price history and no overlap risk. They are the official NSE sector membership and are
used solely to classify instruments.

Consistency across the five files is high. Three issues, each handled explicitly:

1. **`2023_2024` line 39 is corrupt.** `Construction and Allied,Energy and Petroleum,`
   is a section header that landed in the CODE column; the six Energy stocks beneath it
   (KEGN, KPLC, KPLC-P4, KPLC-P7, TOTL, UMME) inherited "Construction and Allied".
   Cross-checked against 2022, where they are correctly Energy and Petroleum. Corrected;
   the corrupt row is dropped.
2. `Telecommunication and Technology` was renamed `Telecommunication` in 2022 —
   normalised to the current label.
3. In the 2013 file, index rows have sector = their own code (`^NASI,^NASI,…`) —
   normalised to `Indices`.

Coverage: 69 stock codes classified. Of the 35 price codes without a sector row, 22 are
resolved by lineage / typing (rights, prefs, indices) and **13 are companies delisted
before 2013** (ACCS, BAUM, CITY, CMC, MASH, REA, UTK, PAFR, ICDC, …) which appear in no
sector file. They keep `sector = NULL`. No sector is ever guessed.

### Intentionally excluded

| What | Why |
|---|---|
| `research/data/canonical_nse_prices.parquet` | sign-corrupted (above) |
| `research/data/ticker_master.parquet` | derived from the same notebook; rebuilt from the sector files instead |
| `stock_data` table as a history source | one row per ticker, stale since 2026-08-18, `afx_scraper` cannot reach its host |
| CFCI → CIC alias | overlapping spans prove different companies |
| Recomputing `Change%` from prices | source values stored as given; a mismatch rate is *reported*, not corrected |

---

## Phase 3 — Normalisation design  ✅

New package `nse_scraper/historical/` — pure `csv` + `sqlite3`, no new runtime dependency,
never imported by the scraper itself:

| Module | Does |
|---|---|
| `readers.py` | BOM-safe reading; the four header variants map to one `RawRow`; 1-based `source_row` kept for audit |
| `normalize.py` | two date layouts (memoised regex — `strptime` was 300µs/call); numbers with commas and `%`; `-` is missing **only when it is the whole cell**; sign preserved |
| `lineage.py` | the eight aliases as data with evidence; typing by suffix (`-R`, `-P\d`, `^`) with parent ticker |
| `sectors.py` | the five sector files; the 2023_2024 correction; label rename; 2013 index rows; newest file wins |
| `repairs.py` | the four evidence-based date repairs |
| `importer.py` | idempotent load; `INSERT OR IGNORE` everywhere; conflicts quarantined; `import_runs` audit |
| `validate.py` | 40-check report, committed as `reports/historical_validation.md` |

A fourth date defect surfaced during the first full run via the `year_mismatch` flag:
70 rows in the 2017 file dated `09-May-15` sit between 2017-05-08 and 2017-05-10;
2017-05-09 (Tue) is absent and 2015-05-09 was a Saturday. A year typo — repaired with the
same evidence standard as the 2009 cases. It also explains why FAHR appeared to list on a
Saturday in the initial span analysis.

## Phase 4 — Database  ✅

- `sql/sqlite/002_canonical.sql` (documentation) · `nse_scraper/db/canonical_schema.py`
  (runtime, executed by `_create_schema()` on every open) ·
  `alembic/versions/20260912_0002_canonical_observations.py` (imports the same constant).
  `tests/test_sqlite_backend.py` asserts all three describe identical tables.
- Alembic **had never been a dependency** (`requirements.txt` lacked it; the `alembic/`
  directory was scaffolding). Added `alembic==1.16.1`; `alembic/env.py` now targets the
  SQLite runtime file via `SQLITE_DB_PATH`, `SQL_DATABASE_URL` still overrides.
- Live DB: `alembic stamp 20260214_0001` (that revision describes the original Postgres
  table and had never run; the runtime tables come from `_create_schema`), then
  `upgrade head`. Dry-run on a copy first: stamp → upgrade → downgrade → upgrade, both
  per-ticker tables untouched throughout.
- Purely additive. Nothing dropped, nothing altered.

## Phase 5 — Historical ingestion  ✅

`scripts/import_historical.py` (`--dry-run` leaves the DB byte-identical; `--years`;
`--validate --report`). Live result, 3m52:

| | |
|---|---|
| rows read | 285,889 |
| inserted | 285,819 |
| quarantined | 69 — all 2017-03-24, the double export |
| rejected | 1 — 2019, a row with no close price |
| repaired | 228 (40 + 59 + 59 in 2009, 70 in 2017), each with `source_date_raw` |
| instruments | 96: 73 ordinary · 10 rights · 2 preference · 9 index · 1 ETF · 1 REIT |
| trading days | 4,481, 2007-01-02 → 2024-12-31 |

Second run: **0 inserted, 285,819 already present, 0 newly quarantined**. Conflict rows
are keyed on `(source_file, source_row)` with a unique index so re-detection is a no-op.

## Phase 6 — Sectors  ✅

Every instrument trading in 2024 has an official NSE sector. Eleven are unclassified —
ten companies delisted before 2013 plus `^NBDI` (an index absent from every sector file) —
and stay `NULL`. Rights and preference shares inherit their parent's sector.

## Phase 7 — Scraper integration  ✅

`SQLiteBackend.upsert_stockanalysis_stock()` now calls `_record_observation()` after the
per-ticker upsert succeeds: resolves the code through `instrument_aliases`, creates an
unseen instrument with `sector = NULL`, and `INSERT OR IGNORE`s one row for the scrape's
calendar day. A failure there writes its own `stock_observations_fallback-*.jsonl` and
**does not** change the return value or the quality gate's `db_upsert_ok` accounting.

Verified with the real job (`docker compose run --rm scraper-job`, live site, live DB):
`QUALITY stockanalysis_scraper OK db_ok=63` → **63 observation rows**, KCB's timeline
reads `2024-12-31 (archive) → 2026-09-12 (scraper)`.

**Deployment note:** the job runs the image's copy of `nse_scraper/`. The first run after
the change wrote 0 rows because the image predated it. `docker compose build` is required
after pulling this change — added to the README.

## Phase 8 — Idempotency  ✅

Three mechanisms, all schema-level: `UNIQUE (ticker_symbol, trade_date)` +
`INSERT OR IGNORE`; `UNIQUE (source_file, source_row)` on conflicts; `file_sha256` on
`import_runs`. Proven on production: a second same-day scraper run left the count at 63
with 0 duplicate keys; a second archive import inserted 0. Tests cover import-twice,
scrape-twice, and archive-then-scrape-then-archive.

## Phase 9 — Validation  ✅ PASS (27 checks, 0 failures, 13 informational)

Full report: `reports/historical_validation.md`. Headlines:

- `close − previous == change` for **100.00% of 179,040 rows** where all three exist.
  The previous notebook reported 40,367 mismatches on the same data — that was its own
  sign-stripping bug, not the data.
- 91,262 negative `change_abs` preserved.
- All eight aliases collapse cleanly; ABSA spans 2007-01-02 → 2026-09-12 in one query.
- Seven spot checks (KCB 2007-01-02, SCOM IPO day, the BBK/ABSA seam, KPLC-P7, ^NASI,
  KCB 2024-12-31) match the CSV line byte-for-byte on code, date, close and volume.
- 57 of 64 scraped tickers join the archive. Scraper-only: KPC, FMLY, AMAC, SKL, TRFC,
  ALP (2025 listings). **HFCB is HF Group's new code at the scraper's source**: the
  scraper's HFCK row went stale on 2026-07-27 and HFCB appeared the same day, both named
  "HFCB Group Plc". Aliased HFCB → HFCK (the NSE code the archive uses), so HFCK now
  spans 2007-01-02 → 2026-09-12. Today's one HFCB row was migrated. 58 of 64 join.
- Large moves since the archive ended (CGEN 12.5×, SMER 7.5×, UCHM 7.2×) are the same
  companies by name — thinly traded small caps, informational only.

## Phase 10 — Cleanup  ✅

No temporary scripts remain. Test suite in the image: **181 pass** (148 baseline + 33),
2 skipped only because the archive is not mounted inside the container.

### Remaining limitations

- **Scraper rows carry the scrape's calendar day as `trade_date`** (09:00 EAT observes
  the previous session's close). Flagged `scrape_date_is_observation_date`; shifting
  them needs an exchange calendar.
- **`volume` / `year_low` / `year_high` on scraper rows are sparse.** The scraper only
  enriches ~16 tickers' `price_metrics` per run (rotating window, ARCHITECTURE.md §8.2).
  Rows carry NULL rather than a stale last-known value.
- The 2017-03-24 second block is quarantined, not attributed.
- `adjusted_price` semantics are undocumented in the source; stored verbatim.
- `afx_scraper` still scrapes 0 items (host unreachable); `stock_data` remains stale.
