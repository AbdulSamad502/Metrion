"""cmo_quota_reservation - serialised quota protection for capped CMO meters.

docs/specs/entitlement.md E2/Q5 (amended 2026-10-04) and docs/specs/slim-cmo-agent.md §8.4.

A plain check-then-record cap lets concurrent requests all pass (independent verification measured
7 of 8 passing a cap of 1). CMO therefore RESERVES the units a request needs, inside one short
transaction serialised by `pg_advisory_xact_lock` on (tenant, agent, meter, period), before any model
call. Reservations are QUOTA PROTECTION ONLY - never a billing record: billing remains the
persisted terminal artefact status plus idempotent `metered_event` rows (entitlement.md rules 3-4).

* `state`: RESERVED (counts against the cap until `expires_at`) -> SETTLED (the metered events were
  written) | RELEASED (nothing delivered, an error, or the reservation expired).
* One ACTIVE reservation per (tenant, agent, meter, request_key): a concurrent identical request is
  "in progress", not a second reservation. A partial unique index scopes it to RESERVED rows.
* The application role may INSERT and UPDATE state but never DELETE.
* No row is seeded; the TTL is configuration (`CMO_QUOTA_RESERVATION_TTL_SECONDS`), not a column default.

Revision ID: 20261004_0005
Revises: 20260925_0004
Create Date: 2026-10-04
"""
from __future__ import annotations

from alembic import op

revision = "20261004_0005"
down_revision = "20260925_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cmo_quota_reservation (
          id          uuid primary key default gen_random_uuid(),
          tenant_id   uuid not null,
          agent_code  text not null check (length(btrim(agent_code)) > 0),
          meter_code  text not null check (length(btrim(meter_code)) > 0),
          period_key  text not null check (length(btrim(period_key)) > 0),
          units       int  not null check (units > 0),
          request_key text not null check (length(btrim(request_key)) > 0),
          state       text not null check (state IN ('RESERVED','SETTLED','RELEASED')),
          created_at  timestamptz not null default now(),
          expires_at  timestamptz not null,
          settled_at  timestamptz,
          check (state = 'RESERVED' OR settled_at IS NOT NULL)
        );
        CREATE UNIQUE INDEX cmo_quota_reservation_active_key_idx
          ON cmo_quota_reservation (tenant_id, agent_code, meter_code, request_key) WHERE state = 'RESERVED';
        CREATE INDEX cmo_quota_reservation_scope_idx
          ON cmo_quota_reservation (tenant_id, agent_code, meter_code, period_key, state);

        ALTER TABLE cmo_quota_reservation ENABLE ROW LEVEL SECURITY;
        ALTER TABLE cmo_quota_reservation FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON cmo_quota_reservation
          USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

        REVOKE ALL ON cmo_quota_reservation FROM metrion_app;
        GRANT SELECT, INSERT, UPDATE ON cmo_quota_reservation TO metrion_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cmo_quota_reservation;")
