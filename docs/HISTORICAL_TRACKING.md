# Historical Data Tracking

## Overview

The scraper now preserves historical data instead of replacing it. Each daily scrape run creates new records, allowing you to track changes over time.

## Schema Changes

### `stock_data` Table
- **Primary Key**: Changed from `ticker_symbol` to composite `(ticker_symbol, scraped_at)`
- **New Column**: `scraped_at TIMESTAMPTZ` - timestamp when the data was scraped
- **Behavior**: Each scrape run inserts new records; old records are preserved

### `stockanalysis_stocks` Table
- **Primary Key**: Changed from `ticker_symbol` to composite `(ticker_symbol, scraped_at)`
- **Behavior**: Each scrape run inserts new records; old records are preserved

## Migration Steps

### For Existing Databases

1. **Run the migration script** in Supabase SQL Editor:
   ```sql
   -- Run sql/005_migrate_to_historical_tracking.sql
   ```

2. **Verify migration**:
   ```sql
   -- Check stock_data has composite key
   SELECT constraint_name, constraint_type 
   FROM information_schema.table_constraints 
   WHERE table_name = 'stock_data' AND constraint_type = 'PRIMARY KEY';
   
   -- Check stockanalysis_stocks has composite key
   SELECT constraint_name, constraint_type 
   FROM information_schema.table_constraints 
   WHERE table_name = 'stockanalysis_stocks' AND constraint_type = 'PRIMARY KEY';
   ```

### For New Databases

Simply run the updated schema files:
- `sql/001_create_stock_data.sql` (already updated with composite key)
- `sql/003_create_stockanalysis_stocks.sql` (already updated with composite key)

## Querying Historical Data

### Get Latest Data for a Stock
```sql
-- Latest stock_data
SELECT * FROM stock_data 
WHERE ticker_symbol = 'SCOM'
ORDER BY scraped_at DESC 
LIMIT 1;

-- Latest stockanalysis_stocks
SELECT * FROM stockanalysis_stocks 
WHERE ticker_symbol = 'SCOM'
ORDER BY scraped_at DESC 
LIMIT 1;
```

### Get All Historical Records
```sql
-- All historical records for a stock
SELECT * FROM stock_data 
WHERE ticker_symbol = 'SCOM'
ORDER BY scraped_at DESC;

-- All historical records for stockanalysis
SELECT * FROM stockanalysis_stocks 
WHERE ticker_symbol = 'SCOM'
ORDER BY scraped_at DESC;
```

### Track Price Changes Over Time
```sql
-- Price history for a stock
SELECT scraped_at, stock_price, stock_change
FROM stock_data
WHERE ticker_symbol = 'SCOM'
ORDER BY scraped_at DESC;
```

## Helper Functions

The migration script includes helper functions:

- `get_latest_stock_data(ticker_symbol)` - Returns latest record for a ticker
- `get_latest_stockanalysis_stock(ticker_symbol)` - Returns latest record for a ticker

Usage:
```sql
SELECT * FROM get_latest_stock_data('SCOM');
SELECT * FROM get_latest_stockanalysis_stock('SCOM');
```

## Daily Scrape Behavior

- **Before**: Each scrape replaced existing records (upsert on `ticker_symbol`)
- **After**: Each scrape inserts new records (insert with composite key `ticker_symbol, scraped_at`)

This means:
- ✅ Historical data is preserved
- ✅ You can track changes over time
- ✅ Each day's scrape adds new records
- ✅ No data loss from previous runs

## Backend Changes

The backend code now uses `insert()` instead of `upsert()`:
- `SupabaseBackend.upsert_stock()` → inserts new records
- `SupabaseBackend.upsert_stockanalysis_stock()` → inserts new records

Duplicate prevention is handled by the composite primary key constraint.
