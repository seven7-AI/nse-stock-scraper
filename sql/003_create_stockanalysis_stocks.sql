-- StockAnalysis scraper: one record per stock with all tab data (overview, performance, dividends, price, profile)
-- Run in Supabase SQL Editor or via psql

CREATE TABLE IF NOT EXISTS stockanalysis_stocks (
    ticker_symbol VARCHAR(20) PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    rank INTEGER,
    stock_price DOUBLE PRECISION,
    stock_change DOUBLE PRECISION,
    scraped_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    overview_metrics JSONB,
    performance_metrics JSONB,
    dividends_metrics JSONB,
    price_metrics JSONB,
    profile_metrics JSONB,
    price_history JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_scraped_at ON stockanalysis_stocks (scraped_at DESC);
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_rank ON stockanalysis_stocks (rank);

CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_overview_metrics ON stockanalysis_stocks USING GIN (overview_metrics);
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_performance_metrics ON stockanalysis_stocks USING GIN (performance_metrics);
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_dividends_metrics ON stockanalysis_stocks USING GIN (dividends_metrics);
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_price_metrics ON stockanalysis_stocks USING GIN (price_metrics);
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_profile_metrics ON stockanalysis_stocks USING GIN (profile_metrics);

-- Add price_history column if table exists but column doesn't
ALTER TABLE stockanalysis_stocks ADD COLUMN IF NOT EXISTS price_history JSONB DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS ix_stockanalysis_stocks_price_history ON stockanalysis_stocks USING GIN (price_history);

CREATE OR REPLACE FUNCTION set_stockanalysis_stocks_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_stockanalysis_stocks_updated_at ON stockanalysis_stocks;
CREATE TRIGGER tr_stockanalysis_stocks_updated_at
    BEFORE UPDATE ON stockanalysis_stocks
    FOR EACH ROW
    EXECUTE PROCEDURE set_stockanalysis_stocks_updated_at();
