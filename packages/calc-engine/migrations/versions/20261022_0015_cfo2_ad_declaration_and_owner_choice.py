"""CFO 2.0 Phase 3b — advertising coverage declarations and cost-owner choices (docs/specs/cfo-phase3-scope.md AD3, AD4).

ad_period_declaration   the seller's explicit "no advertising" for a marketplace and period (so a missing report is a verified zero, not an unknown)
cost_owner_choice       which source owns a cost component for a marketplace and period when two sources exist (cost-ownership matrix, V-DUP-2)

Both are append-only (SELECT and INSERT only for the application role); a later row supersedes an earlier one.

Revision ID: 20261022_0015
Revises: 20261021_0014
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op

revision = "20261022_0015"
down_revision = "20261021_0014"
branch_labels = None
depends_on = None

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT ON {table} TO metrion_app;
REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM metrion_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ad_period_declaration (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          marketplace   text not null,
          period_start  date not null,
          period_end    date not null,
          declaration   text not null,
          declared_by   uuid not null,
          declared_at   timestamptz not null default now(),
          supersedes_id uuid,
          CONSTRAINT ad_period_declaration_kind_check CHECK (declaration IN ('NO_ADS')),
          CONSTRAINT ad_period_declaration_market_check CHECK (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          CONSTRAINT ad_period_declaration_order_check CHECK (period_end >= period_start)
        );
        CREATE INDEX ad_period_declaration_idx ON ad_period_declaration (tenant_id, marketplace, period_start, period_end);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="ad_period_declaration"))

    op.execute(
        """
        CREATE TABLE cost_owner_choice (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          component     text not null,
          marketplace   text not null,
          period_start  date not null,
          period_end    date not null,
          owner         text not null,
          chosen_by     uuid not null,
          chosen_at     timestamptz not null default now(),
          supersedes_id uuid,
          CONSTRAINT cost_owner_choice_component_check CHECK (component IN ('ADVERTISING')),
          CONSTRAINT cost_owner_choice_owner_check CHECK (owner IN ('REPORT','POOL')),
          CONSTRAINT cost_owner_choice_market_check CHECK (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          CONSTRAINT cost_owner_choice_order_check CHECK (period_end >= period_start)
        );
        CREATE INDEX cost_owner_choice_idx ON cost_owner_choice (tenant_id, component, marketplace, period_start, period_end);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="cost_owner_choice"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cost_owner_choice;")
    op.execute("DROP TABLE IF EXISTS ad_period_declaration;")
