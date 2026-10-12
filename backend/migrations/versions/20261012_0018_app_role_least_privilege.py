"""least privilege for the application role on reference, billing-configuration, audit and ledger tables

Stage 3 finding (docs/planning/stages-3-4-5-report-2026-10-12.md): `docker/postgres-init/02-roles.sql` hands `metrion_app` full INSERT/UPDATE/DELETE on every table through
default privileges, so a bug (or an injection) in the application could rewrite platform reference data (fees, formulas, GST rates, plans), change a tenant's entitlement caps,
or alter and delete the audit trail and the billing ledger. Application code never does any of that: it was verified table by table (a scan of every `INSERT INTO` /
`UPDATE` / `DELETE FROM` in `backend/src` and `packages/*/src` against the live grants), and these writes happen only through administration/migrations (the owner role).

REVOKED from `metrion_app` (SELECT stays everywhere, so every read path is unchanged):
  * INSERT, UPDATE, DELETE on platform reference data and plan/entitlement/threshold configuration that the application only reads:
      fee_reference, formula_definition, hsn_gst_reference, gst_slab_reference, plan, whatsapp_template, tenant_plan, member_entitlement_allocation,
      entitlement_cap_config, capability_entitlement_rule, metered_event_meter_map, anomaly_detection_config, discount_bearer_config, financial_health_config,
      reconciliation_tolerance_config, severity_config, ci_tenant_config, tenant_cart_item
      and the WhatsApp tables, whose feature has no code yet (whatsapp_alert_subscription, whatsapp_binding, whatsapp_message, whatsapp_pending_action; the migration that
      builds the feature re-grants what it needs).
  * UPDATE, DELETE on the audit trail and the billing ledger, which the application only appends to: auth_audit, metered_event.

NOT changed (a runtime need was found, or the question is a product decision): everything else, including `tenant` / `app_user` / `membership` (written by onboarding and
webhooks) and the insert-only evidence tables, whose UPDATE/DELETE grants stay pinned by tests/integration/test_privilege_boundary.py's KNOWN_APP_DELETABLE list.

Downgrade restores the exact earlier grants. Every statement is guarded by `to_regclass`, so the migration is safe on a database where a table does not exist.

Revision ID: 20261012_0018
Revises: 20261011_0017
Create Date: 2026-10-12
"""
from __future__ import annotations

from alembic import op

revision = "20261012_0018"
down_revision = "20261011_0017"
branch_labels = None
depends_on = None

READ_ONLY_FOR_APP = (
    "fee_reference", "formula_definition", "hsn_gst_reference", "gst_slab_reference", "plan", "whatsapp_template", "tenant_plan", "member_entitlement_allocation",
    "entitlement_cap_config", "capability_entitlement_rule", "metered_event_meter_map", "anomaly_detection_config", "discount_bearer_config", "financial_health_config",
    "reconciliation_tolerance_config", "severity_config", "ci_tenant_config", "tenant_cart_item",
    "whatsapp_alert_subscription", "whatsapp_binding", "whatsapp_message", "whatsapp_pending_action",
)
APPEND_ONLY_FOR_APP = ("auth_audit", "metered_event")


def _each(tables: tuple[str, ...], privileges: str, verb: str, preposition: str) -> str:
    return "\n".join(
        f"IF to_regclass('public.{t}') IS NOT NULL THEN {verb} {privileges} ON public.{t} {preposition} metrion_app; END IF;" for t in tables
    )


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN\n"
        + _each(READ_ONLY_FOR_APP, "INSERT, UPDATE, DELETE", "REVOKE", "FROM")
        + "\n"
        + _each(APPEND_ONLY_FOR_APP, "UPDATE, DELETE", "REVOKE", "FROM")
        + "\nEND $$;"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN\n"
        + _each(READ_ONLY_FOR_APP, "INSERT, UPDATE, DELETE", "GRANT", "TO")
        + "\n"
        + _each(APPEND_ONLY_FOR_APP, "UPDATE, DELETE", "GRANT", "TO")
        + "\nEND $$;"
    )
