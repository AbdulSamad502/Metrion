-- !! OWNER: THESE LIMITS ARE PLACEHOLDERS, NOT THE REAL MARKETPLACE RULES. Verify them against the current Amazon / Flipkart / Meesho seller-central documentation before relying on any
--    result fitted to them. Chat results fitted to these rows are labelled "placeholder limits for testing". Real rules go in through seed_format_constraints.py (VERIFIED, sourced, dated).
-- LOCAL DEVELOPMENT ONLY. Insert-only (idempotent); deletes nothing. NOT a migration, NOT production data.
-- 1) Three TEST_FIXTURE format-constraint rows with PLACEHOLDER limits (NOT verified marketplace rules). Used only when the backend runs
--    with CMO_ACCEPT_TEST_FIXTURE_CONSTRAINTS=true. Version 100000 so they outrank leftover test-suite rows.
-- 2) Platform-level (tenant NULL) CMO config values a developer needs to try the generation + niche flows. These are dev numbers, not the
--    owner's decisions. Trend-report keys are deliberately NOT seeded: the Trends tab must show its honest CONFIG_MISSING state.
INSERT INTO format_constraint (marketplace, category, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type,
    description_max_chars, keywords_max_count, keywords_max_chars, backend_terms_max_bytes, hashtags_supported, count_rule, source_url, verified_at, version, row_kind)
VALUES
 ('AMAZON',   NULL, 200, 3, 5, 200, 'plain', 2000, 10, 40, 250, NULL, 'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture-dev', now(), 100000, 'TEST_FIXTURE'),
 ('FLIPKART', NULL, 120, 3, 5, 200, 'plain', 2000, 10, 40, NULL, NULL, 'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture-dev', now(), 100000, 'TEST_FIXTURE'),
 ('MEESHO',   NULL, 120, 3, 5, 200, 'plain', 2000, 10, 40, NULL, NULL, 'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture-dev', now(), 100000, 'TEST_FIXTURE')
ON CONFLICT DO NOTHING;

INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES
 (NULL, 'format_constraint_max_age_days', '30',  '2026-01-01'),
 (NULL, 'internal_retry_bound',           '1',   '2026-01-01'),
 (NULL, 'hashtag_set_size',               '3',   '2026-01-01'),
 (NULL, 'max_confirmed_niche_terms',      '5',   '2026-01-01'),
 (NULL, 'max_term_chars',                 '60',  '2026-01-01'),
 (NULL, 'catalog_titles_read_cap',        '500', '2026-01-01')
ON CONFLICT DO NOTHING;
