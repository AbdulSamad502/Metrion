"""Least privilege for `metrion_app` (migration 20261012_0018), proved with the REAL application role on scratch PostgreSQL.

Denied: writing platform reference data, plan/entitlement/threshold configuration and WhatsApp tables, and altering or deleting the audit trail and billing ledger.
Still allowed (a runtime need): reading all of it, appending audit and ledger rows, and the writes the application genuinely performs elsewhere."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

pytestmark = pytest.mark.usefixtures("two_tenants")

READ_ONLY = (
    "fee_reference", "formula_definition", "hsn_gst_reference", "gst_slab_reference", "plan", "whatsapp_template", "tenant_plan", "member_entitlement_allocation",
    "entitlement_cap_config", "capability_entitlement_rule", "metered_event_meter_map", "anomaly_detection_config", "discount_bearer_config", "financial_health_config",
    "reconciliation_tolerance_config", "severity_config", "expense_class_map", "ci_tenant_config", "tenant_cart_item",
    "whatsapp_alert_subscription", "whatsapp_binding", "whatsapp_message", "whatsapp_pending_action",
)
APPEND_ONLY = ("auth_audit", "metered_event", "expense_entry", "expense_class_assignment", "expense_period_declaration", "ad_report_line", "ad_period_declaration", "cost_owner_choice", "leak_claim_event", "held_row", "held_row_resolution", "expense_payment_event")  # the CFO expense ledger and advertising records


def _has(conn, table: str, priv: str) -> bool:
    return bool(conn.execute(text("SELECT has_table_privilege('metrion_app', CAST(:t AS regclass), :p)"), {"t": table, "p": priv}).scalar_one())


@pytest.mark.parametrize("table", READ_ONLY)
def test_reference_and_configuration_tables_are_read_only_for_the_app_role(migrate_engine, table):
    with migrate_engine.connect() as conn:
        assert _has(conn, table, "SELECT")  # every read path is unchanged
        assert not any(_has(conn, table, p) for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")), table


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_the_audit_trail_and_the_billing_ledger_are_append_only_for_the_app_role(migrate_engine, table):
    with migrate_engine.connect() as conn:
        assert _has(conn, table, "SELECT") and _has(conn, table, "INSERT")
        assert not any(_has(conn, table, p) for p in ("UPDATE", "DELETE", "TRUNCATE")), table


@pytest.mark.parametrize("sql", [
    "UPDATE fee_reference SET marketplace = marketplace",
    "DELETE FROM fee_reference",
    "UPDATE formula_definition SET id = id",
    "DELETE FROM hsn_gst_reference",
    "UPDATE gst_slab_reference SET id = id",
    "DELETE FROM plan",
    "UPDATE plan SET id = id",
    "DELETE FROM entitlement_cap_config",
    "UPDATE capability_entitlement_rule SET id = id",
    "DELETE FROM auth_audit",
    "UPDATE auth_audit SET id = id",
    "DELETE FROM metered_event",
    "UPDATE metered_event SET quantity = 0",
    "TRUNCATE metered_event",
])
def test_the_real_app_role_is_refused_with_permission_denied(app_engine, sql):
    with pytest.raises((ProgrammingError, DBAPIError)) as caught:
        with app_engine.begin() as conn:
            conn.execute(text(sql))
    assert "permission denied" in str(caught.value).lower()


def test_the_real_app_role_may_still_read_reference_data(app_engine):
    with app_engine.connect() as conn:
        for table in ("plan", "fee_reference", "formula_definition", "gst_slab_reference", "hsn_gst_reference", "entitlement_cap_config"):
            conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608 - fixed names


def test_the_app_still_appends_audit_and_ledger_rows(two_tenants, app_user):
    from backend.entitlement import record_metered_event
    from backend.repositories import auth_audit_repo
    from backend.tenant_context import tenant_scope

    a, _ = two_tenants
    auth_audit_repo.record(a, actor_user_id=app_user, event="TEST_EVENT", subject="least-privilege", metadata={"k": "v"})
    record_metered_event(a, agent_code="CEO", event_kind="ceo.chat_turn", idempotency_key=f"lp:{uuid.uuid4()}", member_id=app_user)
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM auth_audit WHERE event = 'TEST_EVENT'")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM metered_event WHERE event_kind = 'ceo.chat_turn'")).scalar_one() == 1
