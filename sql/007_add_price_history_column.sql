-- Migration: Add price_history JSONB column to preserve historical data
-- Run this migration in Supabase SQL Editor

-- ============================================
-- 1. Add price_history to stock_data
-- ============================================

-- Add column if it doesn't exist
ALTER TABLE stock_data 
ADD COLUMN IF NOT EXISTS price_history JSONB DEFAULT '[]'::jsonb;

-- Create GIN index for efficient JSONB queries
CREATE INDEX IF NOT EXISTS ix_stock_data_price_history ON stock_data USING GIN (price_history);

-- Populate price_history with existing data (if any records exist)
-- This creates initial history entry from current scraped_at, stock_price, stock_change
UPDATE stock_data
SET price_history = jsonb_build_array(
    jsonb_build_object(
        'scraped_at', scraped_at,
        'stock_price', stock_price,
        'stock_change', stock_change
    )
)
WHERE price_history IS NULL OR price_history = '[]'::jsonb;

-- ============================================
-- 2. Add price_history to stockanalysis_stocks
-- ============================================

-- Add column if it doesn't exist
ALTER TABLE stockanalysis_stocks 
ADD COLUMN IF NOT EXISTS price_history JSONB DEFAULT '[]'::jsonb;

-- Create GIN index for efficient JSONB queries
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_price_history ON stockanalysis_stocks USING GIN (price_history);

-- Populate price_history with existing data (if any records exist)
UPDATE stockanalysis_stocks
SET price_history = jsonb_build_array(
    jsonb_build_object(
        'scraped_at', scraped_at,
        'stock_price', stock_price,
        'stock_change', stock_change
    )
)
WHERE price_history IS NULL OR price_history = '[]'::jsonb;

-- ============================================
-- 3. Helper function to query price history
-- ============================================

CREATE OR REPLACE FUNCTION get_price_history(p_ticker_symbol VARCHAR(20), p_table_name VARCHAR(50) DEFAULT 'stock_data')
RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    IF p_table_name = 'stock_data' THEN
        SELECT price_history INTO result
        FROM stock_data
        WHERE ticker_symbol = p_ticker_symbol;
    ELSIF p_table_name = 'stockanalysis_stocks' THEN
        SELECT price_history INTO result
        FROM stockanalysis_stocks
        WHERE ticker_symbol = p_ticker_symbol;
    END IF;
    
    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
