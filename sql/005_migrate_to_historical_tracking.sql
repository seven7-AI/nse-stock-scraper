-- Migration: Convert tables to support historical tracking
-- This allows multiple records per ticker_symbol, one per scrape run
-- Run this migration in Supabase SQL Editor

-- ============================================
-- 1. Migrate stock_data table
-- ============================================

-- Add scraped_at column if it doesn't exist
ALTER TABLE stock_data 
ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMPTZ;

-- Set scraped_at to created_at for any NULL values
UPDATE stock_data 
SET scraped_at = created_at 
WHERE scraped_at IS NULL;

-- Make scraped_at NOT NULL now that all rows have values
ALTER TABLE stock_data 
ALTER COLUMN scraped_at SET NOT NULL;

-- Drop existing primary key constraint
ALTER TABLE stock_data DROP CONSTRAINT IF EXISTS stock_data_pkey;

-- Ensure unique scraped_at per ticker_symbol before adding composite key
-- Use CTE approach since window functions aren't allowed directly in UPDATE
WITH numbered_records AS (
    SELECT 
        ctid,
        ticker_symbol,
        created_at,
        scraped_at,
        ROW_NUMBER() OVER (PARTITION BY ticker_symbol ORDER BY created_at) - 1 AS row_num
    FROM stock_data
)
UPDATE stock_data sd
SET scraped_at = nr.scraped_at + (nr.row_num * INTERVAL '1 microsecond')
FROM numbered_records nr
WHERE sd.ctid = nr.ctid AND nr.row_num > 0;

-- Add new composite primary key
ALTER TABLE stock_data 
ADD CONSTRAINT stock_data_pkey PRIMARY KEY (ticker_symbol, scraped_at);

-- ============================================
-- 2. Migrate stockanalysis_stocks table
-- ============================================

-- Drop existing primary key constraint
ALTER TABLE stockanalysis_stocks DROP CONSTRAINT IF EXISTS stockanalysis_stocks_pkey;

-- Add new composite primary key
ALTER TABLE stockanalysis_stocks 
ADD CONSTRAINT stockanalysis_stocks_pkey PRIMARY KEY (ticker_symbol, scraped_at);

-- Update existing records to ensure unique scraped_at per ticker
-- This handles edge case where multiple records have same scraped_at
DO $$
DECLARE
    rec RECORD;
    counter INTEGER;
BEGIN
    FOR rec IN 
        SELECT ticker_symbol, scraped_at, COUNT(*) as cnt
        FROM stockanalysis_stocks
        GROUP BY ticker_symbol, scraped_at
        HAVING COUNT(*) > 1
    LOOP
        counter := 0;
        FOR rec IN 
            SELECT ctid, ticker_symbol, scraped_at
            FROM stockanalysis_stocks
            WHERE ticker_symbol = rec.ticker_symbol 
              AND scraped_at = rec.scraped_at
            ORDER BY created_at
        LOOP
            UPDATE stockanalysis_stocks
            SET scraped_at = rec.scraped_at + (counter * INTERVAL '1 microsecond')
            WHERE ctid = rec.ctid;
            counter := counter + 1;
        END LOOP;
    END LOOP;
END $$;

-- ============================================
-- 3. Update indexes for better query performance
-- ============================================

-- stock_data: Keep created_at index, add scraped_at index
CREATE INDEX IF NOT EXISTS ix_stock_data_scraped_at ON stock_data (scraped_at DESC);
CREATE INDEX IF NOT EXISTS ix_stock_data_ticker_scraped ON stock_data (ticker_symbol, scraped_at DESC);

-- stockanalysis_stocks: scraped_at index already exists, add composite index
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_ticker_scraped ON stockanalysis_stocks (ticker_symbol, scraped_at DESC);

-- ============================================
-- 4. Create helper functions for getting latest data
-- ============================================

-- Function to get latest stock_data per ticker
CREATE OR REPLACE FUNCTION get_latest_stock_data(p_ticker_symbol VARCHAR(20))
RETURNS TABLE (
    ticker_symbol VARCHAR(20),
    stock_name VARCHAR(255),
    stock_price DOUBLE PRECISION,
    stock_change DOUBLE PRECISION,
    scraped_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT sd.ticker_symbol, sd.stock_name, sd.stock_price, sd.stock_change, sd.scraped_at, sd.created_at
    FROM stock_data sd
    WHERE sd.ticker_symbol = p_ticker_symbol
    ORDER BY sd.scraped_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to get latest stockanalysis_stocks per ticker
CREATE OR REPLACE FUNCTION get_latest_stockanalysis_stock(p_ticker_symbol VARCHAR(20))
RETURNS TABLE (
    ticker_symbol VARCHAR(20),
    company_name VARCHAR(255),
    rank INTEGER,
    stock_price DOUBLE PRECISION,
    stock_change DOUBLE PRECISION,
    scraped_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    overview_metrics JSONB,
    performance_metrics JSONB,
    dividends_metrics JSONB,
    price_metrics JSONB,
    profile_metrics JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT sas.ticker_symbol, sas.company_name, sas.rank, sas.stock_price, sas.stock_change,
           sas.scraped_at, sas.created_at, sas.updated_at,
           sas.overview_metrics, sas.performance_metrics, sas.dividends_metrics,
           sas.price_metrics, sas.profile_metrics
    FROM stockanalysis_stocks sas
    WHERE sas.ticker_symbol = p_ticker_symbol
    ORDER BY sas.scraped_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;
