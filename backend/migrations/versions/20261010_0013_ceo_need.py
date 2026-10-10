"""ceo_need: who the CEO asked for what (spec agent-needs-and-shared-knowledge.md 9.1)

Append-only (SELECT, INSERT for the app role), FORCE RLS on tenant_id. One row is written when a need ends. It holds no money and no text: the Hub reads it to show that
"the CEO asked the GST lookup for the rate", and the unique idempotency key stops a retried turn from recording (or metering) it twice.

Revision ID: 20261010_0013
Revises: 20261010_0011
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_0013"
down_revision = "20261010_0011"  # re-pointed to 20261010_0012 (shared_finding) when that slice is merged
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ceo_need (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null,
          investigation_id   uuid not null,
          turn_message_id    uuid,
          need_key           text not null,
          requester_agent    text not null,
          mode               text not null,
          provider_key       text,
          slot_digest        text,
          idempotency_key    text not null,
          requester_run_id   uuid,
          provider_run_id    uuid,
          status             text not null,
          reused_from_need_id uuid,
          created_at         timestamptz not null default now(),
          CONSTRAINT ceo_need_agent_check  CHECK (requester_agent IN ('CEO', 'CFO', 'PI', 'CMO', 'CI')),
          CONSTRAINT ceo_need_mode_check   CHECK (mode IN ('PARALLEL', 'OFFER', 'AFTER_RESULT')),
          CONSTRAINT ceo_need_status_check CHECK (status IN ('FULFILLED', 'REUSED', 'DENIED', 'NOT_ATTACHED', 'NOT_ENTITLED', 'UNAVAILABLE', 'FAILED', 'TIMED_OUT', 'CONFIG_MISSING', 'OFFERED', 'DROPPED')),
          CONSTRAINT ceo_need_idem_unique UNIQUE (tenant_id, idempotency_key)
        );
        CREATE INDEX ceo_need_investigation_idx ON ceo_need (tenant_id, investigation_id, created_at);
        ALTER TABLE ceo_need ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ceo_need FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON ceo_need
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT ON ceo_need TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ceo_need;")
