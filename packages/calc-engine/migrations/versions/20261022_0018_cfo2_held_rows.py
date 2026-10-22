"""CFO 2.0 dashboard track — held duplicate rows are kept, so the seller can decide (docs/specs/cfo-data-intelligence.md §6.3a).

held_row             append-only: a row an upload held back (same order line with different values, or an identical repeat that cannot be told from a double
                     export). Its values are kept verbatim so the seller can see it; it never reaches a figure.
held_row_resolution  append-only: the seller's decision about one held row (KEEP_EARLIER or DISCARD). The current state is the latest resolution; none = still held.
Both: SELECT and INSERT only for the application role.

Revision ID: 20261022_0018
Revises: 20261022_0017
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op

revision = "20261022_0018"
down_revision = "20261022_0017"
branch_labels = None
depends_on = None

_RLS = """
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON {t}
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT ON {t} TO metrion_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON {t} FROM metrion_app;
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE held_row (
          id               uuid primary key default gen_random_uuid(),
          tenant_id        uuid not null,
          ingestion_run_id uuid not null,
          report_file_id   uuid not null,
          marketplace      text not null,
          row_number       integer not null,
          kind             text not null,
          rule             text not null,
          reason           text not null,
          earlier_row      integer,
          row_values       jsonb not null,
          created_at       timestamptz not null default now(),
          CONSTRAINT held_row_kind_check CHECK (kind IN ('CONFLICT','AMBIGUOUS')),
          CONSTRAINT held_row_unique UNIQUE (tenant_id, ingestion_run_id, row_number)
        );
        CREATE INDEX held_row_file_idx ON held_row (tenant_id, report_file_id, row_number);
        """
        + _RLS.format(t="held_row")
        + """
        CREATE TABLE held_row_resolution (
          id          uuid primary key default gen_random_uuid(),
          tenant_id   uuid not null,
          held_row_id uuid not null,
          action      text not null,
          note        text,
          resolved_by uuid not null,
          created_at  timestamptz not null default now(),
          CONSTRAINT held_row_resolution_action_check CHECK (action IN ('KEEP_EARLIER','DISCARD'))
        );
        CREATE UNIQUE INDEX held_row_resolution_once_uq ON held_row_resolution (tenant_id, held_row_id);
        """
        + _RLS.format(t="held_row_resolution")
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS held_row_resolution; DROP TABLE IF EXISTS held_row;")
