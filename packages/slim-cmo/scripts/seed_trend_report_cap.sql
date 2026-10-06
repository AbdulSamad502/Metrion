-- Reviewable seed for the launch cap on CMO trend reports: 5 per tenant per MONTH (tenant-timezone calendar month),
-- platform default (tenant_id NULL), on the CMO trend meter only. NOT run by any migration: a commercial limit is data
-- an operator applies deliberately. The shared `research.market_trends` meter is intentionally left unseeded.
--
-- Review, then run as the table owner:
--   docker exec -i metrion-postgres-1 psql -U metrion -d metrion < packages/slim-cmo/scripts/seed_trend_report_cap.sql
-- Re-running is harmless (it inserts only if no platform-default monthly cap row exists for this meter). To change the
-- cap later, insert a new row with a later effective_from and a higher version rather than editing this one.

\echo '-- existing platform-default caps for the CMO trend meter (expect none the first time)'
SELECT id, scope, period_unit, cap_value, effective_from, version
  FROM entitlement_cap_config WHERE tenant_id IS NULL AND agent_code = 'CMO' AND meter_code = 'cmo.market_trends';

BEGIN;
INSERT INTO entitlement_cap_config (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
SELECT gen_random_uuid(), NULL, 'CMO', 'cmo.market_trends', 'TENANT', 'MONTH', 5, CURRENT_DATE, 1
 WHERE NOT EXISTS (
   SELECT 1 FROM entitlement_cap_config
    WHERE tenant_id IS NULL AND agent_code = 'CMO' AND meter_code = 'cmo.market_trends' AND scope = 'TENANT' AND period_unit = 'MONTH');

\echo '-- after (expect exactly one row, cap_value 5):'
SELECT agent_code, meter_code, scope, period_unit, cap_value, effective_from, version
  FROM entitlement_cap_config WHERE tenant_id IS NULL AND agent_code = 'CMO' AND meter_code = 'cmo.market_trends';
COMMIT;
