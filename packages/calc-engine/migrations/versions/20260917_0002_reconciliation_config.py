"""reconciliation_tolerance_config, severity_config

deterministic-engine.md §5.12.1 (new, Category C amendment), §5.14.1. Both are engine-owned
configuration (F4: "coefficients, tolerances ... are configuration, never constants"),
mirroring discount_bearer_config's tenant_id-nullable platform-default pattern (§5.3).

Revision ID: 20260917_0002
Revises: 20260917_0001
Create Date: 2026-09-17
"""
from __future__ import annotations

from alembic import op

revision = "20260917_0002"
down_revision = "20260917_0001"
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
        CREATE TABLE reconciliation_tolerance_config (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid,                     -- null = platform default
          marketplace        text not null,
          component_code     text not null,            -- or '*' for a marketplace-wide default
          tolerance_paise    bigint not null,
          tolerance_bps      int not null,
          settlement_lag_days int not null,
          grace_period_days  int not null,
          effective_from     date not null,
          version            int not null,
          unique (tenant_id, marketplace, component_code, effective_from)
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="reconciliation_tolerance_config"))

    op.execute(
        """
        CREATE TABLE severity_config (
          id                        uuid primary key default gen_random_uuid(),
          tenant_id                 uuid,                     -- null = platform default
          metric                    text not null,            -- AMOUNT_PAISE | AGE_DAYS | WINDOW_DAYS_REMAINING
          high_threshold            bigint,
          medium_threshold          bigint,
          window_closing_soon_days  int not null default 14,
          ordering_basis            text not null,            -- WINDOW_THEN_AMOUNT | AMOUNT_ONLY
          version                   int not null,
          effective_from            date not null,
          unique (tenant_id, metric, effective_from)
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="severity_config"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS severity_config;")
    op.execute("DROP TABLE IF EXISTS reconciliation_tolerance_config;")
