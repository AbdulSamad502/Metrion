"""`/api/v1/cfo/expense-ledger/templates` — kickoff S4b against a real Postgres (only Clerk is faked).

Recurring and amortized templates materialise into `pending_review` ledger entries (X10) that are not counted until confirmed; materialising is idempotent; a rate change is a
new version; per-order and per-unit templates never produce a made-up amount; writes need `financials.adjust`; tenants are isolated.
"""

from __future__ import annotations

import uuid  # noqa: F401

import pytest

from tests.integration.test_cfo_pnl import (  # noqa: F401  (fixtures and helpers)
    _clean_metric_result_table,
    _register_owner,
    _register_partner_with_permissions,
    _seed_zero_cap,
    app_client,
    fake_clerk,
)

BASE = "/api/v1/cfo/expense-ledger"
T = f"{BASE}/templates"
MONTHLY = {"kind": "MONTHLY", "category": "software", "effective_from": "2026-01-01", "amount_paise": 50_000, "vendor": "Acme SaaS"}


@pytest.fixture
def owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[0])


@pytest.fixture
def other_owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[1])


def entries(client, headers):
    r = client.get(f"{BASE}?limit=200&include_voided=true", headers=headers)
    assert r.status_code == 200
    return sorted(r.json()["records"], key=lambda x: x["effectiveDate"])


def test_create_list_and_materialise_a_monthly_template(app_client, owner):
    r = app_client.post(T, json=MONTHLY, headers=owner)
    assert r.status_code == 201, r.text
    key = r.json()["templateKey"]
    listed = app_client.get(T, headers=owner).json()["templates"]
    assert [(t["templateKey"], t["version"], t["kind"], t["amountPaise"], t["costClass"]) for t in listed] == [(key, 1, "MONTHLY", 50_000, "OVERHEAD")]
    m = app_client.post(f"{T}/materialise", json={"through_month": "2026-03-01"}, headers=owner)
    assert m.status_code == 200, m.text
    assert len(m.json()["created"]) == 3 and m.json()["alreadyMaterialised"] == 0 and m.json()["skipped"] == []
    got = entries(app_client, owner)
    assert [e["effectiveDate"] for e in got] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert {e["reviewState"] for e in got} == {"pending_review"} and {e["recurring"] for e in got} == {True}  # X10
    assert got[0]["sourceReference"] == f"template:{key}:2026-01"


def test_materialised_entries_are_not_counted_until_confirmed(app_client, owner):
    app_client.post(T, json=MONTHLY, headers=owner)
    app_client.post(f"{T}/materialise", json={"through_month": "2026-01-01"}, headers=owner)
    period = {"period_start": "2026-01-01", "period_end": "2026-01-31"}
    before = app_client.post(f"{BASE}/summary", json=period, headers=owner).json()
    assert before["expenseTotal"]["paise"] == 0 and before["reviewQueue"]["amountPaise"] == 50_000 and "OVERHEAD" in before["notEntered"]
    eid = entries(app_client, owner)[0]["id"]
    assert app_client.post(f"{BASE}/{eid}/review", json={"state": "confirmed"}, headers=owner).status_code == 200
    after = app_client.post(f"{BASE}/summary", json=period, headers=owner).json()
    assert after["expenseTotal"]["paise"] == 50_000 and after["recurringTotal"]["paise"] == 50_000 and after["notEntered"] == ["ADVERTISING", "STORAGE", "DIRECT"]


def test_materialising_twice_creates_nothing_twice_and_writes_no_second_run(app_client, owner, two_tenants, migrate_engine):
    from sqlalchemy import text

    from backend.tenant_context import tenant_scope

    app_client.post(T, json=MONTHLY, headers=owner)
    first = app_client.post(f"{T}/materialise", json={"through_month": "2026-02-01"}, headers=owner).json()
    again = app_client.post(f"{T}/materialise", json={"through_month": "2026-02-01"}, headers=owner).json()
    assert len(first["created"]) == 2 and again["created"] == [] and again["alreadyMaterialised"] == 2 and len(entries(app_client, owner)) == 2
    with tenant_scope(two_tenants[0]) as conn:
        assert conn.execute(text("SELECT count(*) FROM agent_run WHERE trigger_ref = 'cfo.expense_ledger'")).scalar_one() == 2  # the template + the first materialisation only


def test_a_rate_change_is_a_new_version_and_ending_stops_new_entries(app_client, owner):
    key = app_client.post(T, json={**MONTHLY, "effective_to": "2026-02-28"}, headers=owner).json()["templateKey"]
    v2 = app_client.post(f"{T}/{key}/version", json={**MONTHLY, "effective_from": "2026-03-01", "amount_paise": 70_000}, headers=owner)
    assert v2.status_code == 201 and v2.json()["version"] == 2
    app_client.post(f"{T}/materialise", json={"through_month": "2026-04-01"}, headers=owner)
    assert [e["amountPaise"] for e in entries(app_client, owner)] == [50_000, 50_000, 70_000, 70_000]
    end = app_client.post(f"{T}/{key}/end", json={"effective_to": "2026-04-30"}, headers=owner)
    assert end.status_code == 201 and end.json()["version"] == 3
    app_client.post(f"{T}/materialise", json={"through_month": "2026-08-01"}, headers=owner)
    assert len(entries(app_client, owner)) == 4 and app_client.get(T, headers=owner).json()["templates"][0]["ended"] is True


def test_an_amortized_template_spreads_the_amount_exactly(app_client, owner):
    body = {"kind": "AMORTIZED", "category": "software", "effective_from": "2026-01-01", "amount_paise": 100_001, "amortization_months": 12, "start_month": "2026-04-20"}
    assert app_client.post(T, json=body, headers=owner).status_code == 201
    app_client.post(f"{T}/materialise", json={"through_month": "2026-10-01"}, headers=owner)
    got = entries(app_client, owner)
    assert [e["effectiveDate"] for e in got] == [f"2026-{m:02d}-01" for m in range(4, 11)]  # up to the requested month; the rest wait
    assert len(got) == 7


@pytest.mark.parametrize("months", [0, -1, 2.5, "12", True, 121])
def test_invalid_amortization_months_are_refused_at_entry(app_client, owner, months):
    body = {"kind": "AMORTIZED", "category": "software", "effective_from": "2026-01-01", "amount_paise": 1_000, "amortization_months": months}
    assert app_client.post(T, json=body, headers=owner).status_code == 422
    assert app_client.get(T, headers=owner).json()["templates"] == []


def _insert_run(tenant):
    import uuid as _uuid
    from datetime import datetime, timezone

    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.tenant_context import tenant_scope as df_scope
    from sqlalchemy import text as _text

    file_id = _uuid.uuid4()
    with df_scope(tenant) as conn:
        conn.execute(
            _text("INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                  "VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'synthetic.csv', 100, 'file://x', :by, :at)"),
            {"id": str(file_id), "t": str(tenant), "sha": _uuid.uuid4().hex + _uuid.uuid4().hex, "by": str(_uuid.uuid4()), "at": datetime.now(timezone.utc)},
        )
    return ingestion_run_repo.insert_ingestion_run(tenant, report_file_id=file_id, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc))


def _seed_sales(tenant, *, orders, day="2026-09-10", cancelled="NOT_CANCELLED", declare_status=True):
    """Real sales_line rows (order id, quantity); the seller's status overrides are declared exactly as the period P&L reads them."""
    import uuid as _uuid
    from datetime import date as _date, datetime, timezone

    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
    from data_foundation.repositories.sales_line_repo import insert_sales_line

    run = _insert_run(tenant)
    ids = []
    for n, (ref, qty) in enumerate(orders, start=1):
        line = insert_sales_line(
            tenant, ingestion_run_id=run, marketplace="MEESHO",
            canonical_fields={"order_ref": ref, "quantity": qty, "gross_item_amount": 20_000, "taxable_amount": 20_000, "order_date": _date.fromisoformat(day),
                              "return_status": "NOT_RETURNED", "sku": "SKU-1"},
            source_row_number=n, source_row_json={}, confidence="PROVISIONAL",
        )
        if declare_status:
            for field, value in (("cancellation_state_override", cancelled), ("rto_status_override", "NOT_RTO")):
                insert_adjustment(tenant, target_type="LINE", target_ref=str(line), field=field, value=value, created_by=_uuid.uuid4(), created_at=datetime.now(timezone.utc))
        ids.append(line)
    return ids


def test_per_order_and_per_unit_templates_with_no_sales_data_make_nothing_and_say_why(app_client, owner):
    key = app_client.post(T, json={"kind": "PER_ORDER", "category": "packaging", "effective_from": "2026-01-01", "rate_paise": 500}, headers=owner).json()["templateKey"]
    m = app_client.post(f"{T}/materialise", json={"through_month": "2026-03-01"}, headers=owner).json()
    assert m["created"] == [] and m["skipped"] == [{"templateKey": key, "reason": "NO_ORDERS_IN_PERIOD"}] and entries(app_client, owner) == []  # unavailable, not zero


def test_a_per_order_template_prices_the_engines_order_count_and_waits_for_review(app_client, owner, two_tenants):
    _seed_sales(two_tenants[0], orders=[("ORD-1", 2), ("ORD-2", 3), ("ORD-2", 1)])  # two orders, three lines, six units
    app_client.post(T, json={"kind": "PER_ORDER", "category": "packaging", "effective_from": "2026-09-01", "rate_paise": 500, "vendor": "Mailer Co"}, headers=owner)
    m = app_client.post(f"{T}/materialise", json={"through_month": "2026-09-01"}, headers=owner).json()
    assert len(m["created"]) == 1 and m["skipped"] == []
    row = entries(app_client, owner)[0]
    assert (row["amountPaise"], row["reviewState"], row["recurring"], row["effectiveDate"]) == (1_000, "pending_review", True, "2026-09-01")
    assert "2 orders x Rs 5.00" in row["description"]


def test_a_per_unit_template_prices_net_units_kept(app_client, owner, two_tenants):
    _seed_sales(two_tenants[0], orders=[("ORD-1", 2), ("ORD-2", 3)])
    app_client.post(T, json={"kind": "PER_UNIT", "category": "packaging", "effective_from": "2026-09-01", "rate_paise": 250}, headers=owner)
    app_client.post(f"{T}/materialise", json={"through_month": "2026-09-01"}, headers=owner)
    assert entries(app_client, owner)[0]["amountPaise"] == 1_250  # 5 units x Rs 2.50


def test_cancelled_orders_are_not_counted_and_a_true_zero_is_a_real_zero_entry(app_client, owner, two_tenants):
    _seed_sales(two_tenants[0], orders=[("ORD-1", 1), ("ORD-2", 1)], cancelled="CANCELLED")
    app_client.post(T, json={"kind": "PER_ORDER", "category": "packaging", "effective_from": "2026-09-01", "rate_paise": 500}, headers=owner)
    m = app_client.post(f"{T}/materialise", json={"through_month": "2026-09-01"}, headers=owner).json()
    row = entries(app_client, owner)[0]
    assert len(m["created"]) == 1 and row["amountPaise"] == 0 and "0 orders" in row["description"]


def test_a_line_whose_status_is_unknown_makes_the_count_unavailable_not_partial(app_client, owner, two_tenants):
    _seed_sales(two_tenants[0], orders=[("ORD-1", 1)])
    _seed_sales(two_tenants[0], orders=[("ORD-9", 1)], declare_status=False)  # no declared cancellation or RTO status: this line cannot be assembled
    key = app_client.post(T, json={"kind": "PER_ORDER", "category": "packaging", "effective_from": "2026-09-01", "rate_paise": 500}, headers=owner).json()["templateKey"]
    m = app_client.post(f"{T}/materialise", json={"through_month": "2026-09-01"}, headers=owner).json()
    assert m["created"] == [] and m["skipped"] == [{"templateKey": key, "reason": "ORDERS_UNAVAILABLE"}] and entries(app_client, owner) == []


def test_the_current_month_is_not_priced_until_it_has_finished(app_client, owner):
    from datetime import date as _date

    month = _date.today().replace(day=1).isoformat()
    key = app_client.post(T, json={"kind": "PER_ORDER", "category": "packaging", "effective_from": month, "rate_paise": 500}, headers=owner).json()["templateKey"]
    m = app_client.post(f"{T}/materialise", json={"through_month": month}, headers=owner).json()
    assert m["created"] == [] and m["skipped"] == [{"templateKey": key, "reason": "MONTH_NOT_FINISHED"}]


def test_tenants_do_not_count_each_others_orders(app_client, owner, other_owner, two_tenants):
    _seed_sales(two_tenants[1], orders=[("X-1", 1), ("X-2", 1), ("X-3", 1)])
    app_client.post(T, json={"kind": "PER_ORDER", "category": "packaging", "effective_from": "2026-09-01", "rate_paise": 500}, headers=owner)
    m = app_client.post(f"{T}/materialise", json={"through_month": "2026-09-01"}, headers=owner).json()
    assert m["created"] == [] and m["skipped"][0]["reason"] == "NO_ORDERS_IN_PERIOD"  # the other tenant three orders are invisible


@pytest.mark.parametrize(
    "patch",
    [
        {"amount_paise": None},  # monthly needs an amount
        {"amount_paise": -5},  # a cost is not negative
        {"amount_paise": 1.5},
        {"amount_paise": 10**14},  # above the limit
        {"rate_paise": 500},  # a rate belongs to per-order templates
        {"kind": "WEEKLY"},
        {"category": "nope"},
        {"cost_class": "NOPE"},
        {"effective_from": "1999-12-31"},
        {"effective_to": "2025-12-31"},  # before the start
        {"vendor": "Rent 1,200.50"},  # Q22
        {"start_month": "2026-01-01"},
        {"tenant_id": "x"},
    ],
)
def test_malformed_templates_are_refused(app_client, owner, patch):
    assert app_client.post(T, json={**MONTHLY, **patch}, headers=owner).status_code == 422
    assert app_client.get(T, headers=owner).json()["templates"] == []


def test_materialising_far_in_the_future_or_over_too_many_months_is_refused(app_client, owner):
    app_client.post(T, json={**MONTHLY, "effective_from": "2010-01-01"}, headers=owner)
    assert app_client.post(f"{T}/materialise", json={"through_month": "2099-01-01"}, headers=owner).status_code == 422
    assert app_client.post(f"{T}/materialise", json={"through_month": "2026-09-01"}, headers=owner).status_code == 422  # would span more than 120 months
    assert entries(app_client, owner) == []


def test_a_partner_without_financials_adjust_can_read_but_not_write(app_client, fake_clerk, two_tenants, owner):
    a, _ = two_tenants
    key = app_client.post(T, json=MONTHLY, headers=owner).json()["templateKey"]
    partner = _register_partner_with_permissions(fake_clerk, a, permissions={"agent.cfo": True})
    assert app_client.get(T, headers=partner).status_code == 200
    assert app_client.post(T, json=MONTHLY, headers=partner).status_code == 403
    assert app_client.post(f"{T}/materialise", json={"through_month": "2026-01-01"}, headers=partner).status_code == 403
    assert app_client.post(f"{T}/{key}/version", json=MONTHLY, headers=partner).status_code == 403
    assert app_client.post(f"{T}/{key}/end", json={"effective_to": "2026-02-01"}, headers=partner).status_code == 403


def test_unknown_templates_are_404_and_tenants_are_isolated(app_client, owner, other_owner):
    key = app_client.post(T, json=MONTHLY, headers=owner).json()["templateKey"]
    assert app_client.get(T, headers=other_owner).json()["templates"] == []
    assert app_client.post(f"{T}/{key}/version", json=MONTHLY, headers=other_owner).status_code == 404
    assert app_client.post(f"{T}/{key}/end", json={"effective_to": "2026-02-01"}, headers=other_owner).status_code == 404
    assert app_client.post(f"{T}/{uuid.uuid4()}/end", json={"effective_to": "2026-02-01"}, headers=owner).status_code == 404
    app_client.post(f"{T}/materialise", json={"through_month": "2026-01-01"}, headers=other_owner)
    assert entries(app_client, other_owner) == []


def test_the_entitlement_gate_applies(app_client, owner, two_tenants, migrate_engine):
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.expense_ledger.write")
    assert app_client.post(T, json=MONTHLY, headers=owner).status_code == 402
