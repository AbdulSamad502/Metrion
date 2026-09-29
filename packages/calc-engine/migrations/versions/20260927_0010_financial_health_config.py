"""financial_health_config

docs/specs/cfo-agent.md §6.15 (Financial Health Band). Engine-owned configuration (F4:
"coefficients, tolerances ... are configuration, never constants"), mirroring
`anomaly_detection_config`/`severity_config`'s tenant_id-nullable platform-default RLS pattern
(`20260917_0002_reconciliation_config.py`) verbatim — same `_PLATFORM_DEFAULT_POLICY_SQL` policy
body, same `GRANT` to `metrion_app`.

Thresholds are stored as `numeric(5,2)` percentages (e.g. `8.00` for 8%), matching
`anomaly_detection_config.percentile_low/percentile_high`'s own precedent for a percentage-typed
threshold column — never a float, never basis points requiring a rounding convention this
feature would otherwise have to invent. `direction` exists because, unlike `severity_config`'s
single "higher value = more severe" model, financial-health metrics point both ways: a LOW
`CONTRIBUTION_MARGIN_PCT` is the bad direction, but a HIGH `FEE_RATIO_PCT`/`RETURN_RATE_PCT` is.

No numeric value in this table is seeded by this migration — same posture as `fee_reference`
and `anomaly_detection_config` (their own specs: "No numeric value in this table is seeded by
this spec").

Revision ID: 20260927_0010
Revises: 20260926_0009
Create Date: 2026-09-27
"""
from __future__ import annotations

from alembic import op

revision = "20260927_0010"
down_revision = "20260926_0009"
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
        CREATE TABLE financial_health_config (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid,                     -- null = platform default
          metric                 text not null,            -- CONTRIBUTION_MARGIN_PCT | FEE_RATIO_PCT | RETURN_RATE_PCT
          direction              text not null,            -- HIGHER_IS_WORSE | LOWER_IS_WORSE
          at_risk_threshold_pct  numeric(6,2),              -- e.g. 5.00; null = this band not scored for this metric
          watch_threshold_pct    numeric(6,2),
          effective_from         date not null,
          version                int not null,
          unique (tenant_id, metric, effective_from)
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="financial_health_config"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS financial_health_config;")
