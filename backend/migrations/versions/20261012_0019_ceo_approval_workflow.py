"""CEO approval workflow schema: investigation_plan, investigation_plan_event, turn route_source APPROVAL + plan_id, message kind PLAN

Spec docs/specs/ceo-approval-workflow.md section 5 / 13.6 (S2), with the "Amendment 2026-10-12" renumbering (owner decision CD9, ceo-cmo-delegation.md): this revision sits on
`20261012_0015` (the RAG foundation), which is the single head. The PLANNED turn status already exists (20261011_0016).

What the DATABASE enforces, so no code path can bypass it:
  * `investigation_plan` and `investigation_plan_event` are tenant-owned, ENABLE + FORCE ROW LEVEL SECURITY, `tenant_isolation` policy identical to the other CEO tables.
  * The app role cannot DELETE or TRUNCATE either table. The cluster's default privileges hand it full CRUD on every new table, so each is narrowed by an explicit REVOKE
    (the 0007 / 0014 / 0015 lesson): the plan keeps SELECT, INSERT and a COLUMN-level UPDATE on (status, execution_turn_id, decided_by, decided_at, decision_reason) only
    (never on plan, plan_hash, requested_by, expires_at, tenant_id, investigation_id); the event table is SELECT, INSERT only (append-only).
  * Transition completeness (Q-A10, option 1 + trigger): a BEFORE trigger makes the frozen plan and its identity immutable (even for the owner role), makes a plan start
    AWAITING_APPROVAL, and makes every terminal state final; a DEFERRED constraint trigger makes a commit that creates a plan without its CREATED event, or changes a status
    without exactly the matching event, fail. The one transactional repository function (`investigation_plan_repo`) is how the application does it; this is the backstop.
  * `investigation_plan_event` references the plan through a COMPOSITE (tenant_id, plan_id) FK, because a foreign key is checked with owner privileges and would otherwise
    accept another tenant's plan id.
  * `investigation_turn.plan_id` is a plain indexed column, NOT a foreign key: the plan already references turns (planned_turn_id, execution_turn_id), so a back-FK would make the
    graph cyclic and no children-before-parents deletion order would exist (tenant erasure, test cleanup). The repository sets it in the transaction that creates the turn.

The downgrade REFUSES (it does not silently destroy history) while any plan row, APPROVAL turn or PLAN message exists; on an empty database (CI's `downgrade base`) it is a clean
reversal.

Revision ID: 20261012_0019
Revises: 20261012_0015
Create Date: 2026-10-12
"""
from __future__ import annotations

from alembic import op

revision = "20261012_0019"
down_revision = "20261012_0015"
branch_labels = None
depends_on = None

_TENANT = "tenant_id = current_setting('app.current_tenant_id', true)::uuid"
_EVENTS = ("CREATED", "APPROVAL_REFUSED", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED", "EXECUTION_STARTED", "EXECUTION_FINISHED", "EXECUTION_FAILED",
           "EXECUTION_NOT_STARTED", "OUTCOME_UNKNOWN")
_STATUSES = ("AWAITING_APPROVAL", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


def _rls(table: str) -> str:
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE  ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON {table}
          USING      ({_TENANT})
          WITH CHECK ({_TENANT});
    """


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE investigation_plan (
          id                uuid primary key default gen_random_uuid(),
          tenant_id         uuid not null,
          investigation_id  uuid not null references investigation(id),
          planned_turn_id   uuid not null references investigation_turn(id),
          execution_turn_id uuid references investigation_turn(id),
          plan              jsonb not null,
          plan_hash         text not null,
          status            text not null,
          requested_by      uuid not null references app_user(id),
          created_at        timestamptz not null default now(),
          expires_at        timestamptz not null,
          decided_by        uuid,
          decided_at        timestamptz,
          decision_reason   text,
          CONSTRAINT investigation_plan_status_check CHECK (status IN {_in(_STATUSES)}),
          CONSTRAINT investigation_plan_expiry_check CHECK (expires_at > created_at),
          CONSTRAINT investigation_plan_hash_check CHECK (plan_hash ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT investigation_plan_reason_check CHECK (decision_reason IS NULL OR char_length(decision_reason) <= 200),
          CONSTRAINT investigation_plan_plan_is_object CHECK (jsonb_typeof(plan) = 'object'),
          CONSTRAINT investigation_plan_approved_check CHECK (status <> 'APPROVED' OR (execution_turn_id IS NOT NULL AND decided_by IS NOT NULL AND decided_at IS NOT NULL)),
          CONSTRAINT investigation_plan_declined_check CHECK (status <> 'DECLINED' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
          CONSTRAINT investigation_plan_planned_turn_unique UNIQUE (planned_turn_id),
          CONSTRAINT investigation_plan_tenant_id_unique UNIQUE (tenant_id, id)
        );
        CREATE UNIQUE INDEX investigation_plan_one_open ON investigation_plan (tenant_id, investigation_id) WHERE status = 'AWAITING_APPROVAL';
        CREATE INDEX investigation_plan_investigation_idx ON investigation_plan (investigation_id, created_at);
        CREATE INDEX investigation_plan_execution_turn_idx ON investigation_plan (execution_turn_id) WHERE execution_turn_id IS NOT NULL;
        """
    )
    op.execute(_rls("investigation_plan"))
    op.execute(
        """
        REVOKE ALL ON investigation_plan FROM metrion_app;
        GRANT SELECT, INSERT ON investigation_plan TO metrion_app;
        GRANT UPDATE (status, execution_turn_id, decided_by, decided_at, decision_reason) ON investigation_plan TO metrion_app;
        """
    )

    op.execute(
        f"""
        CREATE TABLE investigation_plan_event (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid not null,
          plan_id        uuid not null,
          event          text not null,
          from_status    text,
          to_status      text,
          actor_user_id  uuid,
          actor_kind     text not null,
          occurred_at    timestamptz not null default now(),
          plan_hash      text not null,
          reason_code    text,
          metadata       jsonb,
          CONSTRAINT investigation_plan_event_plan_fk FOREIGN KEY (tenant_id, plan_id) REFERENCES investigation_plan (tenant_id, id),
          CONSTRAINT investigation_plan_event_event_check CHECK (event IN {_in(_EVENTS)}),
          CONSTRAINT investigation_plan_event_from_check CHECK (from_status IS NULL OR from_status IN {_in(_STATUSES)}),
          CONSTRAINT investigation_plan_event_to_check CHECK (to_status IS NULL OR to_status IN {_in(_STATUSES)}),
          CONSTRAINT investigation_plan_event_actor_check CHECK (actor_kind IN ('USER', 'SYSTEM') AND ((actor_kind = 'USER') = (actor_user_id IS NOT NULL))),
          CONSTRAINT investigation_plan_event_shape_check CHECK (
               (event = 'CREATED' AND from_status IS NULL AND to_status = 'AWAITING_APPROVAL')
            OR (event IN ('APPROVED', 'DECLINED', 'EXPIRED', 'SUPERSEDED') AND from_status = 'AWAITING_APPROVAL' AND to_status = event)
            OR (event NOT IN ('CREATED', 'APPROVED', 'DECLINED', 'EXPIRED', 'SUPERSEDED') AND from_status IS NULL AND to_status IS NULL)
          )
        );
        CREATE INDEX investigation_plan_event_plan_idx ON investigation_plan_event (tenant_id, plan_id, occurred_at, id);
        """
    )
    op.execute(_rls("investigation_plan_event"))
    op.execute(
        """
        REVOKE ALL ON investigation_plan_event FROM metrion_app;
        GRANT SELECT, INSERT ON investigation_plan_event TO metrion_app;
        """
    )

    # ---------------------------------------------------------------- transition guards (Q-A10: repository function + trigger)
    op.execute(
        """
        CREATE FUNCTION investigation_plan_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.status <> 'AWAITING_APPROVAL' OR NEW.execution_turn_id IS NOT NULL OR NEW.decided_by IS NOT NULL OR NEW.decided_at IS NOT NULL OR NEW.decision_reason IS NOT NULL THEN
              RAISE EXCEPTION 'investigation_plan: a plan is created AWAITING_APPROVAL and undecided' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.id <> OLD.id OR NEW.tenant_id <> OLD.tenant_id OR NEW.investigation_id <> OLD.investigation_id OR NEW.planned_turn_id <> OLD.planned_turn_id
             OR NEW.plan IS DISTINCT FROM OLD.plan OR NEW.plan_hash <> OLD.plan_hash OR NEW.requested_by <> OLD.requested_by
             OR NEW.created_at <> OLD.created_at OR NEW.expires_at <> OLD.expires_at THEN
            RAISE EXCEPTION 'investigation_plan: the frozen plan and its identity are immutable' USING ERRCODE = '23514';
          END IF;
          IF OLD.status <> 'AWAITING_APPROVAL' THEN
            RAISE EXCEPTION 'investigation_plan: % is a terminal status', OLD.status USING ERRCODE = '23514';
          END IF;
          IF NEW.status = OLD.status THEN
            RAISE EXCEPTION 'investigation_plan: an update must change the status' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER investigation_plan_guard BEFORE INSERT OR UPDATE ON investigation_plan
          FOR EACH ROW EXECUTE FUNCTION investigation_plan_guard();

        CREATE FUNCTION investigation_plan_requires_event() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NOT EXISTS (SELECT 1 FROM investigation_plan_event e WHERE e.tenant_id = NEW.tenant_id AND e.plan_id = NEW.id AND e.event = 'CREATED') THEN
              RAISE EXCEPTION 'investigation_plan: a plan needs its CREATED event in the same transaction' USING ERRCODE = '23514';
            END IF;
          ELSE
            IF NOT EXISTS (SELECT 1 FROM investigation_plan_event e WHERE e.tenant_id = NEW.tenant_id AND e.plan_id = NEW.id AND e.from_status = OLD.status AND e.to_status = NEW.status) THEN
              RAISE EXCEPTION 'investigation_plan: a status change needs its matching event in the same transaction' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NULL;
        END
        $fn$;
        CREATE CONSTRAINT TRIGGER investigation_plan_event_required_insert AFTER INSERT ON investigation_plan
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION investigation_plan_requires_event();
        CREATE CONSTRAINT TRIGGER investigation_plan_event_required_update AFTER UPDATE OF status ON investigation_plan
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION investigation_plan_requires_event();
        """
    )

    # ---------------------------------------------------------------- existing tables
    op.execute(
        """
        ALTER TABLE investigation_turn ADD COLUMN plan_id uuid;
        CREATE INDEX investigation_turn_plan_idx ON investigation_turn (plan_id) WHERE plan_id IS NOT NULL;
        ALTER TABLE investigation_turn DROP CONSTRAINT investigation_turn_route_source_check;
        ALTER TABLE investigation_turn ADD CONSTRAINT investigation_turn_route_source_check CHECK (route_source IN ('CLASSIFIER','UI_ACTION','APPROVAL'));
        ALTER TABLE investigation_message DROP CONSTRAINT investigation_message_kind_check;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_kind_check
          CHECK (kind IN ('TEXT','CLARIFICATION','ANSWER','BRIEFING','SYSTEM_NOTE','PLAN'));
        """
    )


def _refuse_if_rows_exist() -> None:
    """The tables are FORCE ROW LEVEL SECURITY, so a plain EXISTS from the migration role sees nothing: check each tenant under its own tenant context on a SEPARATE
    connection (closed afterwards). The tenant setting is never touched inside the migration's own transaction (`downgrade base` runs many downgrades in one)."""
    from sqlalchemy import text

    checks = (
        ("investigation_plan", "SELECT 1 FROM investigation_plan LIMIT 1"),
        ("an APPROVAL turn", "SELECT 1 FROM investigation_turn WHERE route_source = 'APPROVAL' OR plan_id IS NOT NULL LIMIT 1"),
        ("a PLAN message", "SELECT 1 FROM investigation_message WHERE kind = 'PLAN' LIMIT 1"),
    )
    # The probe runs on the migration's own connection, inside a savepoint that is ALWAYS rolled back, so the transaction-local tenant setting never survives it. A second
    # connection would block on locks that later downgrades of the same `downgrade base` transaction already hold (it hung on `tenant`).
    conn = op.get_bind()
    probe = conn.begin_nested()
    try:
        for (tenant_id,) in conn.execute(text("SELECT id FROM tenant")).all():
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant_id)})
            for what, sql in checks:
                if conn.execute(text(sql)).first() is not None:
                    raise RuntimeError(f"cannot downgrade 20261012_0019: {what} rows exist (approval history is never destroyed silently)")
    finally:
        probe.rollback()


def downgrade() -> None:
    _refuse_if_rows_exist()
    op.execute(
        """
        ALTER TABLE investigation_message DROP CONSTRAINT investigation_message_kind_check;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_kind_check
          CHECK (kind IN ('TEXT','CLARIFICATION','ANSWER','BRIEFING','SYSTEM_NOTE'));
        ALTER TABLE investigation_turn DROP CONSTRAINT investigation_turn_route_source_check;
        ALTER TABLE investigation_turn ADD CONSTRAINT investigation_turn_route_source_check CHECK (route_source IN ('CLASSIFIER','UI_ACTION'));
        DROP INDEX IF EXISTS investigation_turn_plan_idx;
        ALTER TABLE investigation_turn DROP COLUMN IF EXISTS plan_id;
        DROP TABLE IF EXISTS investigation_plan_event;
        DROP TABLE IF EXISTS investigation_plan;
        DROP FUNCTION IF EXISTS investigation_plan_requires_event();
        DROP FUNCTION IF EXISTS investigation_plan_guard();
        """
    )
