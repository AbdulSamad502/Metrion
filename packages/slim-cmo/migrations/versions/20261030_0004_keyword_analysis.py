"""CMO 3.0 M2: evidence-backed keyword analyses (docs/specs/slim-cmo-agent.md section 6.14).

One immutable row per analysis: the candidates, exclusions, evidence and limits exactly as the seller was shown them, so a later change to a fact or a competitor insight never rewrites
what was said. Tenant-owned, FORCE RLS, append-only for the application role (SELECT and INSERT only). Idempotent per (tenant, request_key). No search volume, demand or rank column
exists: those are never stored because they are never known.

Revision ID: 20261030_0004
Revises: 20261006_0003
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0004"
down_revision = "20261006_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cmo_keyword_analysis (
          id          uuid primary key default gen_random_uuid(),
          tenant_id   uuid not null,
          sku         text not null check (length(btrim(sku)) > 0),
          marketplace text check (marketplace IS NULL OR marketplace IN ('AMAZON','FLIPKART','MEESHO')),
          method      text not null check (length(btrim(method)) > 0),
          status      text not null check (status IN ('COMPLETE','NO_FACTS')),
          result      jsonb not null check (jsonb_typeof(result) = 'object'),
          request_key text not null check (length(btrim(request_key)) > 0),
          created_by  uuid not null,
          agent_run_id uuid,
          created_at  timestamptz not null default now(),
          unique (tenant_id, id),
          unique (tenant_id, request_key)
        );
        CREATE INDEX cmo_keyword_analysis_sku_idx ON cmo_keyword_analysis (tenant_id, sku, created_at DESC);

        ALTER TABLE cmo_keyword_analysis ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cmo_keyword_analysis FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cmo_keyword_analysis
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

        REVOKE ALL ON cmo_keyword_analysis FROM metrion_app;
        GRANT SELECT, INSERT ON cmo_keyword_analysis TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cmo_keyword_analysis;")
