"""anomaly_detection_config

docs/specs/anomaly-detection.md §5.3 (Brain 2 — statistical anomaly detection).
Engine-owned configuration (F4: "coefficients, tolerances ... are configuration, never
constants"), mirroring `reconciliation_tolerance_config`/`severity_config`'s tenant_id-nullable
platform-default RLS pattern (`20260917_0002_reconciliation_config.py`) verbatim — same
`_PLATFORM_DEFAULT_POLICY_SQL` policy body, same `GRANT` to `metrion_app`.

No numeric value in this table is seeded by this migration — same posture as `fee_reference`
and `reconciliation_tolerance_config` (spec §5.3: "No numeric value in this table is seeded
by this spec").

Revision ID: 20260925_0005
Revises: 20260925_0004
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

revision = "20260925_0005"
down_revision = "20260925_0004"
branch_labels = None
depends_on = None

_PLATFORM_DEFAULT_POLICY_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING (
    tenant_id IS NULL
    OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
  )
  WITH CHECK (
    tenant_id IS NULL
    OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE anomaly_detection_config (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid,                     -- null = platform default
          metric                 text not null,            -- MARGIN_PCT | FEE_RATIO_PCT | SETTLEMENT_LAG_DAYS | RETURN_RATE_PCT
          method                 text not null,            -- Z_SCORE | PERCENTILE_THRESHOLD | PERIOD_OVER_PERIOD_DELTA
          min_series_length      int not null,             -- must be >= the engine floor for this method (§6.2); may raise, never lower
          z_score_threshold      numeric(6,3),              -- e.g. 2.500, applies to Z_SCORE only
          percentile_low         numeric(5,2),              -- e.g. 10.00, applies to PERCENTILE_THRESHOLD only
          percentile_high        numeric(5,2),              -- e.g. 90.00, applies to PERCENTILE_THRESHOLD only
          delta_severity_bands   jsonb,                     -- {"high": "3.0", "medium": "2.0", "low": "1.0"} — multiples of
                                                             -- baseline-delta stdev; applies to PERIOD_OVER_PERIOD_DELTA only;
                                                             -- values are strings to preserve Fraction/Decimal precision
          effective_from         date not null,
          version                int not null,
          unique (tenant_id, metric, method, effective_from)
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="anomaly_detection_config"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS anomaly_detection_config;")
