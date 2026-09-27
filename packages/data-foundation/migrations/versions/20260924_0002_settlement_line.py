"""settlement_line — data-foundation.md §5.6 (CONFIRMED, Phase C, C1), §5.7 (migration
ownership CONFIRMED, Phase C, C2). auth.md §7.3 for the RLS pattern, mirrored verbatim from
`sales_line` (real-tenant-rows pattern), not `reconciliation_tolerance_config`'s
nullable-platform-default pattern.

Column list and every comment below is copied from §5.6's DDL block verbatim — no column
added, renamed, or omitted beyond what that section states. §5.6 itself grounds every field
either in `sales_line`'s real §1.3 columns (mirrored 1:1) or in evidence cited at
§5.1/§5.4/§2.3 of the same spec.

Also closes the FK gap left open by 20260917_0001: `line_component.settlement_line_id` was
created as a bare UUID column with the comment "FK omitted: settlement_line has no schema yet
(deferred)". Now that settlement_line exists, that FK is added here, mirroring
`sales_line_id`'s existing real FK exactly.

Revision ID: 20260924_0002
Revises: 20260917_0001
Create Date: 2026-09-24
"""
from __future__ import annotations

from alembic import op

revision = "20260924_0002"
down_revision = "20260917_0001"
branch_labels = None
depends_on = None

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- settlement_line (§5.6) -----------------------------------------------------------
    op.execute(
        """
        CREATE TABLE settlement_line (
          id                       uuid primary key default gen_random_uuid(),
          tenant_id                uuid not null,
          ingestion_run_id         uuid not null references ingestion_run(id),
          marketplace              text not null,
          order_ref                text,
          line_ref                 text,
          settlement_id            text,
          gross_settlement_amount  bigint,
          currency                 char(3) not null default 'INR',
          settlement_date          date,
          document_type            text,
          source_row_number        int not null,
          source_row_json          jsonb not null,
          confidence                text not null   -- VERIFIED | PROVISIONAL | DERIVED | MANUAL
        );
        CREATE INDEX settlement_line_ingestion_run_idx ON settlement_line (ingestion_run_id);
        CREATE INDEX settlement_line_tenant_natural_key_idx ON settlement_line (tenant_id, marketplace, order_ref, line_ref, settlement_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="settlement_line"))

    # --- close the deferred FK gap on line_component.settlement_line_id (§1.4, §5.6) -------
    op.execute(
        """
        ALTER TABLE line_component
          ADD CONSTRAINT line_component_settlement_line_id_fkey
          FOREIGN KEY (settlement_line_id) REFERENCES settlement_line(id);
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE line_component DROP CONSTRAINT IF EXISTS line_component_settlement_line_id_fkey;"
    )
    op.execute("DROP TABLE IF EXISTS settlement_line;")
