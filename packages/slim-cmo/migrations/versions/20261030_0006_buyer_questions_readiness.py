"""CMO 3.0 M5: buyer-question sets and listing-readiness assessments (docs/specs/slim-cmo-agent.md section 6.17).

Two immutable, append-only tables, one row per analysis, holding exactly what the seller was shown (questions with their answers and sources; readiness items, points, statuses, verdicts and
next actions per marketplace). Tenant-owned, FORCE RLS, `SELECT, INSERT` only for the application role, idempotent per (tenant, request_key). No column exists for search volume, buyer demand,
marketplace approval or sales: they are never known and never stored.

Revision ID: 20261030_0006
Revises: 20261030_0005
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0006"
down_revision = "20261030_0005"
branch_labels = None
depends_on = None

_TABLE = """
CREATE TABLE {table} (
  id           uuid primary key default gen_random_uuid(),
  tenant_id    uuid not null,
  sku          text not null check (length(btrim(sku)) > 0),
  method       text not null check (length(btrim(method)) > 0),
  result       jsonb not null check (jsonb_typeof(result) = 'object'),
  request_key  text not null check (length(btrim(request_key)) > 0),
  created_by   uuid not null,
  agent_run_id uuid,
  created_at   timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, request_key)
);
CREATE INDEX {table}_sku_idx ON {table} (tenant_id, sku, created_at DESC);

ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

REVOKE ALL ON {table} FROM metrion_app;
GRANT SELECT, INSERT ON {table} TO metrion_app;
"""


def upgrade() -> None:
    for table in ("cmo_buyer_question_set", "cmo_readiness_assessment"):
        op.execute(_TABLE.format(table=table))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cmo_readiness_assessment; DROP TABLE IF EXISTS cmo_buyer_question_set;")
