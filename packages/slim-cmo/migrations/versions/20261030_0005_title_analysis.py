"""CMO 3.0 M3: five-title quality analyses (docs/specs/slim-cmo-agent.md section 6.15).

One immutable row per analysis of a saved title set: every option's per-dimension results, hard failures, strategy label, the recommendation and the limits exactly as the seller was
shown them. Tenant-owned, FORCE RLS, composite foreign key so an analysis can never point at another tenant's title set, append-only for the application role (SELECT and INSERT only),
idempotent per (tenant, request_key). The title options themselves are NOT changed: their `rank` stays "presentation order, not a quality claim". No numeric score column exists.

Revision ID: 20261030_0005
Revises: 20261030_0004
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0005"
down_revision = "20261030_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cmo_title_analysis (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          generation_id uuid not null,
          marketplace   text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          method        text not null check (length(btrim(method)) > 0),
          result        jsonb not null check (jsonb_typeof(result) = 'object'),
          request_key   text not null check (length(btrim(request_key)) > 0),
          created_by    uuid not null,
          agent_run_id  uuid,
          created_at    timestamptz not null default now(),
          unique (tenant_id, id),
          unique (tenant_id, request_key),
          FOREIGN KEY (tenant_id, generation_id) REFERENCES cmo_generation (tenant_id, id) DEFERRABLE INITIALLY IMMEDIATE
        );
        CREATE INDEX cmo_title_analysis_generation_idx ON cmo_title_analysis (tenant_id, generation_id, created_at DESC);

        ALTER TABLE cmo_title_analysis ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cmo_title_analysis FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cmo_title_analysis
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

        REVOKE ALL ON cmo_title_analysis FROM metrion_app;
        GRANT SELECT, INSERT ON cmo_title_analysis TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cmo_title_analysis;")
