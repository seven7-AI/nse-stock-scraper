CREATE OR REPLACE FUNCTION upsert_stock_data(
    p_ticker_symbol VARCHAR,
    p_stock_name VARCHAR,
    p_stock_price DOUBLE PRECISION,
    p_stock_change DOUBLE PRECISION,
    p_created_at TIMESTAMPTZ DEFAULT NOW()
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO stock_data (
        ticker_symbol,
        stock_name,
        stock_price,
        stock_change,
        created_at
    )
    VALUES (
        p_ticker_symbol,
        p_stock_name,
        p_stock_price,
        p_stock_change,
        p_created_at
    )
    ON CONFLICT (ticker_symbol) DO UPDATE
    SET
        stock_name = EXCLUDED.stock_name,
        stock_price = EXCLUDED.stock_price,
        stock_change = EXCLUDED.stock_change,
        created_at = EXCLUDED.created_at;
END;
$$ LANGUAGE plpgsql;
