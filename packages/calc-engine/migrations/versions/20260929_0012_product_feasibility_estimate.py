"""product_feasibility_estimate — deterministic-engine.md §5.13.2, §9.1. PI-exclusive.

Second table in the `estimate_ref` family alongside `competitor_estimate` (§9.1) —
structurally separate, never shares an id space, never written to `metric_result`.
Backs `calc_engine.api.estimate_product_feasibility.estimate_product_feasibility(...)`.
Real business logic is Checkpoint 2's job (see the PI build plan) — this migration only
creates the table, per the same RLS boilerplate as
`20260917_0001_engine_tables.py`/auth.md §7.3.

Revision ID: 20260929_0012
Revises: 20260929_0011
Create Date: 2026-09-29
"""
from __future__ import annotations

from alembic import op

revision = "20260929_0012"
down_revision = "20260929_0011"
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
    # --- product_feasibility_estimate (§5.13.2, §9.1) -----------------------------------
    op.execute(
        """
        CREATE TABLE product_feasibility_estimate (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid not null,
          low_paise              bigint not null,
          high_paise             bigint not null,
          confidence             text not null,        -- DERIVED, never better (§5.13.2 rule)
          basis                  text not null,
          assumptions            jsonb not null,        -- every fee reference used, every gap named
          cogs_basis             text not null,         -- STATED | UNKNOWN (§5.13.2 rule 6)
          fee_reference_version  int not null,
          observation_ref        jsonb not null,        -- source_url + fetched_at (ProspectiveObservationSet)
          formula_version        text not null,
          config_version         text not null,
          computed_at            timestamptz not null
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="product_feasibility_estimate"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_feasibility_estimate;")
