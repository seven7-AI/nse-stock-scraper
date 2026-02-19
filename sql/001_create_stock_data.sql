CREATE TABLE IF NOT EXISTS stock_data (
    ticker_symbol VARCHAR(20) PRIMARY KEY,
    stock_name VARCHAR(255) NOT NULL,
    stock_price DOUBLE PRECISION NOT NULL,
    stock_change DOUBLE PRECISION,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    price_history JSONB DEFAULT '[]'::jsonb
);

-- Add price_history column if table exists but column doesn't
ALTER TABLE stock_data ADD COLUMN IF NOT EXISTS price_history JSONB DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS ix_stock_data_created_at ON stock_data (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_stock_data_scraped_at ON stock_data (scraped_at DESC);
CREATE INDEX IF NOT EXISTS ix_stock_data_price_history ON stock_data USING GIN (price_history);
