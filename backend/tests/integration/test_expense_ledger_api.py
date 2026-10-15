"""`/api/v1/cfo/expense-ledger` — kickoff S3b against a real Postgres (only Clerk is faked).

Writes need `financials.adjust` (a PARTNER without it gets 403, AC8/AC8a) and the CFO entitlement gate; reads need `agent.cfo`. One `agent_run` row per write (X3). Void
instead of delete, linked corrections and refunds, idempotent retry, the vendor amount-pattern rule (Q22), the proposed bounds, two-tenant isolation. The legacy
`PUT/GET /cfo/expenses` is untouched.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from tests.integration.test_cfo_pnl import (  # noqa: F401  (fixtures and helpers)
    _register_owner,
    _register_partner_with_permissions,
    _seed_zero_cap,
    app_client,
    fake_clerk,
)

BASE = "/api/v1/cfo/expense-ledger"
BODY = {"effective_date": "2026-09-10", "category": "operating_overhead", "amount_paise": 125_000, "vendor": "Acme Realty", "description": "September rent"}


def post(client, headers, body=None, **extra):
    return client.post(BASE, json={**(body or BODY), **extra}, headers=headers)


def runs(migrate_engine, tenant):
    from backend.tenant_context import tenant_scope

    with tenant_scope(tenant) as conn:
        return conn.execute(text("SELECT count(*) FROM agent_run WHERE trigger_ref = 'cfo.expense_ledger'")).scalar_one()


@pytest.fixture
def owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[0])


@pytest.fixture
def other_owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[1])


def test_the_category_list_is_served_and_closed(app_client, owner):
    r = app_client.get(f"{BASE}/categories", headers=owner)
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()["categories"]}
    assert "storage" in ids and "direct_product_costs" not in ids
    assert {c["costClass"] for c in r.json()["categories"]} <= {"ADVERTISING", "STORAGE", "OVERHEAD", "DIRECT"}
    assert r.json()["limits"]["amountMaxPaise"] == 9_999_999_999_999


def test_create_then_read_back_with_two_separate_status_fields(app_client, owner):
    r = post(app_client, owner)
    assert r.status_code == 201, r.text
    eid = r.json()["expenseId"]
    d = app_client.get(f"{BASE}/{eid}", headers=owner).json()
    assert d["amountPaise"] == 125_000 and d["costClass"] == "OVERHEAD" and d["treatment"] == "incremental"
    assert d["reviewState"] == "confirmed" and d["paymentStatus"] == "unknown"   # two separate fields
    assert d["origin"] == "MANUAL" and d["sourceReference"] == "manual"
    assert [h["kind"] for h in d["history"]] == ["REVIEW", "PAYMENT"]


def test_a_partner_without_financials_adjust_cannot_write_but_can_read(app_client, fake_clerk, two_tenants, owner):
    a, _ = two_tenants
    eid = post(app_client, owner).json()["expenseId"]
    partner = _register_partner_with_permissions(fake_clerk, a, permissions={"agent.cfo": True})
    assert post(app_client, partner).status_code == 403                                   # AC8
    assert app_client.post(f"{BASE}/{eid}/void", json={"reason": "x"}, headers=partner).status_code == 403
    assert app_client.post(f"{BASE}/{eid}/review", json={"state": "pending_review"}, headers=partner).status_code == 403
    assert app_client.post(f"{BASE}/{eid}/payment", json={"status": "paid"}, headers=partner).status_code == 403
    assert app_client.post(f"{BASE}/{eid}/refund", json={"effective_date": "2026-10-01", "amount_paise": -1}, headers=partner).status_code == 403
    assert app_client.post(f"{BASE}/{eid}/correct", json=BODY, headers=partner).status_code == 403
    assert app_client.get(BASE, headers=partner).status_code == 200                       # viewing is the existing read permission (agent.cfo)
    granted = _register_partner_with_permissions(fake_clerk, a, permissions={"agent.cfo": True, "financials.adjust": True})
    assert post(app_client, granted).status_code == 201                                   # AC8a: with the grant it works


def test_a_member_without_agent_cfo_is_refused_everywhere(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    nobody = _register_partner_with_permissions(fake_clerk, a, permissions={})
    assert app_client.get(BASE, headers=nobody).status_code == 403
    assert post(app_client, nobody).status_code == 403


def test_the_entitlement_gate_applies(app_client, fake_clerk, two_tenants, migrate_engine, owner):
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.expense_ledger.write")
    assert post(app_client, owner).status_code == 402


def test_each_write_leaves_exactly_one_agent_run_row(app_client, owner, two_tenants, migrate_engine):
    a, _ = two_tenants
    before = runs(migrate_engine, a)
    eid = post(app_client, owner).json()["expenseId"]
    assert runs(migrate_engine, a) == before + 1
    app_client.post(f"{BASE}/{eid}/payment", json={"status": "paid", "paid_amount_paise": 125_000}, headers=owner)
    assert runs(migrate_engine, a) == before + 2
    app_client.get(f"{BASE}/{eid}", headers=owner)
    app_client.get(BASE, headers=owner)
    assert runs(migrate_engine, a) == before + 2                                           # reads write no run


def test_an_idempotent_retry_returns_the_original_record(app_client, owner):
    first = post(app_client, owner, idempotency_key="rent-2026-09")
    second = post(app_client, owner, idempotency_key="rent-2026-09")
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["expenseId"] == second.json()["expenseId"] and second.json()["replayed"] is True
    assert app_client.get(BASE, headers=owner).json()["total"] == 1


def test_void_instead_of_delete_keeps_the_record_and_the_reason(app_client, owner):
    eid = post(app_client, owner).json()["expenseId"]
    assert app_client.post(f"{BASE}/{eid}/void", json={"reason": ""}, headers=owner).status_code == 422   # a void needs a reason
    r = app_client.post(f"{BASE}/{eid}/void", json={"reason": "entered twice"}, headers=owner)
    assert r.status_code == 200
    d = app_client.get(f"{BASE}/{eid}", headers=owner).json()
    assert d["reviewState"] == "voided" and d["reviewReason"] == "entered twice"
    assert app_client.get(BASE, headers=owner).json()["total"] == 0
    assert app_client.get(BASE, params={"include_voided": "true"}, headers=owner).json()["total"] == 1
    assert app_client.post(f"{BASE}/{eid}/review", json={"state": "confirmed"}, headers=owner).status_code == 409   # voided is terminal
    assert not hasattr(app_client, "delete") or app_client.delete(f"{BASE}/{eid}", headers=owner).status_code in (404, 405)


def test_an_edit_is_a_linked_correction_that_voids_the_original(app_client, owner):
    eid = post(app_client, owner).json()["expenseId"]
    r = app_client.post(f"{BASE}/{eid}/correct", json={**BODY, "amount_paise": 130_000, "reason": "wrong amount"}, headers=owner)
    assert r.status_code == 201
    new_id = r.json()["expenseId"]
    assert new_id != eid
    new = app_client.get(f"{BASE}/{new_id}", headers=owner).json()
    old = app_client.get(f"{BASE}/{eid}", headers=owner).json()
    assert new["correctsExpenseId"] == eid and new["amountPaise"] == 130_000
    assert old["reviewState"] == "voided" and old["amountPaise"] == 125_000          # the original is untouched, only voided


def test_a_refund_is_a_negative_linked_record_in_its_own_period(app_client, owner):
    eid = post(app_client, owner).json()["expenseId"]
    r = app_client.post(f"{BASE}/{eid}/refund", json={"effective_date": "2026-10-03", "amount_paise": -40_000}, headers=owner)
    assert r.status_code == 201
    d = app_client.get(f"{BASE}/{r.json()['expenseId']}", headers=owner).json()
    assert d["refundOfExpenseId"] == eid and d["amountPaise"] == -40_000 and d["effectiveDate"] == "2026-10-03"
    assert app_client.post(f"{BASE}/{eid}/refund", json={"effective_date": "2026-10-03", "amount_paise": 40_000}, headers=owner).status_code == 422


@pytest.mark.parametrize("patch,status", [
    ({"vendor": "Acme ₹500"}, 422), ({"vendor": "paid 1,200.50 to Acme"}, 422), ({"vendor": "3M"}, 201),   # Q22
    ({"amount_paise": 1.5}, 422), ({"amount_paise": "100"}, 422), ({"amount_paise": 10_000_000_000_000}, 422), ({"amount_paise": -5}, 422),
    ({"amount_paise": 0}, 201), ({"category": "direct_product_costs"}, 422), ({"category": "nonsense"}, 422), ({"cost_class": "COGS"}, 422),
    ({"treatment": "replaces_input"}, 422), ({"channel_scope": "EBAY"}, 422), ({"effective_date": "not-a-date"}, 422),
    ({"description": "x" * 501}, 422), ({"tenant_id": str(uuid.uuid4())}, 422), ({"state": "voided"}, 422),
])
def test_validation_and_bounds(app_client, owner, patch, status):
    assert post(app_client, owner, **patch).status_code == status


def test_a_category_supplies_the_default_cost_class_and_the_record_may_override_it(app_client, owner):
    d1 = app_client.get(f"{BASE}/{post(app_client, owner, category='advertising').json()['expenseId']}", headers=owner).json()
    assert d1["costClass"] == "ADVERTISING"
    d2 = app_client.get(f"{BASE}/{post(app_client, owner, category='other', cost_class='DIRECT').json()['expenseId']}", headers=owner).json()
    assert d2["costClass"] == "DIRECT"
    d3 = app_client.get(f"{BASE}/{post(app_client, owner, category='taxes').json()['expenseId']}", headers=owner).json()
    assert d3["treatment"] == "informational"


def test_status_changes_review_and_payment(app_client, owner):
    eid = post(app_client, owner, state="pending_review").json()["expenseId"]
    assert app_client.get(f"{BASE}/{eid}", headers=owner).json()["reviewState"] == "pending_review"
    assert app_client.post(f"{BASE}/{eid}/review", json={"state": "confirmed"}, headers=owner).status_code == 200
    assert app_client.post(f"{BASE}/{eid}/payment", json={"status": "partially_paid", "paid_amount_paise": 25_000}, headers=owner).status_code == 200
    d = app_client.get(f"{BASE}/{eid}", headers=owner).json()
    assert (d["reviewState"], d["paymentStatus"], d["paidAmountPaise"]) == ("confirmed", "partially_paid", 25_000)
    assert app_client.post(f"{BASE}/{eid}/payment", json={"status": "settled"}, headers=owner).status_code == 422


def test_list_filters_and_page_size_cap(app_client, owner):
    post(app_client, owner, category="software", effective_date="2026-09-01")
    post(app_client, owner, category="advertising", effective_date="2026-10-05")
    assert app_client.get(BASE, params={"category": "software"}, headers=owner).json()["total"] == 1
    assert app_client.get(BASE, params={"date_from": "2026-10-01"}, headers=owner).json()["total"] == 1
    assert app_client.get(BASE, params={"limit": 201}, headers=owner).status_code == 422
    assert app_client.get(BASE, params={"review_state": "bogus"}, headers=owner).status_code == 422


def test_two_tenants_cannot_see_or_touch_each_others_records(app_client, owner, other_owner):
    eid = post(app_client, owner).json()["expenseId"]
    assert app_client.get(f"{BASE}/{eid}", headers=other_owner).status_code == 404
    assert app_client.post(f"{BASE}/{eid}/void", json={"reason": "x"}, headers=other_owner).status_code == 404
    assert app_client.post(f"{BASE}/{eid}/refund", json={"effective_date": "2026-10-01", "amount_paise": -1}, headers=other_owner).status_code == 404
    assert app_client.get(BASE, headers=other_owner).json()["total"] == 0


def test_the_legacy_expense_routes_still_work_unchanged(app_client, owner):
    r = app_client.put("/api/v1/cfo/expenses", json={"target_type": "ACCOUNT", "target_ref": "default", "field": "expense.other", "value": {"amount_paise": 500}}, headers=owner)
    assert r.status_code == 200 and "manualAdjustmentId" in r.json()
    listed = app_client.get("/api/v1/cfo/expenses", headers=owner).json()
    assert listed["totalPaise"] == 500
    assert app_client.get(BASE, headers=owner).json()["total"] == 0           # the two stores are separate; no migration (Q16)
