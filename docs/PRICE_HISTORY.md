# Price History Tracking

## Overview

The scraper uses a **hybrid approach** that combines the best of both worlds:
- **One record per ticker_symbol** - Easy to query latest data
- **Historical data preserved** - Stored in `price_history` JSONB column

## How It Works

### Schema
- **Primary Key**: `ticker_symbol` (single column)
- **Main Columns**: `stock_price`, `stock_change`, `scraped_at` - Always contain **latest** data
- **History Column**: `price_history` JSONB - Array of historical price snapshots

### Data Structure

Each record has:
```json
{
  "ticker_symbol": "ABSA",
  "stock_price": 29.45,           // Latest price
  "stock_change": 0.4,            // Latest change
  "scraped_at": "2026-02-19T17:14:04Z",  // Latest scrape time
  "price_history": [              // Historical snapshots
    {
      "scraped_at": "2026-02-19T06:00:14Z",
      "stock_price": 29.85,
      "stock_change": 0
    },
    {
      "scraped_at": "2026-02-19T17:11:34Z",
      "stock_price": 29.45,
      "stock_change": 0.4
    },
    {
      "scraped_at": "2026-02-19T17:14:04Z",
      "stock_price": 29.45,
      "stock_change": 0.4
    }
  ]
}
```

## Migration

Run this migration to add `price_history` column to existing tables:

```sql
-- Run sql/007_add_price_history_column.sql
```

This will:
- Add `price_history` JSONB column to both tables
- Create GIN indexes for efficient JSONB queries
- Populate initial history from existing `scraped_at`, `stock_price`, `stock_change`

## Querying Data

### Get Latest Data (Simple)
```sql
-- Get latest price for a stock
SELECT ticker_symbol, stock_price, stock_change, scraped_at
FROM stock_data
WHERE ticker_symbol = 'ABSA';
```

### Get Price History
```sql
-- Get full price history for a stock
SELECT ticker_symbol, price_history
FROM stock_data
WHERE ticker_symbol = 'ABSA';

-- Or use helper function
SELECT get_price_history('ABSA', 'stock_data');
```

### Query Historical Entries
```sql
-- Get all historical prices as rows
SELECT 
    ticker_symbol,
    jsonb_array_elements(price_history)::jsonb->>'scraped_at' as history_scraped_at,
    (jsonb_array_elements(price_history)::jsonb->>'stock_price')::double precision as history_price,
    (jsonb_array_elements(price_history)::jsonb->>'stock_change')::double precision as history_change
FROM stock_data
WHERE ticker_symbol = 'ABSA'
ORDER BY history_scraped_at DESC;
```

### Track Price Changes
```sql
-- Find when price changed
SELECT 
    ticker_symbol,
    entry->>'scraped_at' as changed_at,
    (entry->>'stock_price')::double precision as price,
    (entry->>'stock_change')::double precision as change
FROM stock_data,
LATERAL jsonb_array_elements(price_history) as entry
WHERE ticker_symbol = 'ABSA'
ORDER BY changed_at DESC;
```

## Backend Behavior

When a scrape runs:
1. **Reads existing record** (if exists)
2. **Appends new entry** to `price_history` array (only if price/change changed)
3. **Updates main columns** with latest data
4. **Upserts record** (updates existing or inserts new)

This ensures:
- ✅ Latest data always in main columns (easy access)
- ✅ Historical data preserved in JSONB
- ✅ No duplicate entries (only adds when price changes)
- ✅ Efficient storage (one record per stock)

## Benefits

- **Easy Latest Queries**: `SELECT * FROM stock_data WHERE ticker_symbol = 'ABSA'`
- **Historical Tracking**: Access `price_history` JSONB array
- **Efficient Storage**: One record per stock, not multiple rows
- **Flexible Queries**: Use JSONB operators for complex history queries
- **Indexed**: GIN index on `price_history` for fast JSONB queries
