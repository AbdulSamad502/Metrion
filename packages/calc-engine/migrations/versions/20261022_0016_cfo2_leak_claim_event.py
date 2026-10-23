"""CFO 2.0 Phase 3d — the seller's claim lifecycle for a leak finding (docs/specs/cfo-phase3-scope.md LD3).

leak_claim_event   append-only: one row per state the SELLER reports for a discrepancy (Metrion never files a claim). The current state is the latest
                   event; before any event it is the finding's own status. SELECT and INSERT only for the application role.

Revision ID: 20261022_0016
Revises: 20261022_0015c
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op

revision = "20261022_0016"
down_revision = "20261022_0015c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE leak_claim_event (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid not null,
          leak_finding_id uuid not null,
          from_state      text not null,
          to_state        text not null,
          actor           uuid not null,
          note            text,
          created_at      timestamptz not null default now(),
          CONSTRAINT leak_claim_event_to_check CHECK (to_state IN
            ('ACKNOWLEDGED','CLAIM_DRAFTED','SELLER_REPORTED_RAISED','SELLER_REPORTED_RESOLVED','DISMISSED')),
          CONSTRAINT leak_claim_event_from_check CHECK (from_state IN
            ('NEW','ACKNOWLEDGED','CLAIM_DRAFTED','SELLER_REPORTED_RAISED'))
        );
        CREATE INDEX leak_claim_event_finding_idx ON leak_claim_event (tenant_id, leak_finding_id, created_at);
        ALTER TABLE leak_claim_event ENABLE ROW LEVEL SECURITY;
        ALTER TABLE leak_claim_event FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON leak_claim_event
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT ON leak_claim_event TO metrion_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON leak_claim_event FROM metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leak_claim_event;")
