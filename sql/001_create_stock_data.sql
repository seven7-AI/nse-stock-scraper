CREATE TABLE IF NOT EXISTS stock_data (
    ticker_symbol VARCHAR(20) PRIMARY KEY,
    stock_name VARCHAR(255) NOT NULL,
    stock_price DOUBLE PRECISION NOT NULL,
    stock_change DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_stock_data_created_at ON stock_data (created_at DESC);
