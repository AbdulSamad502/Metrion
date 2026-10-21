"""CFO 2.0 engine-owned tables — docs/specs/cfo-unified-financials.md §5, deterministic-engine.md §5.17.

expense_class_map         configuration: which accounting class an expense category belongs to
                          (ALLOCATED_COST | OVERHEAD | OWNER_DRAWING | INVENTORY_PURCHASE | CAPITAL | TAX_ASSET |
                          OTHER_UNCLASSIFIED) and the allocation basis for shared pools. Tenant-nullable
                          platform-default pattern, mirroring `financial_health_config`. **Nothing is seeded**:
                          the class of a category is the seller's confirmation (cfo-unified-financials OQ2),
                          never an assumption.
cfo_read_model_version    one monotone counter per tenant, bumped in the same transaction as any write that
                          changes canonical financial data; it is the cache-invalidation signal
                          (cfo-query-planner.md D2/§6.4).

Revision ID: 20261021_0013
Revises: 20260929_0012
Create Date: 2026-10-21
"""
from __future__ import annotations

from alembic import op

revision = "20261021_0013"
down_revision = "20260929_0012"
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

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE expense_class_map (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid,                         -- null = platform default
          category          text not null,
          class             text not null,
          allocation_basis  text,                         -- NET_REVENUE | UNITS | ORDERS; null = account level, unallocated
          effective_from    date not null,
          version           int not null,
          unique (tenant_id, category, effective_from),
          CONSTRAINT expense_class_map_class_check CHECK (class IN
            ('ALLOCATED_COST','OVERHEAD','OWNER_DRAWING','INVENTORY_PURCHASE','CAPITAL','TAX_ASSET','OTHER_UNCLASSIFIED')),
          CONSTRAINT expense_class_map_basis_check CHECK (allocation_basis IS NULL OR allocation_basis IN ('NET_REVENUE','UNITS','ORDERS'))
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="expense_class_map"))
    # Configuration, like every other tenant-nullable platform-default table: the application role may only READ it (least privilege,
    # backend migration 20261012_0018). Were it writable, the nullable-tenant policy would let the app role insert platform-default rows
    # visible to every tenant. A seller's own classification is recorded as a `manual_adjustment` (`expense.class`), never here.
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON expense_class_map FROM metrion_app;")

    op.execute(
        """
        CREATE TABLE cfo_read_model_version (
          tenant_id     uuid primary key,
          data_version  bigint not null default 0,
          updated_at    timestamptz not null default now()
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="cfo_read_model_version"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cfo_read_model_version;")
    op.execute("DROP TABLE IF EXISTS expense_class_map;")
