-- Reviewable DEV seed for the Slim CMO market-trends configuration (docs/specs/slim-cmo-agent.md section 6.8.5, "Starting values").
-- Platform default (tenant_id NULL). NOT run by any migration: these are owner-set data, never code defaults.
-- Values marked OWNER-APPROVED 2026-10-13 came from the owner's reply "yes, seed news config" to the recommended values; the first group is the spec's recorded starting values.
-- Re-running is harmless: a key is inserted only when no platform-default row exists for it. To change a value later, insert a row with a later effective_from.
--   docker exec -i metrion-postgres-1 psql -U metrion -d metrion < packages/slim-cmo/scripts/seed_trend_config.sql

BEGIN;
INSERT INTO cmo_platform_config (id, tenant_id, key, value, effective_from)
SELECT gen_random_uuid(), NULL, v.key, v.value::jsonb, DATE '2026-01-01'
  FROM (VALUES
    -- spec starting values
    ('max_queries_per_report',          '10'),
    ('section_query_budgets',           '{"NICHE": 2, "MARKET_NEWS": 2, "REPORTED_TACTICS": 2, "NEW_PRODUCTS_BUZZ": 2, "ADJACENT": 2}'),
    ('section_priority',                '["NICHE", "MARKET_NEWS", "REPORTED_TACTICS", "NEW_PRODUCTS_BUZZ", "ADJACENT"]'),
    ('max_results_per_query',           '5'),
    ('news_window_days',                '30'),
    ('provider_cache_ttl_hours',        '24'),
    ('provider_call_timeout_seconds',   '15'),
    ('provider_daily_search_ceiling',   '20'),
    -- previously unset, owner-approved 2026-10-13
    ('max_sources_per_report',          '12'),
    ('max_findings_per_section',        '4'),
    ('fresh_window_days',               '7'),
    ('recent_window_days',              '30'),
    ('moderate_min_independent_sources','2'),
    ('strong_min_independent_sources',  '3')
  ) AS v(key, value)
 WHERE NOT EXISTS (SELECT 1 FROM cmo_platform_config c WHERE c.tenant_id IS NULL AND c.key = v.key);

SELECT key, value FROM cmo_platform_config WHERE tenant_id IS NULL AND key NOT LIKE 'test%' ORDER BY key;
COMMIT;
