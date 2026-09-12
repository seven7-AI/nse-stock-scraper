# Historical import validation

**Overall: FAIL**

## Summary

| Metric | Value |
|---|---:|
| observations | 287789 |
| archive_observations | 285819 |
| scraper_observations | 1970 |
| instruments | 102 |
| instruments_by_type | {'etf': 1, 'index': 9, 'ordinary': 79, 'preference': 2, 'reit': 1, 'rights': 10} |
| aliases | 8 |
| distinct_trade_dates | 4520 |
| min_trade_date | 2007-01-02 |
| max_trade_date | 2026-09-12 |
| conflicts | 69 |
| import_runs | 18 |

## Checks

| | Check | Detail |
|---|---|---|
| ✅ | no duplicate (ticker, trade_date) | 0 duplicate keys |
| ✅ | every observation has an instrument | 0 orphans |
| ✅ | conflicts are exactly the 2017-03-24 double export | 69 rows on ['2017-03-24'] |
| ✅ | date repairs match the audit | 228 repaired rows (expected 228) |
| ✅ | every repaired row keeps its original date string | 228/228 |
| ✅ | rejected rows match the audit | 1 rejected in the latest run per file (expected 1) |
| ✅ | archive starts 2007-01-02 | 2007-01-02 |
| ✅ | all aliases registered | 8 rows |
| ✅ | alias BBK -> ABSA collapses cleanly | 1500 rows kept source_ticker=BBK, 0 stored under the old code; ABSA spans 2007-01-02..2026-09-12 |
| ✅ | alias CFC -> SBIC collapses cleanly | 1489 rows kept source_ticker=CFC, 0 stored under the old code; SBIC spans 2007-01-02..2026-09-12 |
| ✅ | alias NIC -> NCBA collapses cleanly | 1500 rows kept source_ticker=NIC, 0 stored under the old code; NCBA spans 2007-01-02..2026-09-12 |
| ✅ | alias FIRE -> SMER collapses cleanly | 1497 rows kept source_ticker=FIRE, 0 stored under the old code; SMER spans 2007-01-02..2026-09-12 |
| ✅ | alias C&G -> CGEN collapses cleanly | 1284 rows kept source_ticker=C&G, 0 stored under the old code; CGEN spans 2007-01-02..2026-09-12 |
| ✅ | alias FAHR -> LAPR collapses cleanly | 1619 rows kept source_ticker=FAHR, 0 stored under the old code; LAPR spans 2015-11-27..2026-09-12 |
| ✅ | alias CFCI -> LBTY collapses cleanly | 251 rows kept source_ticker=CFCI, 0 stored under the old code; LBTY spans 2012-01-03..2026-09-12 |
| ✅ | alias HFCB -> HFCK collapses cleanly | 34 rows kept source_ticker=HFCB, 0 stored under the old code; HFCK spans 2007-01-02..2026-09-12 |
| ✅ | negative changes preserved (sign bug not reproduced) | 92102 negative, 88766 positive change_abs |
| ✅ | close - previous == change where all three present | 100.00% of 179040 rows consistent within 0.01 (0 inconsistent — reported, not corrected) |
| ✅ | no non-positive close prices | 0 |
| ℹ️ | missing values are NULL, not invented | archive rows without volume: 61803; without change: 106762; without name: 48 |
| ℹ️ | quality flags | {"backfilled_from_price_history": 1907, "date_repaired": 228, "scrape_date_is_observation_date": 1970} |
| ❌ | every instrument trading in 2024 has a sector | unclassified-but-active: ['ALP', 'AMAC', 'FMLY', 'KPC', 'SKL', 'TRFC'] |
| ℹ️ | unclassified instruments (delisted pre-2013, never guessed) | 17: ['ACCS', 'ALP', 'AMAC', 'BAUM', 'BERG', 'CITY', 'CMC', 'FMLY', 'ICDC', 'KPC', 'MASH', 'PAFR', 'REA', 'SKL', 'TRFC', 'UTK', '^NBDI'] |
| ℹ️ | ordinary shares by sector | NULL=16; Commercial and Services=13; Banking=12; Manufacturing and Allied=8; Insurance=6; Agricultural=6; Investment=5; Energy and Petroleum=5; Construction and Allied=5; Telecommunication=1; Investment Services=1; Automobiles and Accessories=1 |
| ✅ | KCB has an unbroken 2007 -> latest series | 4517 rows, 2007-01-02..2026-09-12, 19 distinct years |
| ℹ️ | instruments by first-listing year | None:6, 2007:55, 2008:5, 2009:4, 2010:3, 2011:2, 2012:5, 2013:8, 2014:3, 2015:2, 2016:2, 2017:1, 2018:3, 2022:1, 2023:1, 2024:1 |
| ℹ️ | ordinary shares no longer present in 2024 (delisted) | 11: ['ACCS', 'BAUM', 'BERG', 'CITY', 'CMC', 'ICDC', 'MASH', 'PAFR', 'REA', 'UTK', 'KENO'] |
| ℹ️ | longest histories | KCB 4517 rows 2007-01-02..2026-09-12; ABSA 4516 rows 2007-01-02..2026-09-12; HFCK 4516 rows 2007-01-02..2026-09-12; KQ 4516 rows 2007-01-02..2026-09-12; SASN 4516 rows 2007-01-02..2026-09-12 |
| ℹ️ | tickers whose company name changed over time | CABL (4 names); TOTL (4 names); ABSA (3 names); BAMB (3 names); BAT (3 names); CARB (3 names); CGEN (3 names); CIC (3 names); COOP (3 names); DTK (3 names); EABL (3 names); EGAD (3 names) |
| ✅ | spot KCB 2007-01-02 | csv[NSE_data_all_stocks_2007.csv:17] code=KCB date='1/2/2007' close=243 vol='225,900'  ->  db source_ticker=KCB close=243.0 volume=225900 change=5.0 |
| ✅ | spot SCOM 2008-06-09 | csv[NSE_data_all_stocks_2008.csv:4637] code=SCOM date='6/9/2008' close=7.35 vol='416,380,000'  ->  db source_ticker=SCOM close=7.35 volume=416380000 change=2.35 |
| ✅ | spot ABSA 2012-12-31 | csv[NSE_data_all_stocks_2012.csv:16033] code=BBK date='12/31/2012' close=15.75 vol='1,340,000'  ->  db source_ticker=BBK close=15.75 volume=1340000 change=0.05 |
| ✅ | spot ABSA 2013-01-02 | csv[NSE_data_all_stocks_2013.csv:9] code=ABSA date='2-Jan-13' close=15.7 vol='78,200'  ->  db source_ticker=ABSA close=15.7 volume=78200 change=-0.05 |
| ✅ | spot KPLC-P7 2015-06-30 | csv[NSE_data_all_stocks_2015.csv:8033] code=KPLC-P7 date='30-Jun-15' close=5.5 vol='-'  ->  db source_ticker=KPLC-P7 close=5.5 volume=None change=None |
| ✅ | spot ^NASI 2024-12-31 | csv[NSE_data_all_stocks_2024.csv:18117] code=^NASI date='31-Dec-24' close=123.48 vol='-'  ->  db source_ticker=^NASI close=123.48 volume=None change=0.36 |
| ✅ | spot KCB 2024-12-31 | csv[NSE_data_all_stocks_2024.csv:18062] code=KCB date='31-Dec-24' close=41.6 vol='136,800.00'  ->  db source_ticker=KCB close=41.6 volume=136800 change=1.6 |
| ℹ️ | scraper tickers found in the archive | 58 of 64 scraped tickers have archive history; scraper-only (new listings or scraper-side codes): ['KPC', 'FMLY', 'AMAC', 'SKL', 'TRFC', 'ALP'] |
| ℹ️ | company-name drift between sources for the same ticker (eyeball; ticker is the identity) | IMH: scraper 'I&M Group PLC' vs archive 'I & M Holdings Plc'; HFCK: scraper 'HFCB Group Plc' vs archive 'HF Group Ltd'; FTGH: scraper 'FTG Holdings Ltd' vs archive 'Flame Tree Group Holdings Ltd'; HFCB: scraper 'HFCB Group Plc' vs archive 'HF Group Ltd' |
| ℹ️ | large moves between archive end and today (same company; informational) | CGEN 12.5x (22.75 -> 284.0); SMER 7.5x (2.43 -> 18.2); UCHM 7.2x (0.17 -> 1.23) |
| ℹ️ | scraper lists one company under two codes (scraper-side duplicate, not aliased) | HFCB Group Plc -> HFCK,HFCB |
| ℹ️ | scraper observations coexist in the same table | 1970 rows with data_source = nse_scraper |
