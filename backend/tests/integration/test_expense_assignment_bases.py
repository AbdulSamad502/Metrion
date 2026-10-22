"""Multi-SKU assignment by the SKUs' own net revenue, units or orders (engine section 5.18.3 with 5.10.1) against a real Postgres. The browser never sees the data: the route
stores the seller's choice, the feed reads each SKU's figures from the assembled sales lines, and the engine splits. Only Clerk is faked."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from tests.integration.test_cfo_pnl import (  # noqa: F401  (fixtures and helpers)
    _clean_metric_result_table,
    _register_owner,
    _register_partner_with_permissions,
    _seed_zero_cap,
    app_client,
    fake_clerk,
)

BASE = "/api/v1/cfo/expense-ledger"
PERIOD = {"period_start": "2026-09-01", "period_end": "2026-09-30"}


@pytest.fixture
def owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[0])


@pytest.fixture
def other_owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[1])


def seed(tenant, lines, *, declare_status=True):
    """Real sales_line rows: (sku, order id, quantity, gross paise); the seller's status overrides are declared as the period P&L reads them."""
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.sales_line_repo import insert_sales_line
    from data_foundation.repositories.tenant_context import tenant_scope as df_scope

    file_id = uuid.uuid4()
    with df_scope(tenant) as conn:
        conn.execute(
            text("INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                 "VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 's.csv', 1, 'file://x', :by, :at)"),
            {"id": str(file_id), "t": str(tenant), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "by": str(uuid.uuid4()), "at": datetime.now(timezone.utc)},
        )
    run = ingestion_run_repo.insert_ingestion_run(tenant, report_file_id=file_id, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc))
    for n, (sku, order, qty, gross, *when) in enumerate(lines, start=1):
        line = insert_sales_line(
            tenant, ingestion_run_id=run, marketplace="MEESHO",
            canonical_fields={"order_ref": order, "quantity": qty, "gross_item_amount": gross, "taxable_amount": gross, "order_date": when[0] if when else date(2026, 9, 10), "return_status": "NOT_RETURNED", "sku": sku},
            source_row_number=n, source_row_json={}, confidence="PROVISIONAL",
        )
        if declare_status:
            for field, value in (("cancellation_state_override", "NOT_CANCELLED"), ("rto_status_override", "NOT_RTO")):
                insert_adjustment(tenant, target_type="LINE", target_ref=str(line), field=field, value=value, created_by=uuid.uuid4(), created_at=datetime.now(timezone.utc))


def expense(client, headers, category="advertising", amount=10_001):
    r = client.post(BASE, json={"effective_date": "2026-09-12", "category": category, "amount_paise": amount, "vendor": "Ad Co"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["expenseId"]


def feed_for(tenant):
    from calc_engine.formulas.ledger_feed import ledger_feed
    from calc_engine.repositories import expense_ledger_repo as ledger

    from backend.services import expense_assignment_data as data

    events = ledger.feed_events(tenant, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    catalog = {s: s for s in ledger.known_skus(tenant)}
    basis = data.basis_data(tenant, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), events=events)
    return ledger_feed(events, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), channel_scope=None, catalog=catalog, basis_data=basis), basis


def assign(client, headers, eid, basis, *skus):
    return client.post(f"{BASE}/{eid}/assign", json={"basis": basis, "shares": [{"sku": s} for s in skus]}, headers=headers)


def test_units_follow_each_skus_net_units_and_the_pool_total_never_changes(app_client, owner, two_tenants):
    seed(two_tenants[0], [("A", "O1", 6, 60_000), ("B", "O2", 4, 40_000)])
    eid = expense(app_client, owner)
    r = assign(app_client, owner, eid, "UNITS", "A", "B")
    assert r.status_code == 201, r.text
    feed, basis = feed_for(two_tenants[0])
    pool = feed.pools["ADVERTISING"]
    assert {k: v.value for k, v in pool.sku_level.items()} == {"A": 6_001, "B": 4_000} and pool.business_level.value == 0
    assert pool.total.value == feed.expense_total.value == 10_001 and pool.manual_sku_level.value == 10_001  # SKU-level but flagged manual
    summary = app_client.post(f"{BASE}/summary", json=PERIOD, headers=owner).json()
    assert summary["expenseTotal"]["paise"] == 10_001  # the dashboard total is the same with or without the split (MS6)


def test_orders_follow_distinct_order_counts(app_client, owner, two_tenants):
    seed(two_tenants[0], [("A", "O1", 1, 100), ("A", "O2", 1, 100), ("A", "O3", 5, 100), ("B", "O4", 1, 100)])  # A has three orders, B one
    eid = expense(app_client, owner, amount=4_000)
    assert assign(app_client, owner, eid, "ORDERS", "A", "B").status_code == 201
    pool = feed_for(two_tenants[0])[0].pools["ADVERTISING"]
    assert {k: v.value for k, v in pool.sku_level.items()} == {"A": 3_000, "B": 1_000}


def test_net_revenue_follows_each_skus_revenue_from_the_engine(app_client, owner, two_tenants):
    seed(two_tenants[0], [("A", "O1", 1, 30_000), ("B", "O2", 1, 10_000)])
    eid = expense(app_client, owner, category="storage", amount=8_000)
    assert assign(app_client, owner, eid, "NET_REVENUE", "A", "B").status_code == 201
    feed, basis = feed_for(two_tenants[0])
    pool = feed.pools["STORAGE"]
    assert sum(v.value for v in pool.sku_level.values()) + pool.business_level.value == 8_000
    assert pool.sku_level["A"].value == 3 * pool.sku_level["B"].value  # revenue 3:1
    assert basis["A"].net_revenue is not None


def test_a_sku_with_no_sales_in_the_period_leaves_the_whole_amount_unassigned_never_zero(app_client, owner, two_tenants):
    seed(two_tenants[0], [("A", "O1", 6, 60_000), ("B", "O0", 4, 40_000, date(2026, 8, 5))])  # B is in the catalog but sold nothing in September
    eid = expense(app_client, owner)
    assert assign(app_client, owner, eid, "UNITS", "A", "B").status_code == 201
    feed, basis = feed_for(two_tenants[0])
    pool = feed.pools["ADVERTISING"]
    assert "B" not in basis and pool.sku_level == {} and pool.business_level.value == 10_001 and pool.total.value == 10_001  # no data for B: nothing is guessed, nothing is lost


def test_a_sku_that_is_not_in_the_catalog_gets_no_share_the_mapped_ones_split_the_amount(app_client, owner, two_tenants):
    seed(two_tenants[0], [("A", "O1", 6, 60_000)])  # B has no sales line at all, so it is not in the seller catalog (Q29)
    eid = expense(app_client, owner)
    assert assign(app_client, owner, eid, "UNITS", "A", "B").status_code == 201
    feed, _ = feed_for(two_tenants[0])
    assert {k: v.value for k, v in feed.pools["ADVERTISING"].sku_level.items()} == {"A": 10_001}
    assert any(item.reason == "UNMAPPED_IDENTIFIER" and item.expense_id == eid for item in feed.review_queue)  # B goes to the review queue


def test_unknown_cancellation_return_or_rto_status_makes_the_figures_unavailable_not_zero(app_client, owner, two_tenants):
    seed(two_tenants[0], [("A", "O1", 6, 60_000), ("B", "O2", 4, 40_000)], declare_status=False)  # no declared cancellation or RTO status
    eid = expense(app_client, owner)
    assert assign(app_client, owner, eid, "UNITS", "A", "B").status_code == 201
    feed, basis = feed_for(two_tenants[0])
    assert all(t.units_sold is None and t.units_returned is None and t.order_ids is None for t in basis.values())
    assert feed.pools["ADVERTISING"].sku_level == {} and feed.pools["ADVERTISING"].business_level.value == 10_001


def test_a_data_basis_takes_no_basis_points_and_only_advertising_or_storage_can_be_assigned(app_client, owner):
    adv = expense(app_client, owner)
    bad = app_client.post(f"{BASE}/{adv}/assign", json={"basis": "UNITS", "shares": [{"sku": "A", "bp": 5_000}, {"sku": "B"}]}, headers=owner)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "INVALID_ASSIGNMENT"
    rent = expense(app_client, owner, category="operating_overhead")
    assert assign(app_client, owner, rent, "ORDERS", "A", "B").status_code == 422
    assert app_client.post(f"{BASE}/{adv}/assign", json={"basis": "MAGIC", "shares": [{"sku": "A"}]}, headers=owner).status_code == 422
    assert app_client.post(f"{BASE}/{adv}/assign", json={"basis": "UNITS", "shares": []}, headers=owner).status_code == 422
    assert app_client.post(f"{BASE}/{adv}/assign", json={"basis": "UNITS", "shares": [{"sku": "A"}, {"sku": "A"}]}, headers=owner).status_code == 422  # a SKU twice


def test_the_choice_is_stored_and_a_new_choice_replaces_it_while_the_old_stays_as_history(app_client, owner, two_tenants):
    seed(two_tenants[0], [("A", "O1", 6, 60_000), ("B", "O2", 4, 40_000)])
    eid = expense(app_client, owner)
    assign(app_client, owner, eid, "UNITS", "A", "B")
    assert app_client.get(f"{BASE}/{eid}", headers=owner).json()["assignment"] == {"basis": "UNITS", "shares": [{"sku": "A", "bp": None}, {"sku": "B", "bp": None}]}
    assert app_client.post(f"{BASE}/{eid}/assign", json={"basis": "EQUAL", "shares": [{"sku": "A"}, {"sku": "B"}]}, headers=owner).status_code == 201
    assert app_client.get(f"{BASE}/{eid}", headers=owner).json()["assignment"]["basis"] == "EQUAL"
    with_tenant = two_tenants[0]
    from backend.tenant_context import tenant_scope

    with tenant_scope(with_tenant) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_assignment WHERE expense_id = :e"), {"e": eid}).scalar_one() == 2


def test_a_voided_record_and_a_foreign_tenant_cannot_be_assigned_and_permission_is_needed(app_client, fake_clerk, two_tenants, owner, other_owner):
    eid = expense(app_client, owner)
    assert assign(app_client, other_owner, eid, "UNITS", "A").status_code == 404
    partner = _register_partner_with_permissions(fake_clerk, two_tenants[0], permissions={"agent.cfo": True})
    assert assign(app_client, partner, eid, "UNITS", "A").status_code == 403
    assert app_client.post(f"{BASE}/{eid}/void", json={"reason": "wrong"}, headers=owner).status_code == 200
    assert assign(app_client, owner, eid, "UNITS", "A").status_code == 409


def test_the_other_tenants_sales_never_feed_the_split(app_client, owner, other_owner, two_tenants):
    seed(two_tenants[1], [("A", "X1", 9, 90_000), ("B", "X2", 1, 10_000)])  # another tenant's sales for the same SKU names
    seed(two_tenants[0], [("A", "O1", 1, 10_000), ("B", "O2", 1, 10_000)])
    eid = expense(app_client, owner, amount=1_000)
    assign(app_client, owner, eid, "UNITS", "A", "B")
    pool = feed_for(two_tenants[0])[0].pools["ADVERTISING"]
    assert {k: v.value for k, v in pool.sku_level.items()} == {"A": 500, "B": 500}  # one unit each in OUR data, not 9 and 1


def test_nothing_is_read_unless_a_record_actually_needs_sales_data(app_client, owner, two_tenants, monkeypatch):
    from calc_engine.repositories import expense_ledger_repo as ledger

    from backend.services import cfo_actions
    from backend.services import expense_assignment_data as data

    def boom(*a, **k):
        raise AssertionError("sales lines must not be read for an expense without a data-driven assignment")

    monkeypatch.setattr(cfo_actions, "assemble_canonical_lines_for_period", boom)
    eid = expense(app_client, owner)
    assign(app_client, owner, eid, "EQUAL", "A", "B")  # a seller-chosen basis needs no sales data
    events = ledger.feed_events(two_tenants[0], period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    assert data.basis_data(two_tenants[0], period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), events=events) is None
    assert app_client.post(f"{BASE}/summary", json=PERIOD, headers=owner).status_code == 200


def test_a_voided_record_does_not_ask_for_sales_data(app_client, owner, two_tenants, monkeypatch):
    from calc_engine.repositories import expense_ledger_repo as ledger

    from backend.services import expense_assignment_data as data

    eid = expense(app_client, owner)
    assign(app_client, owner, eid, "UNITS", "A", "B")
    app_client.post(f"{BASE}/{eid}/void", json={"reason": "wrong"}, headers=owner)
    events = ledger.feed_events(two_tenants[0], period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    assert data.needed_skus(events) == set()
