-- Example queries for stockanalysis_stocks (tab-like retrieval).
-- Run in Supabase SQL Editor or use via PostgREST.

-- Get all stocks with overview tab data
SELECT ticker_symbol, company_name, stock_price, overview_metrics
FROM stockanalysis_stocks
ORDER BY rank;

-- Get specific stock with all tabs
SELECT ticker_symbol, company_name,
       overview_metrics, performance_metrics, dividends_metrics,
       price_metrics, profile_metrics
FROM stockanalysis_stocks
WHERE ticker_symbol = 'SCOM';

-- Query by metric value (e.g., revenue > 100B)
SELECT ticker_symbol, company_name,
       overview_metrics->>'revenue' AS revenue
FROM stockanalysis_stocks
WHERE (overview_metrics->>'revenue')::bigint > 100000000000;

-- Get latest scraped data
SELECT ticker_symbol, company_name, scraped_at
FROM stockanalysis_stocks
ORDER BY scraped_at DESC
LIMIT 10;
