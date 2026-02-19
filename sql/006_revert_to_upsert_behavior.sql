-- Migration: Revert to upsert behavior - one record per ticker_symbol
-- This updates existing records instead of creating duplicates
-- Run this migration in Supabase SQL Editor

-- ============================================
-- 1. Fix stock_data table
-- ============================================

-- Drop composite primary key if it exists
ALTER TABLE stock_data DROP CONSTRAINT IF EXISTS stock_data_pkey;

-- Keep only the latest record per ticker_symbol, delete duplicates
DELETE FROM stock_data
WHERE ctid NOT IN (
    SELECT DISTINCT ON (ticker_symbol) ctid
    FROM stock_data
    ORDER BY ticker_symbol, scraped_at DESC
);

-- Add single-column primary key
ALTER TABLE stock_data 
ADD CONSTRAINT stock_data_pkey PRIMARY KEY (ticker_symbol);

-- Drop composite index if it exists
DROP INDEX IF EXISTS ix_stock_data_ticker_scraped;

-- ============================================
-- 2. Fix stockanalysis_stocks table
-- ============================================

-- Drop composite primary key if it exists
ALTER TABLE stockanalysis_stocks DROP CONSTRAINT IF EXISTS stockanalysis_stocks_pkey;

-- Keep only the latest record per ticker_symbol, delete duplicates
DELETE FROM stockanalysis_stocks
WHERE ctid NOT IN (
    SELECT DISTINCT ON (ticker_symbol) ctid
    FROM stockanalysis_stocks
    ORDER BY ticker_symbol, scraped_at DESC
);

-- Add single-column primary key
ALTER TABLE stockanalysis_stocks 
ADD CONSTRAINT stockanalysis_stocks_pkey PRIMARY KEY (ticker_symbol);

-- Drop composite index if it exists
DROP INDEX IF EXISTS ix_stockanalysis_stocks_ticker_scraped;

-- ============================================
-- 3. Update helper functions (simplified for single record per ticker)
-- ============================================

-- Function to get latest stock_data per ticker (now just returns the one record)
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
    WHERE sd.ticker_symbol = p_ticker_symbol;
END;
$$ LANGUAGE plpgsql;

-- Function to get latest stockanalysis_stocks per ticker (now just returns the one record)
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
    WHERE sas.ticker_symbol = p_ticker_symbol;
END;
$$ LANGUAGE plpgsql;
