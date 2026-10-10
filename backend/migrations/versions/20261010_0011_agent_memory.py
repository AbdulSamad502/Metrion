"""agent_memory: private memory per agent and one shared memory

Spec agent-memory.md (2026-10-10). Append-only (SELECT, INSERT for the app role): a correction is a new row that supersedes the old one, forgetting is a FORGOTTEN
row that supersedes it. FORCE RLS on tenant_id. The shared-memory gate is a CHECK, so it cannot be bypassed from code: a SHARED row needs a shared kind and a
seller-stated or confirmed basis, and any row not written by an agent about its own work needs a source reference.

Revision ID: 20261010_0011
Revises: 20261010_0010
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_0011"
down_revision = "20261010_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_memory (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          scope         text not null,
          agent_code    text not null,
          kind          text not null,
          key           text not null,
          value         text not null,
          basis         text not null,
          source_ref    jsonb,
          supersedes_id uuid references agent_memory(id),
          status        text not null default 'ACTIVE',
          created_by    uuid,
          created_at    timestamptz not null default now(),
          CONSTRAINT agent_memory_scope_check  CHECK (scope IN ('PRIVATE', 'SHARED')),
          CONSTRAINT agent_memory_agent_check  CHECK (agent_code IN ('CEO', 'CFO', 'PI', 'CMO', 'CI')),
          CONSTRAINT agent_memory_kind_check   CHECK (kind IN ('BUSINESS_NAME', 'NICHE', 'MARKETPLACES', 'GOAL', 'BRAND_TONE', 'DECISION', 'PREFERENCE', 'NOTE')),
          CONSTRAINT agent_memory_basis_check  CHECK (basis IN ('SELLER_STATED', 'CONFIRMED_DECISION', 'AGENT_NOTE')),
          CONSTRAINT agent_memory_status_check CHECK (status IN ('ACTIVE', 'FORGOTTEN')),
          CONSTRAINT agent_memory_value_check  CHECK (char_length(value) BETWEEN 1 AND 500),
          CONSTRAINT agent_memory_shared_gate  CHECK (
            scope = 'PRIVATE'
            OR (kind IN ('BUSINESS_NAME', 'NICHE', 'MARKETPLACES', 'GOAL', 'BRAND_TONE', 'DECISION') AND basis IN ('SELLER_STATED', 'CONFIRMED_DECISION'))
          ),
          CONSTRAINT agent_memory_source_check CHECK (basis = 'AGENT_NOTE' OR source_ref IS NOT NULL)
        );
        CREATE INDEX agent_memory_lookup_idx ON agent_memory (tenant_id, scope, agent_code, kind, key, created_at);
        CREATE INDEX agent_memory_supersedes_idx ON agent_memory (supersedes_id);
        ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;
        ALTER TABLE agent_memory FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON agent_memory
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        GRANT SELECT, INSERT ON agent_memory TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_memory;")
