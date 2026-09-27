"""CFO-owned tables: leak_finding, agent_data_request

docs/specs/cfo-agent.md §5. auth.md §7.3 for the RLS pattern.

Scope note (CP1, plan `twinkly-mapping-canyon.md`): this migration creates exactly these two
tables. It does NOT create `cash_view` — that is a derived read model deferred on the
not-yet-built `cash_reconciliation()` engine function (see migrations/README.md). It does not
touch any data-foundation or calc-engine DDL (`sales_line`, `line_component`, `metric_result`,
`manual_adjustment`, ...) — those are owned by their own packages' migration histories.

Revision ID: 20260923_0001
Revises:
Create Date: 2026-09-23
"""
from __future__ import annotations

from alembic import op

revision = "20260923_0001"
down_revision = None
branch_labels = None
depends_on = None

# auth.md §7.3: FORCE ROW LEVEL SECURITY, SET LOCAL app.current_tenant_id, fail-closed via
# current_setting(..., true) returning NULL -> zero rows when context is unset. Applied
# identically to every tenant-owned table created here.
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- leak_finding (§5) — interpretation of an engine exception. amount_paise is COPIED
    # from the exception, never recomputed here (§6.4 rule, AC4). ------------------------
    op.execute(
        """
        CREATE TABLE leak_finding (
          id                            uuid primary key default gen_random_uuid(),
          tenant_id                     uuid not null,
          reconciliation_exception_id   uuid not null,   -- engine-owned; amount lives there
          engine_result_ref             uuid not null,   -- deterministic-engine.md §9.1
          marketplace                   text not null,
          leak_category                 text not null,   -- §6.3; PROVISIONAL mapping, Q12
          severity                      text not null,   -- HIGH | MEDIUM | LOW (engine §5.14.1)
          amount_paise                  bigint not null, -- copied from the exception
          affected_line_count           int not null,
          sku                           text,
          first_observed_at             timestamptz not null,
          age_days                      int not null,
          claim_window_days             int,
          window_status                 text,            -- OPEN | CLOSING_SOON | EXPIRED | UNKNOWN
          explanation                   text,            -- Brain 3; no LLM-produced number
          recommended_action            text,
          status                        text not null,   -- NEW | ACKNOWLEDGED | ACTIONED | DISMISSED
          confidence                    text not null,   -- §5.2 vocabulary
          formula_version               text not null
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="leak_finding"))

    # --- agent_data_request (§5) — OP1: CFO asks rather than assumes ---------------------
    op.execute(
        """
        CREATE TABLE agent_data_request (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          requested_field     text not null,
          reason              text not null,
          blocking_metric     text,             -- what cannot be computed without it
          status              text not null,    -- OPEN | ANSWERED | DECLINED
          answered_with_kind  text,             -- MANUAL_ADJUSTMENT (only target type in V1)
          answered_with_id    uuid,
          created_at          timestamptz not null default now()
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="agent_data_request"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_data_request;")
    op.execute("DROP TABLE IF EXISTS leak_finding;")
