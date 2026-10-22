"""`POST /api/v1/cfo/expense-ledger/{id}/assign` — kickoff S5c (multi-SKU assignment, Q33; engine §5.18.3, tests MS1–MS7) against a real Postgres (only Clerk is faked).

The seller chooses the split; the engine computes it when the feed is built. Shares are SKU-level and flagged manual, the pool total never changes, an unmapped SKU goes to the
review queue, shares above 10,000 basis points are rejected at entry, and writes need `financials.adjust`.
"""

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
AD = {"effective_date": "2026-09-10", "category": "advertising", "amount_paise": 10_001, "vendor": "Ad Network"}


def seed_catalog(tenant, *skus: str) -> None:
    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.sales_line_repo import insert_sales_line
    from data_foundation.repositories.tenant_context import tenant_scope

    file_id = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(
            text("INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                 "VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'c.csv', 1, 'file://x', :by, :at)"),
            {"id": str(file_id), "t": str(tenant), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "by": str(uuid.uuid4()), "at": datetime.now(timezone.utc)},
        )
    run = ingestion_run_repo.insert_ingestion_run(tenant, report_file_id=file_id, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc))
    for i, sku in enumerate(skus, start=1):
        insert_sales_line(tenant, ingestion_run_id=run, marketplace="MEESHO",
                          canonical_fields={"order_ref": f"O{i}", "quantity": 1, "gross_item_amount": 1_000, "taxable_amount": 1_000, "order_date": date(2026, 9, 5), "sku": sku},
                          source_row_number=i, source_row_json={}, confidence="PROVISIONAL")


def feed(tenant):
    from calc_engine.formulas.ledger_feed import ledger_feed
    from calc_engine.repositories import expense_tracker_repo as ledger

    return ledger_feed(ledger.feed_events(tenant, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)), period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                       channel_scope=None, catalog={s: s for s in ledger.known_skus(tenant)})


@pytest.fixture(autouse=True)
def _clean_sales(migrate_engine):
    tables = ("sales_line", "ingestion_run", "report_file")
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


@pytest.fixture
def owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[0])


@pytest.fixture
def other_owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[1])


def new(client, headers, **kw):
    r = client.post(BASE, json={**AD, **kw}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["expenseId"]


def assign(client, headers, eid, basis, shares):
    return client.post(f"{BASE}/{eid}/assign", json={"basis": basis, "shares": shares}, headers=headers)


def test_an_equal_assignment_is_stored_and_the_engine_splits_it_as_manual_sku_level(app_client, owner, two_tenants):
    seed_catalog(two_tenants[0], "A", "B", "C")
    eid = new(app_client, owner)
    r = assign(app_client, owner, eid, "EQUAL", [{"sku": "A"}, {"sku": "B"}, {"sku": "C"}])
    assert r.status_code == 201, r.text
    pool = feed(two_tenants[0]).pools["ADVERTISING"]
    assert {k: v.value for k, v in pool.sku_level.items()} == {"A": 3_334, "B": 3_334, "C": 3_333} and pool.manual_sku_level.value == 10_001 and pool.business_level.value == 0
    d = app_client.get(f"{BASE}/{eid}", headers=owner).json()
    assert d["assignment"] == {"basis": "EQUAL", "shares": [{"sku": "A", "bp": None}, {"sku": "B", "bp": None}, {"sku": "C", "bp": None}]}


def test_ms6_the_summary_totals_are_unchanged_by_an_assignment(app_client, owner, two_tenants):
    seed_catalog(two_tenants[0], "A", "B")
    eid = new(app_client, owner)
    period = {"period_start": "2026-09-01", "period_end": "2026-09-30"}
    before = app_client.post(f"{BASE}/summary", json=period, headers=owner).json()
    assign(app_client, owner, eid, "EXPLICIT_SHARES", [{"sku": "A", "bp": 6_000}, {"sku": "B", "bp": 4_000}])
    after = app_client.post(f"{BASE}/summary", json=period, headers=owner).json()
    assert before["expenseTotal"]["paise"] == after["expenseTotal"]["paise"] == 10_001
    assert [c["paise"] for c in before["byCostClass"]] == [c["paise"] for c in after["byCostClass"]] and before["watermark"] != after["watermark"]


def test_ms2_explicit_shares_below_one_hundred_percent_leave_the_remainder_visible(app_client, owner, two_tenants):
    seed_catalog(two_tenants[0], "A", "B")
    eid = new(app_client, owner, amount_paise=100_000)
    assert assign(app_client, owner, eid, "EXPLICIT_SHARES", [{"sku": "A", "bp": 4_000}, {"sku": "B", "bp": 3_000}]).status_code == 201
    pool = feed(two_tenants[0]).pools["ADVERTISING"]
    assert {k: v.value for k, v in pool.sku_level.items()} == {"A": 40_000, "B": 30_000} and pool.business_level.value == 30_000


def test_ms5_an_unmapped_sku_gets_no_share_and_the_record_is_queued_for_review(app_client, owner, two_tenants):
    seed_catalog(two_tenants[0], "A")
    eid = new(app_client, owner, amount_paise=9_000)
    assert assign(app_client, owner, eid, "EQUAL", [{"sku": "A"}, {"sku": "NOPE"}]).status_code == 201  # accepted; the catalog check is the engine's (Q29)
    f = feed(two_tenants[0])
    assert {k: v.value for k, v in f.pools["ADVERTISING"].sku_level.items()} == {"A": 9_000} and [(i.expense_id, i.reason) for i in f.review_queue] == [(eid, "UNMAPPED_IDENTIFIER")]
    s = app_client.post(f"{BASE}/summary", json={"period_start": "2026-09-01", "period_end": "2026-09-30"}, headers=owner).json()
    assert [(i["expenseId"], i["reason"]) for i in s["reviewQueue"]["items"]] == [(eid, "UNMAPPED_IDENTIFIER")]


@pytest.mark.parametrize(
    "basis,shares,code",
    [
        ("EXPLICIT_SHARES", [{"sku": "A", "bp": 10_001}], "SHARES_ABOVE_100_PERCENT"),  # MS7
        ("EXPLICIT_SHARES", [{"sku": "A", "bp": 6_000}, {"sku": "B", "bp": 4_001}], "SHARES_ABOVE_100_PERCENT"),
        ("EXPLICIT_SHARES", [{"sku": "A", "bp": 0}], "INVALID_ASSIGNMENT"),
        ("EXPLICIT_SHARES", [{"sku": "A"}], "INVALID_ASSIGNMENT"),
        ("EQUAL", [{"sku": "A", "bp": 5_000}], "INVALID_ASSIGNMENT"),
        ("EQUAL", [{"sku": "A"}, {"sku": "A"}], "INVALID_ASSIGNMENT"),
    ],
)
def test_ms7_invalid_assignments_are_rejected_at_entry_and_store_nothing(app_client, owner, two_tenants, basis, shares, code):
    seed_catalog(two_tenants[0], "A", "B")
    eid = new(app_client, owner)
    r = assign(app_client, owner, eid, basis, shares)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert app_client.get(f"{BASE}/{eid}", headers=owner).json()["assignment"] is None and feed(two_tenants[0]).pools["ADVERTISING"].sku_level == {}


@pytest.mark.parametrize("body", [{"basis": "BY_WEIGHT", "shares": [{"sku": "A"}]}, {"basis": "EQUAL", "shares": []}, {"basis": "EQUAL"}, {"shares": [{"sku": "A"}]},
                                  {"basis": "EQUAL", "shares": [{"sku": "A", "bp": 1.5}]}, {"basis": "EQUAL", "shares": [{"sku": "A"}], "tenant_id": "x"},
                                  {"basis": "EQUAL", "shares": [{"sku": f"S{i}"} for i in range(21)]}])
def test_malformed_bodies_are_422(app_client, owner, body):
    eid = new(app_client, owner)
    assert app_client.post(f"{BASE}/{eid}/assign", json=body, headers=owner).status_code == 422


def test_only_advertising_and_storage_records_can_be_assigned(app_client, owner):
    overhead = new(app_client, owner, category="operating_overhead")
    assert assign(app_client, owner, overhead, "EQUAL", [{"sku": "A"}]).status_code == 422
    assert assign(app_client, owner, new(app_client, owner, category="storage"), "EQUAL", [{"sku": "A"}]).status_code == 201


def test_a_voided_record_cannot_be_assigned_and_an_unknown_one_is_404(app_client, owner):
    eid = new(app_client, owner)
    app_client.post(f"{BASE}/{eid}/void", json={"reason": "mistake"}, headers=owner)
    assert assign(app_client, owner, eid, "EQUAL", [{"sku": "A"}]).status_code == 409
    assert assign(app_client, owner, str(uuid.uuid4()), "EQUAL", [{"sku": "A"}]).status_code == 404


def test_a_new_assignment_replaces_the_current_one_and_keeps_the_history(app_client, owner, two_tenants, migrate_engine):
    seed_catalog(two_tenants[0], "A", "B")
    eid = new(app_client, owner)
    assign(app_client, owner, eid, "EQUAL", [{"sku": "A"}])
    assign(app_client, owner, eid, "EQUAL", [{"sku": "B"}])
    assert {k: v.value for k, v in feed(two_tenants[0]).pools["ADVERTISING"].sku_level.items()} == {"B": 10_001}
    from backend.tenant_context import tenant_scope

    with tenant_scope(two_tenants[0]) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_assignment")).scalar_one() == 2  # append-only: nothing overwritten


def test_one_agent_run_per_assignment_and_none_for_a_rejected_one(app_client, owner, two_tenants):
    from backend.tenant_context import tenant_scope

    eid = new(app_client, owner)

    def runs():
        with tenant_scope(two_tenants[0]) as conn:
            return conn.execute(text("SELECT count(*) FROM agent_run WHERE trigger_ref = 'cfo.expense_ledger'")).scalar_one()

    base = runs()
    assign(app_client, owner, eid, "EXPLICIT_SHARES", [{"sku": "A", "bp": 20_000}])
    assert runs() == base
    assign(app_client, owner, eid, "EQUAL", [{"sku": "A"}])
    assert runs() == base + 1


def test_a_partner_without_financials_adjust_cannot_assign(app_client, fake_clerk, two_tenants, owner):
    eid = new(app_client, owner)
    partner = _register_partner_with_permissions(fake_clerk, two_tenants[0], permissions={"agent.cfo": True})
    assert assign(app_client, partner, eid, "EQUAL", [{"sku": "A"}]).status_code == 403
    assert app_client.get(f"{BASE}/{eid}", headers=partner).json()["assignment"] is None


def test_tenants_are_isolated(app_client, owner, other_owner, two_tenants):
    seed_catalog(two_tenants[0], "A")
    eid = new(app_client, owner)
    assert assign(app_client, other_owner, eid, "EQUAL", [{"sku": "A"}]).status_code == 404
    assert feed(two_tenants[1]).pools["ADVERTISING"].sku_level == {}
