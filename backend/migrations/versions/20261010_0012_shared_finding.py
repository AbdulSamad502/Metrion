"""shared_finding: the shared findings ledger (tier 2 of shared memory)

Spec agent-needs-and-shared-knowledge.md section 6 (2026-10-10). Append-only (SELECT, INSERT for the app role): a correction is a SELLER_STATED row that supersedes the
finding, forgetting is a FORGOTTEN row that supersedes it. FORCE RLS on tenant_id. The gate is in the database so it cannot be bypassed from code:
  * text of an agent or engine finding contains no digit (a number lives only in figure_refs and is rendered from the referenced result);
  * ENGINE_VERIFIED needs at least one figure ref and every ref is an ENGINE_RESULT;
  * every ENGINE_RESULT ref must be a metric_result of the SAME tenant, every supersedes_id a row of the same tenant (trigger, runs under RLS);
  * SELLER_STATED is only the CEO's SELLER_NOTE, cites a message and supersedes an existing finding;
  * a forgotten source (dedupe_key) is never recorded again as a new finding.

Revision ID: 20261010_0012
Revises: 20261010_0011
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_0012"
down_revision = "20261010_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE shared_finding (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          agent_code    text not null,
          kind          text not null,
          subject       text,
          text          text not null,
          trust         text not null,
          source_ref    jsonb not null,
          figure_refs   jsonb not null default '[]'::jsonb,
          dedupe_key    text not null,
          supersedes_id uuid references shared_finding(id),
          status        text not null default 'ACTIVE',
          created_by    uuid,
          created_at    timestamptz not null default now(),
          CONSTRAINT shared_finding_agent_check  CHECK (agent_code IN ('CEO', 'CFO', 'PI', 'CMO', 'CI')),
          CONSTRAINT shared_finding_kind_check   CHECK (kind IN ('PRODUCT_IDEA', 'COMPETITOR_CHANGE', 'LEAK_FOUND', 'MARGIN_ISSUE', 'DATA_GAP', 'CONTENT_READY', 'SELLER_NOTE')),
          CONSTRAINT shared_finding_pairing_check CHECK (
            (kind = 'PRODUCT_IDEA' AND agent_code = 'PI') OR (kind = 'COMPETITOR_CHANGE' AND agent_code = 'CI')
            OR (kind IN ('LEAK_FOUND', 'MARGIN_ISSUE', 'DATA_GAP') AND agent_code = 'CFO')
            OR (kind = 'CONTENT_READY' AND agent_code = 'CMO') OR (kind = 'SELLER_NOTE' AND agent_code = 'CEO')
          ),
          CONSTRAINT shared_finding_trust_check  CHECK (trust IN ('SELLER_STATED', 'ENGINE_VERIFIED', 'AGENT_REPORTED')),
          CONSTRAINT shared_finding_status_check CHECK (status IN ('ACTIVE', 'FORGOTTEN')),
          CONSTRAINT shared_finding_text_check   CHECK (char_length(text) BETWEEN 1 AND 300),
          CONSTRAINT shared_finding_subject_check CHECK (subject IS NULL OR char_length(subject) BETWEEN 1 AND 120),
          CONSTRAINT shared_finding_dedupe_check CHECK (char_length(dedupe_key) BETWEEN 1 AND 200),
          CONSTRAINT shared_finding_refs_shape_check CHECK (jsonb_typeof(figure_refs) = 'array' AND jsonb_array_length(figure_refs) <= 3),
          CONSTRAINT shared_finding_source_check CHECK (
            jsonb_typeof(source_ref) = 'object'
            AND source_ref->>'kind' IN ('agent_run', 'investigation_finding', 'metric_result', 'pi_research_run', 'competitor_snapshot', 'cmo_generation', 'message')
            AND coalesce(source_ref->>'id', '') <> ''
          ),
          -- no free number: only the seller's own words (a correction) may contain a digit
          CONSTRAINT shared_finding_no_digit_check CHECK (trust = 'SELLER_STATED' OR text !~ '[0-9]'),
          CONSTRAINT shared_finding_engine_check CHECK (
            trust <> 'ENGINE_VERIFIED'
            OR (jsonb_array_length(figure_refs) >= 1 AND NOT jsonb_path_exists(figure_refs, '$[*] ? (@.kind != "ENGINE_RESULT")'))
          ),
          CONSTRAINT shared_finding_seller_check CHECK (
            (trust = 'SELLER_STATED') = (kind = 'SELLER_NOTE')
            AND (trust <> 'SELLER_STATED'
                 OR (agent_code = 'CEO' AND source_ref->>'kind' = 'message' AND supersedes_id IS NOT NULL))
          ),
          CONSTRAINT shared_finding_forgotten_check CHECK (status <> 'FORGOTTEN' OR supersedes_id IS NOT NULL)
        );
        CREATE INDEX shared_finding_lookup_idx ON shared_finding (tenant_id, created_at DESC);
        CREATE INDEX shared_finding_supersedes_idx ON shared_finding (supersedes_id);
        -- a repeated finding (same source) is a no-op; a forgotten one stays blocked because the original row is never removed
        CREATE UNIQUE INDEX shared_finding_dedupe_uidx ON shared_finding (tenant_id, dedupe_key) WHERE supersedes_id IS NULL;

        CREATE FUNCTION shared_finding_gate() RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
          r jsonb;
        BEGIN
          IF NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM shared_finding f WHERE f.id = NEW.supersedes_id AND f.tenant_id = NEW.tenant_id) THEN
            RAISE EXCEPTION 'shared_finding: supersedes_id is not a finding of this tenant' USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.status = 'ACTIVE' AND NEW.supersedes_id IS NULL AND EXISTS (
               SELECT 1 FROM shared_finding f WHERE f.tenant_id = NEW.tenant_id AND f.dedupe_key = NEW.dedupe_key AND f.status = 'FORGOTTEN') THEN
            RAISE EXCEPTION 'shared_finding: this source was forgotten and is not recorded again' USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.status = 'ACTIVE' THEN
            FOR r IN SELECT value FROM jsonb_array_elements(NEW.figure_refs) LOOP
              IF jsonb_typeof(r) <> 'object' OR r->>'kind' NOT IN ('ENGINE_RESULT', 'ESTIMATE')
                 OR coalesce(r->>'label', '') = '' OR coalesce(r->>'id', '') !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
                RAISE EXCEPTION 'shared_finding: malformed figure ref' USING ERRCODE = 'check_violation';
              END IF;
              IF r->>'kind' = 'ENGINE_RESULT' AND NOT EXISTS (
                   SELECT 1 FROM metric_result m WHERE m.id = (r->>'id')::uuid AND m.tenant_id = NEW.tenant_id) THEN
                RAISE EXCEPTION 'shared_finding: an ENGINE_RESULT ref is not a metric_result of this tenant' USING ERRCODE = 'check_violation';
              END IF;
            END LOOP;
          END IF;
          RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER shared_finding_gate BEFORE INSERT ON shared_finding FOR EACH ROW EXECUTE FUNCTION shared_finding_gate();

        ALTER TABLE shared_finding ENABLE ROW LEVEL SECURITY;
        ALTER TABLE shared_finding FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON shared_finding
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
        -- the cluster's default privileges hand every new table full DML to the app role: take it back, append-only is a grant-level fact
        REVOKE ALL ON shared_finding FROM metrion_app;
        GRANT SELECT, INSERT ON shared_finding TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shared_finding; DROP FUNCTION IF EXISTS shared_finding_gate();")
