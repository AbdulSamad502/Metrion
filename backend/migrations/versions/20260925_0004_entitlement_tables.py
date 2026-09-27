"""entitlement tables: plan, tenant_plan, tenant_cart_item, metered_event_meter_map,
metered_event, entitlement_cap_config, member_entitlement_allocation,
capability_entitlement_rule

docs/specs/entitlement.md §5 (data model — every column/constraint copied verbatim from the
spec's own SQL blocks) and §7 (RLS: rule 1 assigns real-per-tenant FORCE RLS to
`tenant_plan`/`tenant_cart_item`/`metered_event`/`member_entitlement_allocation`, and the
nullable-platform-default predicate — identical to `reconciliation_tolerance_config`'s — to
`metered_event_meter_map`/`entitlement_cap_config`/`capability_entitlement_rule`).

`plan` is the one exception: §5.1's own DDL block gives it no `tenant_id` column at all
("platform-owned, no tenant_id — mirrors fee_reference"), which is the same posture
`fee_reference`/`gst_slab_reference`/`formula_definition` already ship in
`packages/calc-engine` (read-only to `metrion_app`, no RLS policy at all — RLS on a table
with no `tenant_id` column would have no predicate to evaluate). This is a literal, minor
inconsistency against §7's own prose, which lists `plan` alongside the three
nullable-`tenant_id` config tables; the §5.1 DDL block is followed here since the task
instructs copying that block's columns exactly ("do not add, rename, or omit anything") and
the DDL is the more specific, physically-binding artifact. Flagged, not silently resolved.

No row is seeded by this migration (DDL only) — zero data, exactly matching `fee_reference`'s
own precedent.

Revision ID: 20260925_0004
Revises: 20260917_0003
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

revision = "20260925_0004"
down_revision = "20260917_0003"
branch_labels = None
depends_on = None

# Real-per-tenant FORCE RLS — auth.md §7.3, identical to every other tenant-owned table in
# this codebase (backend/migrations/versions/20260917_0001_auth_tables.py's own template).
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""

# Nullable-tenant_id platform-default RLS — identical predicate to
# reconciliation_tolerance_config (packages/calc-engine/migrations/versions/
# 20260917_0002_reconciliation_config.py), entitlement.md §7 rule 1.
_PLATFORM_DEFAULT_POLICY_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING (
    tenant_id IS NULL
    OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
  )
  WITH CHECK (
    tenant_id IS NULL
    OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- plan (§5.1) — platform-owned, no tenant_id column, no RLS, mirrors fee_reference --
    op.execute(
        """
        CREATE TABLE plan (
          id          uuid primary key default gen_random_uuid(),
          code        text unique not null,
          name        text not null,
          status      text not null,
          created_at  timestamptz not null
        );
        """
    )
    op.execute("GRANT SELECT ON plan TO metrion_app;")

    # --- tenant_plan (§5.1) ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE tenant_plan (
          id          uuid primary key default gen_random_uuid(),
          tenant_id   uuid not null references tenant(id),
          plan_id     uuid not null references plan(id),
          status      text not null,
          started_at  timestamptz not null,
          ended_at    timestamptz,
          source      text not null
        );
        -- at most one ACTIVE-or-TRIAL row per tenant (§5.1):
        CREATE UNIQUE INDEX tenant_plan_one_active_idx ON tenant_plan (tenant_id)
          WHERE status IN ('ACTIVE', 'TRIAL');
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="tenant_plan"))

    # --- tenant_cart_item (§5.1) — the "agent cart" -------------------------------------------
    op.execute(
        """
        CREATE TABLE tenant_cart_item (
          id            uuid primary key default gen_random_uuid(),
          tenant_id     uuid not null references tenant(id),
          agent_code    text not null,
          tier          text not null,
          status        text not null,
          started_at    timestamptz not null,
          ended_at      timestamptz,
          source        text not null
        );
        -- unique (tenant_id, agent_code) partial: where status = 'ACTIVE' (§5.1):
        CREATE UNIQUE INDEX tenant_cart_item_one_active_idx ON tenant_cart_item (tenant_id, agent_code)
          WHERE status = 'ACTIVE';
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="tenant_cart_item"))

    # --- metered_event_meter_map (§5.2.1) — the CI-Q15-safe indirection ----------------------
    op.execute(
        """
        CREATE TABLE metered_event_meter_map (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid,
          event_kind     text not null,
          meter_code     text not null,
          effective_from date not null,
          version        int not null,
          unique (tenant_id, event_kind, effective_from)
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="metered_event_meter_map"))

    # --- metered_event (§5.2) -----------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE metered_event (
          id                 uuid primary key default gen_random_uuid(),
          tenant_id          uuid not null references tenant(id),
          member_id          uuid references app_user(id),
          agent_code         text not null,
          event_kind         text not null,
          meter_code         text not null,
          quantity           int not null default 1,
          agent_run_id       uuid references agent_run(id),
          source_ref         uuid,
          idempotency_key    text not null,
          occurred_at        timestamptz not null,
          period_key         text not null,
          unique (tenant_id, idempotency_key)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="metered_event"))

    # --- entitlement_cap_config (§5.3) — deny-threshold/run-credit config --------------------
    op.execute(
        """
        CREATE TABLE entitlement_cap_config (
          id                  uuid primary key default gen_random_uuid(),
          tenant_id           uuid,
          agent_code          text not null,
          meter_code          text not null,
          scope               text not null,
          period_unit         text not null,
          cap_value           bigint,
          saved_resource_cap  bigint,
          effective_from      date not null,
          version             int not null,
          unique (tenant_id, agent_code, meter_code, scope, effective_from)
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="entitlement_cap_config"))

    # --- member_entitlement_allocation (§5.3) — exercised only when scope = MEMBER, unused V1
    op.execute(
        """
        CREATE TABLE member_entitlement_allocation (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid not null references tenant(id),
          member_id       uuid not null references app_user(id),
          agent_code      text not null,
          meter_code      text not null,
          allocated_value bigint,
          period_unit     text not null,
          effective_from  date not null,
          unique (tenant_id, member_id, agent_code, meter_code, effective_from)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="member_entitlement_allocation"))

    # --- capability_entitlement_rule (§5.4) — the Q13 denial-rendering mechanism -------------
    op.execute(
        """
        CREATE TABLE capability_entitlement_rule (
          id                          uuid primary key default gen_random_uuid(),
          tenant_id                   uuid,
          agent_code                  text not null,
          direct_action_code          text not null,
          denial_rendering            text not null default 'ERROR',
          reduced_payload_action_code text,
          effective_from               date not null,
          version                      int not null,
          unique (tenant_id, agent_code, direct_action_code, effective_from)
        );
        """
    )
    op.execute(_PLATFORM_DEFAULT_POLICY_SQL.format(table="capability_entitlement_rule"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS capability_entitlement_rule;")
    op.execute("DROP TABLE IF EXISTS member_entitlement_allocation;")
    op.execute("DROP TABLE IF EXISTS entitlement_cap_config;")
    op.execute("DROP TABLE IF EXISTS metered_event;")
    op.execute("DROP TABLE IF EXISTS metered_event_meter_map;")
    op.execute("DROP TABLE IF EXISTS tenant_cart_item;")
    op.execute("DROP TABLE IF EXISTS tenant_plan;")
    op.execute("DROP TABLE IF EXISTS plan;")
