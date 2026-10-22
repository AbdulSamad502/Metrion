"""`expense_template_repo` against a real Postgres (kickoff S4b): immutable template versions, materialisation into `pending_review` ledger entries (X10), idempotency,
amortization conservation, per-order/per-unit refusing a made-up amount, and tenant isolation. The amounts come from `formulas/expense_templates.py`."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from calc_engine.formulas.ledger_feed import ledger_feed
from calc_engine.repositories import expense_ledger_repo as ledger
from calc_engine.repositories import expense_template_repo as repo
from calc_engine.repositories.expense_template_repo import NewTemplate

USER = uuid.uuid4()


def monthly(**kw) -> NewTemplate:
    base = dict(kind="MONTHLY", category="software", cost_class="OVERHEAD", effective_from=date(2026, 1, 15), amount_paise=50_000, vendor="Acme SaaS")
    base.update(kw)
    return NewTemplate(**base)


def rows(tenant):
    items, _ = ledger.list_records(tenant, limit=200, include_voided=True)
    return sorted(items, key=lambda r: r["effective_date"])


def test_a_monthly_template_materialises_one_pending_review_entry_per_month(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, monthly(), created_by=USER)
    out = repo.materialise(a, through_month=date(2026, 3, 20), created_by=USER)
    assert len(out.created) == 3 and out.replayed == 0 and out.skipped == []
    got = rows(a)
    assert [r["effective_date"] for r in got] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert {r["review_state"] for r in got} == {"pending_review"}  # X10: nothing recurring is counted until the seller confirms it
    assert {r["amount_paise"] for r in got} == {50_000} and all(r["recurring"] for r in got)
    assert got[0]["source_reference"] == f"template:{key}:2026-01"


def test_pending_entries_are_not_counted_until_confirmed(two_tenants):
    a, _ = two_tenants
    repo.create(a, monthly(), created_by=USER)
    repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER)

    def feed():
        return ledger_feed(ledger.feed_events(a, period_start=date(2026, 1, 1), period_end=date(2026, 2, 28)), period_start=date(2026, 1, 1), period_end=date(2026, 2, 28),
                           channel_scope=None, catalog={})

    before = feed()
    assert before.expense_total.value == 0 and before.pools["OVERHEAD"].total is None and before.review_queue_amount.value == 100_000
    first = rows(a)[0]["id"]
    ledger.append_review(a, first, review_state="confirmed", reason=None, created_by=USER)
    after = feed()
    assert after.expense_total.value == 50_000 and after.recurring_total.value == 50_000


def test_materialising_twice_creates_nothing_twice(two_tenants):
    a, _ = two_tenants
    repo.create(a, monthly(), created_by=USER)
    repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER)
    again = repo.materialise(a, through_month=date(2026, 3, 1), created_by=USER)
    assert len(again.created) == 1 and again.replayed == 2 and len(rows(a)) == 3


def test_a_voided_entry_is_not_silently_recreated(two_tenants):
    a, _ = two_tenants
    repo.create(a, monthly(), created_by=USER)
    repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER)
    ledger.append_review(a, rows(a)[0]["id"], review_state="voided", reason="not needed", created_by=USER)
    again = repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER)
    assert again.created == [] and again.replayed == 1 and rows(a)[0]["review_state"] == "voided"


def test_a_rate_change_is_a_new_version_and_each_month_uses_the_version_in_force(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, monthly(effective_from=date(2026, 1, 1), effective_to=date(2026, 2, 28)), created_by=USER)
    v2 = repo.new_version(a, key, monthly(effective_from=date(2026, 3, 1), amount_paise=70_000), created_by=USER)
    assert v2 == 2 and [v["version"] for v in repo.versions(a, key)] == [1, 2]
    repo.materialise(a, through_month=date(2026, 4, 1), created_by=USER)
    assert [r["amount_paise"] for r in rows(a)] == [50_000, 50_000, 70_000, 70_000]  # earlier months keep version 1
    assert [t["version"] for t in repo.list_current(a)] == [2]


def test_ending_a_template_stops_new_entries_and_leaves_earlier_ones(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, monthly(effective_from=date(2026, 1, 1)), created_by=USER)
    repo.new_version(a, key, monthly(effective_from=date(2026, 1, 1), effective_to=date(2026, 2, 28), ended=True), created_by=USER)
    repo.materialise(a, through_month=date(2026, 6, 1), created_by=USER)
    assert [r["effective_date"] for r in rows(a)] == [date(2026, 1, 1), date(2026, 2, 1)]


def test_an_amortized_template_spreads_the_amount_exactly(two_tenants):
    a, _ = two_tenants
    repo.create(a, NewTemplate(kind="AMORTIZED", category="software", cost_class="OVERHEAD", effective_from=date(2026, 1, 1), amount_paise=100_001, amortization_months=12,
                               start_month=date(2026, 4, 20)), created_by=USER)
    repo.materialise(a, through_month=date(2027, 12, 1), created_by=USER)
    got = rows(a)
    assert len(got) == 12 and got[0]["effective_date"] == date(2026, 4, 1) and got[-1]["effective_date"] == date(2027, 3, 1)
    assert sum(r["amount_paise"] for r in got) == 100_001 and max(r["amount_paise"] for r in got) - min(r["amount_paise"] for r in got) == 1


def test_an_amortized_template_stops_at_the_requested_month_and_continues_later(two_tenants):
    a, _ = two_tenants
    repo.create(a, NewTemplate(kind="AMORTIZED", category="software", cost_class="OVERHEAD", effective_from=date(2026, 1, 1), amount_paise=120_000, amortization_months=4,
                               start_month=date(2026, 1, 1)), created_by=USER)
    repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER)
    assert len(rows(a)) == 2
    repo.materialise(a, through_month=date(2026, 12, 1), created_by=USER)
    assert [r["amount_paise"] for r in rows(a)] == [30_000] * 4


def test_a_manual_sku_tag_on_the_template_carries_to_every_entry(two_tenants):
    a, _ = two_tenants
    repo.create(a, monthly(sku="SKU-9", cost_class="STORAGE", category="storage"), created_by=USER)
    repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER)
    assert {r["sku"] for r in rows(a)} == {"SKU-9"} and {r["origin"] for r in rows(a)} == {"MANUAL"}  # stays a manual tag (Q29)


@pytest.mark.parametrize("kind,reason", [("PER_ORDER", "ORDERS_UNAVAILABLE"), ("PER_UNIT", "UNITS_UNAVAILABLE")])
def test_per_order_and_per_unit_templates_never_materialise_a_made_up_amount(two_tenants, kind, reason):
    a, _ = two_tenants
    key = repo.create(a, NewTemplate(kind=kind, category="packaging", cost_class="DIRECT", effective_from=date(2026, 1, 1), rate_paise=500), created_by=USER)
    out = repo.materialise(a, through_month=date(2026, 3, 1), created_by=USER)
    assert out.created == [] and out.skipped == [(str(key), reason)] and rows(a) == []


def test_the_database_rejects_a_malformed_template(two_tenants, migrate_engine):
    a, _ = two_tenants
    for bad in (
        NewTemplate(kind="MONTHLY", category="software", cost_class="OVERHEAD", effective_from=date(2026, 1, 1)),  # no amount
        NewTemplate(kind="AMORTIZED", category="software", cost_class="OVERHEAD", effective_from=date(2026, 1, 1), amount_paise=1, amortization_months=0, start_month=date(2026, 1, 1)),
        NewTemplate(kind="PER_ORDER", category="packaging", cost_class="DIRECT", effective_from=date(2026, 1, 1), rate_paise=-1),
        NewTemplate(kind="WEEKLY", category="software", cost_class="OVERHEAD", effective_from=date(2026, 1, 1), amount_paise=1),
        monthly(cost_class="NOPE"),
    ):
        with pytest.raises(Exception):
            repo.create(a, bad, created_by=USER)


def test_templates_are_append_only_for_the_application_role(two_tenants, migrate_engine):
    from calc_engine.repositories.tenant_context import tenant_scope

    a, _ = two_tenants
    repo.create(a, monthly(), created_by=USER)
    for sql in ("UPDATE expense_template SET amount_paise = 1", "DELETE FROM expense_template"):
        with pytest.raises(Exception):
            with tenant_scope(a) as conn:
                conn.execute(text(sql))


def test_tenants_are_isolated(two_tenants):
    a, b = two_tenants
    key = repo.create(a, monthly(), created_by=USER)
    repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER)
    assert repo.list_current(b) == [] and repo.versions(b, key) == [] and rows(b) == []
    with pytest.raises(LookupError):
        repo.new_version(b, key, monthly(), created_by=USER)
    assert repo.materialise(b, through_month=date(2026, 1, 1), created_by=USER).created == []
