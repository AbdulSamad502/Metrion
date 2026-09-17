"""whatsapp tables: whatsapp_template, whatsapp_message, whatsapp_pending_action,
whatsapp_alert_subscription

whatsapp-integration.md §5 (Data model). `whatsapp_template` carries no `tenant_id` — it is Metrion's
own Meta-approved template registry, shared across all tenants, not tenant-owned data, so it
gets no RLS policy, matching the same reasoning applied to `tenant`/`app_user` in
20260917_0001.

Revision ID: 20260917_0003
Revises: 20260917_0002
Create Date: 2026-09-17
"""
from __future__ import annotations

from alembic import op

revision = "20260917_0003"
down_revision = "20260917_0002"
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
    # --- whatsapp_template — shared registry, no tenant_id, no RLS ------------------------
    op.execute(
        """
        CREATE TABLE whatsapp_template (
          id               uuid primary key default gen_random_uuid(),
          name             text not null,
          category         text not null,          -- UTILITY | MARKETING (Meta's classification)
          approval_status  text not null,          -- PENDING | APPROVED | REJECTED
          version          int not null,
          body_text        text not null,
          variable_count   int not null,
          approved_at      timestamptz
        );
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_template TO metrion_app;")

    # --- whatsapp_message --------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE whatsapp_message (
          id                          uuid primary key default gen_random_uuid(),
          tenant_id                   uuid not null,
          whatsapp_binding_id         uuid not null references whatsapp_binding(id),
          direction                   text not null,      -- OUTBOUND_TEMPLATE | OUTBOUND_SESSION | INBOUND
          template_id                 uuid references whatsapp_template(id),   -- set only for OUTBOUND_TEMPLATE
          agent_run_id                uuid references agent_run(id),            -- the agent_run this alert renders (C4)
          variables                   jsonb,
          body_rendered               text,
          provider_message_id         text,
          status                      text not null,      -- QUEUED | SENT | DELIVERED | READ | FAILED
          session_window_expires_at   timestamptz,          -- null until a seller reply opens one
          created_at                  timestamptz not null default now()
        );
        CREATE INDEX whatsapp_message_binding_idx ON whatsapp_message (whatsapp_binding_id, created_at);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="whatsapp_message"))

    # --- whatsapp_pending_action (the object "invoke/revoke" (C3) actually acts on) --------
    op.execute(
        """
        CREATE TABLE whatsapp_pending_action (
          id                    uuid primary key default gen_random_uuid(),
          tenant_id             uuid not null,
          whatsapp_message_id   uuid not null references whatsapp_message(id),
          action_ref            text not null,       -- e.g. "ci.capture_run:<id>", "cfo.preview:<id>"
          status                text not null,        -- PENDING | CONFIRMED | DECLINED | EXPIRED
          expires_at            timestamptz not null
        );
        CREATE INDEX whatsapp_pending_action_message_idx ON whatsapp_pending_action (whatsapp_message_id);
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="whatsapp_pending_action"))

    # --- whatsapp_alert_subscription (per-type mute) ---------------------------------------
    op.execute(
        """
        CREATE TABLE whatsapp_alert_subscription (
          tenant_id   uuid not null,
          alert_type  text not null,                -- MARGIN_RISK | PRICE_CHANGE | OPPORTUNITY
          enabled     boolean not null default true,
          primary key (tenant_id, alert_type)
        );
        """
    )
    op.execute(_TENANT_RLS_SQL.format(table="whatsapp_alert_subscription"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS whatsapp_alert_subscription;")
    op.execute("DROP TABLE IF EXISTS whatsapp_pending_action;")
    op.execute("DROP TABLE IF EXISTS whatsapp_message;")
    op.execute("DROP TABLE IF EXISTS whatsapp_template;")
