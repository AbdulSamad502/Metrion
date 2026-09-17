"""engine-owned tables: formula_definition, metric_result, manual_adjustment,
discount_bearer_config, gst_slab_reference, fee_reference

deterministic-engine.md §9, §5.3, §7.1, §8.2.1, §5.14. auth.md §7.3 for the RLS pattern.
This package never creates DDL for data-foundation-owned tables (sales_line, line_component,
settlement_line) — it only reads them, via canonical_repo.py.

Revision ID: 20260917_0001
Revises:
Create Date: 2026-09-17
"""
from __future__ import annotations

from alembic import op

revision = "20260917_0001"
down_revision = None
branch_labels = None
depends_on = None

# auth.md §7.3: FORCE ROW LEVEL SECURITY, SET LOCAL app.current_tenant_id, fail-closed via
# current_setting(..., true) returning NULL -> zero rows when context is unset. Applied
# identically to every tenant-owned table created here.
_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- formula_definition (§4.1, F1-F6) -----------------------------------------------
    # Platform-owned (no tenant_id): a formula's structure is not tenant data.
    op.execute(
        """
        CREATE TABLE formula_definition (
          id                   uuid primary key default gen_random_uuid(),
          metric_code          text not null,
          formula_version      text not null,
          definition           jsonb not null,     -- the node tree (definitions/schema.py)
          effective_from       date not null,
          created_at           timestamptz not null default now(),
          unique (metric_code, formula_version)
        );
        """
    )
    op.execute("GRANT SELECT ON formula_definition TO metrion_app;")

    # --- metric_result (§9) -------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE metric_result (
          id                     uuid primary key default gen_random_uuid(),
          tenant_id              uuid not null,
          metric_code            text not null,
          grain                  text not null,        -- LINE | ORDER | SKU | MARKETPLACE | ACCOUNT
          target_ref             text not null,
          period                 text,
          value_paise            bigint,                -- null only when is_available = false
          recognition_state      text not null,         -- RECOGNISED | REALIZED | UNAVAILABLE
          confidence             text not null,         -- VERIFIED | PROVISIONAL | DERIVED | MANUAL
          calculation_basis      text not null,
          formula_definition_id  uuid references formula_definition(id),
          formula_version        text not null,
          config_version         text not null,
          canonical_data_version text not null,
          manual_adjustment_set  jsonb not null default '[]'::jsonb,
          as_of_date             date,
          input_refs             jsonb not null default '[]'::jsonb,
          exclusions             jsonb not null default '[]'::jsonb,
          is_trial               boolean not null default false,
          is_available           boolean not null default true,
          unavailable_reason     text,
          computed_at            timestamptz not null
        );
        CREATE INDEX metric_result_tenant_target_idx
          ON metric_result (tenant_id, metric_code, target_ref, computed_at desc);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="metric_result"))

    # --- manual_adjustment (§7.1) — append-only: UPDATE is revoked at the grant level, not
    # just enforced in application logic (a correction is a new row with supersedes_id set).
    op.execute(
        """
        CREATE TABLE manual_adjustment (
          id             uuid primary key default gen_random_uuid(),
          tenant_id      uuid not null,
          target_type    text not null,     -- LINE | ORDER | SKU | PERIOD | ACCOUNT | SUPPLIER | SETTLEMENT
          target_ref     text not null,
          field          text not null,     -- §7.2.1 field registry — this migration does not
                                             -- enumerate it; the engine's field registry is
                                             -- the sole authority, not a DB CHECK constraint
          value          jsonb not null,
          reason         text,
          created_by     uuid not null,
          created_at     timestamptz not null default now(),
          supersedes_id  uuid references manual_adjustment(id),
          status         text not null default 'ACTIVE'   -- ACTIVE | SUPERSEDED | WITHDRAWN
        );
        CREATE INDEX manual_adjustment_tenant_target_idx
          ON manual_adjustment (tenant_id, target_type, target_ref, field, status);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="manual_adjustment"))
    op.execute("REVOKE UPDATE, DELETE ON manual_adjustment FROM metrion_app;")

    # --- discount_bearer_config (§5.3) --------------------------------------------------
    # tenant_id is nullable: NULL = platform default, resolved before any tenant-specific
    # override (§5.3 "Resolution order"). RLS still applies — a NULL tenant_id row is a
    # platform default visible to every tenant, which the policy predicate below allows by
    # matching NULL rows regardless of the session's current_tenant_id.
    op.execute(
        """
        CREATE TABLE discount_bearer_config (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid,                     -- null = platform default
          marketplace     text not null,
          component_code  text not null,
          bearer          text not null,            -- SELLER | MARKETPLACE | UNKNOWN
          source          text not null,
          confidence      text not null,
          effective_from  date not null,
          version         int not null,
          unique (tenant_id, marketplace, component_code, effective_from)
        );
        ALTER TABLE discount_bearer_config ENABLE ROW LEVEL SECURITY;
        ALTER TABLE discount_bearer_config FORCE ROW LEVEL SECURITY;

        CREATE POLICY tenant_isolation ON discount_bearer_config
          USING (
            tenant_id IS NULL
            OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
          )
          WITH CHECK (
            tenant_id IS NULL
            OR tenant_id = current_setting('app.current_tenant_id', true)::uuid
          );

        GRANT SELECT, INSERT, UPDATE, DELETE ON discount_bearer_config TO metrion_app;
        """
    )

    # --- gst_slab_reference (§8.2.1, U7) — platform-owned, read-only to metrion_app -----
    op.execute(
        """
        CREATE TABLE gst_slab_reference (
          id              uuid primary key default gen_random_uuid(),
          rate_pct        numeric(7,4) not null,
          label           text not null,
          source_url      text not null,
          source_title    text,
          retrieved_at    timestamptz not null,
          effective_from  date not null,
          effective_to    date,
          version         int not null,
          confidence      text not null default 'PROVISIONAL'
        );
        """
    )
    op.execute("GRANT SELECT ON gst_slab_reference TO metrion_app;")

    # --- fee_reference (§5.14) — schema only, seeding deferred (U8, plan §J) -----------
    op.execute(
        """
        CREATE TABLE fee_reference (
          id                 uuid primary key default gen_random_uuid(),
          marketplace        text not null,
          category           text not null,
          fee_type           text not null,
          rate_pct           numeric(7,4),
          rate_low_pct       numeric(7,4),
          rate_high_pct      numeric(7,4),
          effective_from     date not null,
          effective_to       date,
          source             text not null,
          confidence         text not null,
          version            int not null,
          last_verified_at   timestamptz not null
        );
        """
    )
    op.execute("GRANT SELECT ON fee_reference TO metrion_app;")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fee_reference;")
    op.execute("DROP TABLE IF EXISTS gst_slab_reference;")
    op.execute("DROP TABLE IF EXISTS discount_bearer_config;")
    op.execute("DROP TABLE IF EXISTS manual_adjustment;")
    op.execute("DROP TABLE IF EXISTS metric_result;")
    op.execute("DROP TABLE IF EXISTS formula_definition;")
