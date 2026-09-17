"""orchestration tables: investigation, investigation_message, agent_run

ceo-agent-orchestration.md §5. `tenant_id` columns here carry no FK to `tenant(id)` — the
spec's own DDL doesn't declare one (unlike auth.md's explicit `references tenant`), and
`data-foundation.md`'s tables follow the same convention, so this migration matches that
established precedent rather than adding a cross-spec constraint the spec never stated.

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

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- investigation (§5) -----------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE investigation (
          id                      uuid primary key default gen_random_uuid(),
          tenant_id               uuid not null,
          title                   text,               -- auto-generated from the first message, editable
          status                  text not null,      -- ACTIVE | ARCHIVED
          created_by              uuid not null,
          summary                 text,                -- compressed running summary (D2); null until first regeneration
          summary_covers_through  uuid,                -- fk to the last investigation_message folded into `summary`
          created_at              timestamptz not null default now(),
          last_message_at         timestamptz not null default now()
        );
        CREATE INDEX investigation_tenant_last_message_idx ON investigation (tenant_id, last_message_at);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="investigation"))

    # --- agent_run (§5, C7) — created before investigation_message so the latter's FK resolves
    op.execute(
        """
        CREATE TABLE agent_run (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid not null,
          agent_id            text not null,          -- CEO | PI | CI | CFO | CMO | BRAIN1
          trigger_type        text not null,          -- DIRECT | CONVERSATIONAL
          trigger_ref         text not null,           -- e.g. "pi.discover", "cfo.reconcile", "ceo.chat_turn", "brain1.compute_metric"
          investigation_id    uuid references investigation(id),   -- set only for CONVERSATIONAL
          parent_run_id       uuid references agent_run(id),        -- null for the CEO's own turn-level row
          requested_by        uuid not null,
          permission_check    text not null,          -- PASS | DENIED, and which key failed if denied
          entitlement_check   text not null,          -- PASS | DENIED
          status              text not null,           -- QUEUED | RUNNING | PARTIAL | COMPLETE | FAILED | DENIED
          output_refs         jsonb,                   -- engine_result_ref[] / estimate_ref[] this run produced
          error_reason        text,
          started_at          timestamptz,
          finished_at         timestamptz
        );
        CREATE INDEX agent_run_tenant_started_idx ON agent_run (tenant_id, started_at);
        CREATE INDEX agent_run_investigation_idx ON agent_run (investigation_id);
        CREATE INDEX agent_run_parent_run_idx ON agent_run (parent_run_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="agent_run"))

    # --- investigation_message (§5) ---------------------------------------------------------
    op.execute(
        """
        CREATE TABLE investigation_message (
          id                uuid primary key default gen_random_uuid(),
          investigation_id  uuid not null references investigation(id),
          tenant_id         uuid not null,
          role              text not null,            -- USER | CEO | SYSTEM
          content           text not null,
          agent_run_id      uuid references agent_run(id),   -- set when this CEO message resulted from an agent/Brain 1 invocation
          created_by        uuid,                       -- the member who sent a USER message; null for CEO/SYSTEM
          created_at        timestamptz not null default now()
        );
        CREATE INDEX investigation_message_investigation_idx ON investigation_message (investigation_id, created_at);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="investigation_message"))

    # investigation.summary_covers_through references investigation_message, which didn't
    # exist yet when `investigation` was created above — added now that it does.
    op.execute(
        "ALTER TABLE investigation ADD CONSTRAINT investigation_summary_covers_through_fk "
        "FOREIGN KEY (summary_covers_through) REFERENCES investigation_message(id);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE investigation DROP CONSTRAINT IF EXISTS investigation_summary_covers_through_fk;")
    op.execute("DROP TABLE IF EXISTS investigation_message;")
    op.execute("DROP TABLE IF EXISTS agent_run;")
    op.execute("DROP TABLE IF EXISTS investigation;")
