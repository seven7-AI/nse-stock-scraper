CREATE TABLE IF NOT EXISTS stock_data (
    ticker_symbol VARCHAR(20) NOT NULL,
    stock_name VARCHAR(255) NOT NULL,
    stock_price DOUBLE PRECISION NOT NULL,
    stock_change DOUBLE PRECISION,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT stock_data_pkey PRIMARY KEY (ticker_symbol, scraped_at)
);

CREATE INDEX IF NOT EXISTS ix_stock_data_created_at ON stock_data (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_stock_data_scraped_at ON stock_data (scraped_at DESC);
CREATE INDEX IF NOT EXISTS ix_stock_data_ticker_scraped ON stock_data (ticker_symbol, scraped_at DESC);
