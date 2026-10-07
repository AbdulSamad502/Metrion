"""ceo foundation: investigation lifecycle, turns, findings, agent attachment

ceo-agent-orchestration.md §5 (CP1 amendment 2026-10-07), B1 Foundation. Adds ONLY the V1-core
shapes; the V1-later tables (`ceo_goal`, `situation`, `ceo_decision`, `ceo_open_issue`,
`ceo_followup`) are specified but deliberately not created yet.

* `investigation`: `origin`, `situation_id` (no FK - `situation` is V1-later), RESOLVED lifecycle
  (`resolution_note`/`resolved_by`/`resolved_at`), and CHECKs on `status`/`origin`.
* `investigation_message`: `kind`, `turn_id`, CHECKs on `role`/`kind`.
* `investigation_turn`: one row per conversational turn (the audit/eval unit above `agent_run`).
* `investigation_finding`: the by-reference evidence ledger. Holds refs and pointers only - never a
  value the CEO computed (spec R7).
* `investigation_agent`: which specialists are attached to an investigation (spec §6.22). Attachment
  only ever NARROWS what the CEO may call or read (spec R13); it grants nothing.
* `agent_run`: no new column (`investigation_id`/`output_refs`/`parent_run_id` already exist). Adds
  `trigger_type` / `agent_id` CHECKs as NOT VALID: they bind every NEW row but do not re-validate
  history, so a legacy row can never block this migration.

The application role gets SELECT/INSERT/UPDATE on the three new tables and no DELETE: turns and
findings are audit evidence. (`docker/postgres-init/02-roles.sql` sets ALTER DEFAULT PRIVILEGES so that
metrion_app would otherwise receive DELETE on every new table; the migration therefore REVOKEs it.) (Test cleanup runs as the table owner through RLS.)

A foreign key is checked with the owner's privileges and therefore does NOT enforce tenant
isolation by itself; `repositories/investigation_repo.py` re-checks that the parent row is visible in
the caller's tenant before every insert (defence in depth, auth.md §7.3).

Revision ID: 20261007_0006
Revises: 20261004_0005
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op

revision = "20261007_0006"
down_revision = "20261004_0005"
branch_labels = None
depends_on = None

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON {table} TO metrion_app;
-- The init script's ALTER DEFAULT PRIVILEGES hands metrion_app full CRUD on every new table, so DELETE must be revoked explicitly.
REVOKE DELETE ON {table} FROM metrion_app;
"""


def upgrade() -> None:
    # --- investigation ------------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE investigation
          ADD COLUMN origin          text NOT NULL DEFAULT 'USER_CHAT',
          ADD COLUMN situation_id    uuid,
          ADD COLUMN resolution_note text,
          ADD COLUMN resolved_by     uuid,
          ADD COLUMN resolved_at     timestamptz;
        ALTER TABLE investigation
          ADD CONSTRAINT investigation_status_check CHECK (status IN ('ACTIVE','RESOLVED','ARCHIVED')) NOT VALID,
          ADD CONSTRAINT investigation_origin_check CHECK (origin IN ('USER_CHAT','WHATSAPP','SYSTEM')),
          ADD CONSTRAINT investigation_resolved_has_note CHECK (
            status <> 'RESOLVED' OR (resolved_at IS NOT NULL AND resolved_by IS NOT NULL
                                     AND resolution_note IS NOT NULL AND length(btrim(resolution_note)) > 0)
          );
        """
    )

    # --- break the pre-existing delete cycle ----------------------------------------------------
    # `investigation.summary_covers_through -> investigation_message` points back at a table that already references
    # `investigation` (investigation_message.investigation_id), so no children-before-parents deletion order existed. It never
    # mattered while nothing wrote investigation rows; now that the CEO does, tenant erasure and test cleanup need an order.
    # The column stays (the rolling-summary pointer, spec §6.6); the repository maintains it.
    op.execute("ALTER TABLE investigation DROP CONSTRAINT IF EXISTS investigation_summary_covers_through_fk;")

    # --- agent_run: bind new rows only --------------------------------------------------------
    op.execute(
        """
        ALTER TABLE agent_run
          ADD CONSTRAINT agent_run_trigger_type_check
            CHECK (trigger_type IN ('DIRECT','CONVERSATIONAL','SYSTEM')) NOT VALID,
          ADD CONSTRAINT agent_run_agent_id_check
            CHECK (agent_id IN ('CEO','PI','CI','CFO','CMO','BRAIN1','GST_LOOKUP')) NOT VALID;
        """
    )

    # --- investigation_message ----------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE investigation_message
          ADD COLUMN kind    text NOT NULL DEFAULT 'TEXT',
          ADD COLUMN turn_id uuid;
        ALTER TABLE investigation_message
          ADD CONSTRAINT investigation_message_role_check CHECK (role IN ('USER','CEO','SYSTEM')) NOT VALID,
          ADD CONSTRAINT investigation_message_kind_check
            CHECK (kind IN ('TEXT','CLARIFICATION','ANSWER','BRIEFING','SYSTEM_NOTE'));
        """
    )

    # --- investigation_turn -------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE investigation_turn (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          investigation_id  uuid not null references investigation(id),
          user_message_id   uuid not null references investigation_message(id),
          ceo_message_id    uuid references investigation_message(id),
          agent_run_id      uuid not null references agent_run(id),   -- the CEO anchor row (parent_run_id null)
          route             text not null,
          route_key         text,
          route_source      text not null default 'CLASSIFIER',
          slots             jsonb,
          classifier_result jsonb,
          composition_mode  text,
          safety_result     jsonb,
          stage_timings     jsonb,
          status            text not null,
          created_at        timestamptz not null default now(),
          completed_at      timestamptz,
          CONSTRAINT investigation_turn_route_check CHECK (route IN
            ('BUSINESS_STATE','ACTION','PLAYBOOK','ADVISORY','SYNTHESIZE','CLARIFY','OUT_OF_SCOPE')),
          CONSTRAINT investigation_turn_route_source_check CHECK (route_source IN ('CLASSIFIER','UI_ACTION')),
          CONSTRAINT investigation_turn_composition_mode_check
            CHECK (composition_mode IS NULL OR composition_mode IN ('LLM','TEMPLATE','TEMPLATE_FALLBACK')),
          CONSTRAINT investigation_turn_status_check CHECK (status IN
            ('RECEIVED','CAP_CHECKED','CLASSIFIED','PLAN_VALIDATED','DISPATCHED','GATHERED','COMPOSED',
             'DELIVERED','CLARIFIED','DENIED','FAILED')),
          UNIQUE (agent_run_id)
        );
        CREATE INDEX investigation_turn_investigation_idx ON investigation_turn (investigation_id, created_at);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="investigation_turn"))
    # `investigation_message.turn_id` is deliberately a plain indexed column, NOT a foreign key: `investigation_turn` already
    # references `investigation_message` (user_message_id/ceo_message_id), so a back-FK would make the graph cyclic and no
    # children-before-parents deletion order would exist (tenant erasure, test cleanup). The repository sets it in the same
    # transaction that creates the turn.
    op.execute("CREATE INDEX investigation_message_turn_idx ON investigation_message (turn_id) WHERE turn_id IS NOT NULL;")

    # --- investigation_finding ----------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE investigation_finding (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          investigation_id  uuid not null references investigation(id),
          turn_id           uuid not null references investigation_turn(id),
          agent_run_id      uuid references agent_run(id),
          source            text not null,
          action_key        text not null,
          status            text not null,
          figure_refs       jsonb not null default '[]',
          report_ref        jsonb,
          gap_reason        text,
          created_at        timestamptz not null default now(),
          CONSTRAINT investigation_finding_source_check
            CHECK (source IN ('CFO','PI','CI','CMO','GST_LOOKUP','BUSINESS_STATE')),
          CONSTRAINT investigation_finding_status_check
            CHECK (status IN ('COMPLETE','PARTIAL','DENIED','FAILED','UNAVAILABLE','NOT_ENTITLED')),
          CONSTRAINT investigation_finding_refs_is_array CHECK (jsonb_typeof(figure_refs) = 'array')
        );
        CREATE INDEX investigation_finding_investigation_idx ON investigation_finding (investigation_id, created_at);
        CREATE INDEX investigation_finding_turn_idx ON investigation_finding (turn_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="investigation_finding"))

    # --- investigation_agent ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE investigation_agent (
          investigation_id  uuid not null references investigation(id),
          tenant_id         uuid not null,
          agent_code        text not null,
          attached          boolean not null,
          changed_by        uuid not null,
          changed_at        timestamptz not null default now(),
          PRIMARY KEY (investigation_id, agent_code),
          CONSTRAINT investigation_agent_code_check CHECK (agent_code IN ('CFO','CI','PI','CMO'))
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="investigation_agent"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS investigation_agent;")
    op.execute("DROP TABLE IF EXISTS investigation_finding;")
    op.execute("DROP INDEX IF EXISTS investigation_message_turn_idx;")
    op.execute("DROP TABLE IF EXISTS investigation_turn;")
    op.execute(
        """
        ALTER TABLE investigation_message
          DROP CONSTRAINT IF EXISTS investigation_message_kind_check,
          DROP CONSTRAINT IF EXISTS investigation_message_role_check,
          DROP COLUMN IF EXISTS turn_id,
          DROP COLUMN IF EXISTS kind;
        ALTER TABLE agent_run
          DROP CONSTRAINT IF EXISTS agent_run_agent_id_check,
          DROP CONSTRAINT IF EXISTS agent_run_trigger_type_check;
        ALTER TABLE investigation
          DROP CONSTRAINT IF EXISTS investigation_resolved_has_note,
          DROP CONSTRAINT IF EXISTS investigation_origin_check,
          DROP CONSTRAINT IF EXISTS investigation_status_check,
          DROP COLUMN IF EXISTS resolved_at,
          DROP COLUMN IF EXISTS resolved_by,
          DROP COLUMN IF EXISTS resolution_note,
          DROP COLUMN IF EXISTS situation_id,
          DROP COLUMN IF EXISTS origin;
        """
    )
    op.execute(
        "ALTER TABLE investigation ADD CONSTRAINT investigation_summary_covers_through_fk "
        "FOREIGN KEY (summary_covers_through) REFERENCES investigation_message(id);"
    )
