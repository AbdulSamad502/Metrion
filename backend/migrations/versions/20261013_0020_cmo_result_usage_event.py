"""cmo_result_usage_event: append-only record of CMO result generation / viewing / copying / explicit reuse

Spec docs/specs/ceo-cmo-delegation.md section 5.1 (CD14). Sits on `20261012_0019` (the CEO approval workflow), which sits on `20261012_0015` (RAG).

What the DATABASE enforces:
  * tenant-owned, ENABLE + FORCE ROW LEVEL SECURITY, `tenant_isolation` policy identical to the other CMO tables.
  * the app role is SELECT + INSERT only (explicit REVOKE ALL first: default privileges would otherwise hand it full CRUD, 0018 lesson). No UPDATE, DELETE, TRUNCATE.
  * `GENERATED` is written by the SERVER only: two AFTER INSERT triggers on `cmo_generation` / `cmo_title_option` write it in the very transaction that inserts the
    artefact (surface SYSTEM, actor = the requester). A CHECK ties surface SYSTEM to GENERATED and forbids GENERATED from any other surface, so a client-driven insert
    path can never forge one. The HTTP route additionally accepts only VIEWED / COPIED / MARKED_USED.
  * composite (tenant_id, generation_id) / (tenant_id, option_id) foreign keys: a plain id FK is checked with owner privileges and would accept another tenant's row.
    They are ON DELETE CASCADE only so the owner role's test/erasure purge of an artefact is not blocked; the app role cannot delete either side.
  * no seller text or figure is copied into an event.

Revision ID: 20261013_0020
Revises: 20261012_0019
Create Date: 2026-10-13
"""
from __future__ import annotations

from alembic import op

revision = "20261013_0020"
down_revision = "20261012_0019"
branch_labels = None
depends_on = None

_PARTS = ("TITLE", "BULLET_1", "BULLET_2", "BULLET_3", "BULLET_4", "BULLET_5", "DESCRIPTION", "BACKEND_TERMS", "FULL_PACK", "HASHTAGS")


def upgrade() -> None:
    parts = ",".join(f"'{p}'" for p in _PARTS)
    op.execute(
        f"""
        CREATE TABLE cmo_result_usage_event (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null,
          generation_id uuid not null,
          option_id     uuid,
          result_part   text,
          event_kind    text not null,
          actor_user_id uuid not null,
          occurred_at   timestamptz not null default now(),
          surface       text not null,
          CONSTRAINT cmo_usage_kind_check    CHECK (event_kind IN ('GENERATED','VIEWED','COPIED','MARKED_USED')),
          CONSTRAINT cmo_usage_surface_check CHECK (surface IN ('DASHBOARD','CHAT','SYSTEM')),
          CONSTRAINT cmo_usage_part_check    CHECK (result_part IS NULL OR result_part IN ({parts})),
          CONSTRAINT cmo_usage_system_only_generated CHECK ((surface = 'SYSTEM') = (event_kind = 'GENERATED')),
          FOREIGN KEY (tenant_id, generation_id) REFERENCES cmo_generation (tenant_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE,
          FOREIGN KEY (tenant_id, option_id)     REFERENCES cmo_title_option (tenant_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY IMMEDIATE
        );
        CREATE INDEX cmo_usage_event_generation_idx ON cmo_result_usage_event (tenant_id, generation_id, occurred_at);
        CREATE INDEX cmo_usage_event_option_idx ON cmo_result_usage_event (tenant_id, option_id) WHERE option_id IS NOT NULL;

        ALTER TABLE cmo_result_usage_event ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cmo_result_usage_event FORCE  ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cmo_result_usage_event
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

        REVOKE ALL ON cmo_result_usage_event FROM metrion_app;
        GRANT SELECT, INSERT ON cmo_result_usage_event TO metrion_app;

        CREATE FUNCTION cmo_usage_generated_for_generation() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
          -- a title set records one GENERATED per option (below); a trend report is not a copyable result
          IF NEW.status = 'COMPLETE' AND NEW.output_type NOT IN ('TITLE_SET', 'TREND_REPORT') THEN
            INSERT INTO cmo_result_usage_event (tenant_id, generation_id, event_kind, actor_user_id, surface)
            VALUES (NEW.tenant_id, NEW.id, 'GENERATED', NEW.generated_by, 'SYSTEM');
          END IF;
          RETURN NEW;
        END $fn$;
        CREATE TRIGGER cmo_generation_usage_generated AFTER INSERT ON cmo_generation
          FOR EACH ROW EXECUTE FUNCTION cmo_usage_generated_for_generation();

        CREATE FUNCTION cmo_usage_generated_for_option() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
          INSERT INTO cmo_result_usage_event (tenant_id, generation_id, option_id, event_kind, actor_user_id, surface)
          SELECT NEW.tenant_id, NEW.generation_id, NEW.id, 'GENERATED', g.generated_by, 'SYSTEM'
          FROM cmo_generation g WHERE g.tenant_id = NEW.tenant_id AND g.id = NEW.generation_id;
          RETURN NEW;
        END $fn$;
        CREATE TRIGGER cmo_title_option_usage_generated AFTER INSERT ON cmo_title_option
          FOR EACH ROW EXECUTE FUNCTION cmo_usage_generated_for_option();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS cmo_title_option_usage_generated ON cmo_title_option;
        DROP TRIGGER IF EXISTS cmo_generation_usage_generated ON cmo_generation;
        DROP FUNCTION IF EXISTS cmo_usage_generated_for_option();
        DROP FUNCTION IF EXISTS cmo_usage_generated_for_generation();
        DROP TABLE IF EXISTS cmo_result_usage_event;
        """
    )
