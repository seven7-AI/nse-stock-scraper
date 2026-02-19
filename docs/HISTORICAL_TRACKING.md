# Data Storage Behavior

## Overview

The scraper uses upsert behavior: each daily scrape run **updates** existing records for each ticker_symbol instead of creating duplicates. This ensures you always have the latest data for each stock.

## Schema

### `stock_data` Table
- **Primary Key**: `ticker_symbol` (single column)
- **Column**: `scraped_at TIMESTAMPTZ` - timestamp when the data was last scraped
- **Behavior**: Each scrape run updates existing records or inserts new ones (upsert)

### `stockanalysis_stocks` Table
- **Primary Key**: `ticker_symbol` (single column)
- **Column**: `scraped_at TIMESTAMPTZ` - timestamp when the data was last scraped
- **Behavior**: Each scrape run updates existing records or inserts new ones (upsert)

## Migration Steps

### For Existing Databases with Duplicate Records

1. **Run the cleanup migration script** in Supabase SQL Editor:
   ```sql
   -- Run sql/006_revert_to_upsert_behavior.sql
   ```
   This will:
   - Remove duplicate records (keeps only the latest per ticker_symbol)
   - Restore single-column primary keys
   - Clean up composite indexes

2. **Verify migration**:
   ```sql
   -- Check stock_data has single-column primary key
   SELECT constraint_name, constraint_type 
   FROM information_schema.table_constraints 
   WHERE table_name = 'stock_data' AND constraint_type = 'PRIMARY KEY';
   
   -- Check stockanalysis_stocks has single-column primary key
   SELECT constraint_name, constraint_type 
   FROM information_schema.table_constraints 
   WHERE table_name = 'stockanalysis_stocks' AND constraint_type = 'PRIMARY KEY';
   
   -- Verify no duplicates
   SELECT ticker_symbol, COUNT(*) as count 
   FROM stock_data 
   GROUP BY ticker_symbol 
   HAVING COUNT(*) > 1;
   ```

### For New Databases

Simply run the schema files:
- `sql/001_create_stock_data.sql` (single-column primary key)
- `sql/003_create_stockanalysis_stocks.sql` (single-column primary key)

## Querying Data

### Get Current Data for a Stock
```sql
-- Current stock_data (one record per ticker)
SELECT * FROM stock_data 
WHERE ticker_symbol = 'SCOM';

-- Current stockanalysis_stocks (one record per ticker)
SELECT * FROM stockanalysis_stocks 
WHERE ticker_symbol = 'SCOM';
```

### Get All Stocks
```sql
-- All stocks with latest prices
SELECT * FROM stock_data 
ORDER BY ticker_symbol;

-- All stocks with latest analysis data
SELECT * FROM stockanalysis_stocks 
ORDER BY ticker_symbol;
```

### Check Last Scrape Time
```sql
-- When was each stock last scraped
SELECT ticker_symbol, scraped_at, stock_price
FROM stock_data
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

- **Behavior**: Each scrape **updates** existing records (upsert on `ticker_symbol`)
- **Result**: One record per ticker_symbol with the latest scraped data

This means:
- ✅ Latest data is always available
- ✅ No duplicate records per ticker
- ✅ `scraped_at` timestamp shows when data was last updated
- ✅ Efficient storage (one record per stock)

## Backend Implementation

The backend code uses `upsert()` with `on_conflict="ticker_symbol"`:
- `SupabaseBackend.upsert_stock()` → updates existing or inserts new
- `SupabaseBackend.upsert_stockanalysis_stock()` → updates existing or inserts new

Duplicate prevention is handled by the primary key constraint on `ticker_symbol`.
