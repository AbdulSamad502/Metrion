"""auth tables: tenant, app_user, membership, whatsapp_binding, auth_audit

auth.md §5.1. `tenant` and `app_user` carry no `tenant_id` column and get no RLS policy —
they are the identity roots themselves, not tenant-owned data (a request resolves `tenant_id`
*from* `app_user`+`membership`, so RLS on those two tables would be circular). Every other
table here carries `tenant_id` and gets the standard tenant_isolation policy per §7.3.

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

_TENANT_RLS_SQL = """
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON {table}
  USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO metrion_app;
"""


def upgrade() -> None:
    # --- tenant (§5.1) — identity root, no tenant_id column, no RLS -----------------------
    op.execute(
        """
        CREATE TABLE tenant (
          id             uuid primary key default gen_random_uuid(),
          clerk_org_id   text unique not null,
          business_name  text not null,
          country        char(2) not null default 'IN',
          currency       char(3) not null default 'INR',
          timezone       text not null default 'Asia/Kolkata',
          status         text not null,            -- ACTIVE | SUSPENDED | DELETED
          created_at     timestamptz not null default now()
        );
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant TO metrion_app;")

    # --- app_user (§5.1) — identity root, no tenant_id column, no RLS ---------------------
    op.execute(
        """
        CREATE TABLE app_user (
          id              uuid primary key default gen_random_uuid(),
          clerk_user_id   text unique not null,
          email           text not null,
          email_verified  boolean not null default false,   -- I5
          auth_provider   text not null,           -- GOOGLE | EMAIL_PASSWORD
          display_name    text,
          created_at      timestamptz not null default now()
        );
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON app_user TO metrion_app;")

    # --- membership (§5.1) -----------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE membership (
          id           uuid primary key default gen_random_uuid(),
          tenant_id    uuid not null references tenant(id),
          app_user_id  uuid not null references app_user(id),
          role         text not null,              -- OWNER | PARTNER
          status       text not null,               -- INVITED | ACTIVE | SUSPENDED | REMOVED
          permissions  jsonb not null,               -- D4: empty object = deny-all
          invited_by   uuid references app_user(id),
          joined_at    timestamptz,
          unique (tenant_id, app_user_id)
        );
        -- Exactly one active owner per tenant (E20):
        CREATE UNIQUE INDEX membership_one_active_owner_idx ON membership (tenant_id)
          WHERE role = 'OWNER' AND status = 'ACTIVE';
        CREATE INDEX membership_app_user_idx ON membership (app_user_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="membership"))

    # --- whatsapp_binding (§5.1, §7.5) ------------------------------------------------------
    op.execute(
        """
        CREATE TABLE whatsapp_binding (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null references tenant(id),
          provider_account_id   text not null,       -- A5: stable provider identifier
          phone_e164            text not null,
          verification_status   text not null,        -- PENDING | VERIFIED | DISCONNECTED
          verified_at           timestamptz,
          enabled               boolean not null default false,   -- W10, owner-controlled
          bound_by              uuid not null references app_user(id),
          created_at            timestamptz not null default now()
        );
        -- W1: one verified binding per tenant
        CREATE UNIQUE INDEX whatsapp_binding_one_verified_per_tenant_idx ON whatsapp_binding (tenant_id)
          WHERE verification_status = 'VERIFIED';
        -- W7: a destination cannot be claimed twice
        CREATE UNIQUE INDEX whatsapp_binding_provider_account_verified_idx ON whatsapp_binding (provider_account_id)
          WHERE verification_status = 'VERIFIED';
        CREATE UNIQUE INDEX whatsapp_binding_phone_verified_idx ON whatsapp_binding (phone_e164)
          WHERE verification_status = 'VERIFIED';
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="whatsapp_binding"))

    # --- auth_audit (§5.1, §7.6) — shorthand in spec, typed here per sibling conventions ---
    op.execute(
        """
        CREATE TABLE auth_audit (
          id              uuid primary key default gen_random_uuid(),
          tenant_id       uuid not null references tenant(id),
          actor_user_id   uuid references app_user(id),
          event           text not null,
          subject         text,
          metadata        jsonb,
          occurred_at     timestamptz not null default now()
        );
        CREATE INDEX auth_audit_tenant_occurred_idx ON auth_audit (tenant_id, occurred_at);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="auth_audit"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_audit;")
    op.execute("DROP TABLE IF EXISTS whatsapp_binding;")
    op.execute("DROP TABLE IF EXISTS membership;")
    op.execute("DROP TABLE IF EXISTS app_user;")
    op.execute("DROP TABLE IF EXISTS tenant;")
