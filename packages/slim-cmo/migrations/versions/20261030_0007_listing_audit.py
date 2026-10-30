"""CMO 3.0 M6: the post-generation listing audit, and unverified-basis packs (docs/specs/slim-cmo-agent.md sections 6.18.5 and 6.18.11).

1. `cmo_listing_audit`: one immutable row per (pack, content hash), exactly what the seller was shown (verdict, per-check statuses including NOT_ASSESSED, findings, keyword map, measured lengths).
   Tenant-owned, FORCE RLS, composite foreign key to `cmo_generation`, `SELECT, INSERT` only for the application role. No column exists for a score, search volume, demand, ranking or
   conversion: they are never known and never stored.
2. `cmo_generation`: a completed constraint-bound artefact had to cite a `format_constraint` row. Owner decision 2026-10-30 (spec 6.18.11): an artefact the server produced on the rules-unavailable
   basis has no row to cite. The check is replaced by an equivalent one that also accepts a NULL reference ONLY when `output_structured ->> 'rules_basis' = 'UNVERIFIED'` (wrapped in COALESCE:
   an absent key, a NULL or malformed `output_structured` is NULL/false, and a CHECK that evaluates to NULL would otherwise PASS); a VERIFIED-basis
   artefact (or one with no basis recorded, i.e. every existing row) still must cite its row. Nothing is rewritten and every existing row stays valid.

Downgrade restores the strict check and REFUSES (with a clear message, nothing half-applied) while any unverified-basis artefact exists: those rows are never deleted or altered by a migration.

Revision ID: 20261030_0007
Revises: 20261030_0006
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0007"
down_revision = "20261030_0006"
branch_labels = None
depends_on = None

_CONSTRAINT_BOUND = "'TITLE_SET','LISTING_COPY','DESCRIPTION','BULLETS','KEYWORDS','BACKEND_TERMS'"
_OLD = "(status = 'FAILED' OR output_type NOT IN ({b}) OR format_constraint_ref IS NOT NULL)"
_FIND = """
DO $$
DECLARE c record;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'cmo_generation'::regclass AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%format_constraint_ref IS NOT NULL%'
  LOOP
    EXECUTE format('ALTER TABLE cmo_generation DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
"""

_AUDIT = """
CREATE TABLE cmo_listing_audit (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null,
  generation_id uuid not null,
  marketplace   text not null check (marketplace IN ('AMAZON','FLIPKART','MEESHO')),
  content_hash  text not null check (length(content_hash) = 64),
  rules_basis   text not null check (rules_basis IN ('VERIFIED','UNVERIFIED')),
  verdict       text not null check (verdict IN ('BLOCKED','NEEDS_ATTENTION','CHECKED_NOT_VERIFIED')),
  method_version text not null check (length(btrim(method_version)) > 0),
  checks        jsonb not null check (jsonb_typeof(checks) = 'array'),
  findings      jsonb not null check (jsonb_typeof(findings) = 'array'),
  keyword_map   jsonb not null check (jsonb_typeof(keyword_map) = 'object'),
  measured      jsonb not null check (jsonb_typeof(measured) = 'object'),
  created_by    uuid not null,
  agent_run_id  uuid,
  created_at    timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, generation_id, content_hash),
  FOREIGN KEY (tenant_id, generation_id) REFERENCES cmo_generation (tenant_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
);
CREATE INDEX cmo_listing_audit_generation_idx ON cmo_listing_audit (tenant_id, generation_id, created_at DESC);

ALTER TABLE cmo_listing_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE cmo_listing_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON cmo_listing_audit
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

REVOKE ALL ON cmo_listing_audit FROM metrion_app;
GRANT SELECT, INSERT ON cmo_listing_audit TO metrion_app;
"""


def upgrade() -> None:
    op.execute(_AUDIT)
    op.execute(_FIND)
    op.execute(
        "ALTER TABLE cmo_generation ADD CONSTRAINT cmo_generation_constraint_ref_check CHECK ("
        f"status = 'FAILED' OR output_type NOT IN ({_CONSTRAINT_BOUND}) OR format_constraint_ref IS NOT NULL "
        "OR COALESCE(jsonb_typeof(output_structured) = 'object' AND output_structured ->> 'rules_basis' = 'UNVERIFIED', false))"
    )


def downgrade() -> None:
    # FORCE ROW LEVEL SECURITY hides every tenant's rows from the migration role, so a SELECT here would be blind. Adding the strict check validates ALL rows regardless of RLS; if any
    # unverified-basis artefact exists it fails, and that failure is turned into a clear refusal. The whole downgrade is one transaction, so a refusal leaves everything as it was.
    op.execute("DROP TABLE IF EXISTS cmo_listing_audit;")
    op.execute("ALTER TABLE cmo_generation DROP CONSTRAINT IF EXISTS cmo_generation_constraint_ref_check;")
    op.execute(
        f"""
DO $$
BEGIN
  ALTER TABLE cmo_generation ADD CONSTRAINT cmo_generation_constraint_ref_legacy_check CHECK {_OLD.format(b=_CONSTRAINT_BOUND)};
EXCEPTION WHEN check_violation THEN
  RAISE EXCEPTION 'cannot downgrade: unverified-basis artefacts exist in cmo_generation and are never deleted by a migration';
END $$;
"""
    )
