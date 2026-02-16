-- Upsert a single stockanalysis_stocks row (all tab data in one record).
-- Can be called via Supabase RPC or used from SQL.
-- Application may instead use PostgREST upsert on table stockanalysis_stocks with on_conflict=ticker_symbol.

CREATE OR REPLACE FUNCTION upsert_stockanalysis_stock(
    p_ticker_symbol VARCHAR(20),
    p_company_name VARCHAR(255),
    p_rank INTEGER,
    p_stock_price DOUBLE PRECISION,
    p_stock_change DOUBLE PRECISION,
    p_scraped_at TIMESTAMPTZ,
    p_overview_metrics JSONB DEFAULT NULL,
    p_performance_metrics JSONB DEFAULT NULL,
    p_dividends_metrics JSONB DEFAULT NULL,
    p_price_metrics JSONB DEFAULT NULL,
    p_profile_metrics JSONB DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO stockanalysis_stocks (
        ticker_symbol,
        company_name,
        rank,
        stock_price,
        stock_change,
        scraped_at,
        overview_metrics,
        performance_metrics,
        dividends_metrics,
        price_metrics,
        profile_metrics
    )
    VALUES (
        p_ticker_symbol,
        p_company_name,
        p_rank,
        p_stock_price,
        p_stock_change,
        p_scraped_at,
        p_overview_metrics,
        p_performance_metrics,
        p_dividends_metrics,
        p_price_metrics,
        p_profile_metrics
    )
    ON CONFLICT (ticker_symbol) DO UPDATE SET
        company_name = EXCLUDED.company_name,
        rank = EXCLUDED.rank,
        stock_price = EXCLUDED.stock_price,
        stock_change = EXCLUDED.stock_change,
        scraped_at = EXCLUDED.scraped_at,
        updated_at = NOW(),
        overview_metrics = EXCLUDED.overview_metrics,
        performance_metrics = EXCLUDED.performance_metrics,
        dividends_metrics = EXCLUDED.dividends_metrics,
        price_metrics = EXCLUDED.price_metrics,
        profile_metrics = EXCLUDED.profile_metrics;
END;
$$ LANGUAGE plpgsql;
