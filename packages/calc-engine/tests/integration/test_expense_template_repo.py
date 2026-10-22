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
def test_per_order_and_per_unit_templates_without_a_count_source_make_nothing(two_tenants, kind, reason):
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


# ---- per-order and per-unit templates with the engine's count (section 5.18.2) ----------------------------------------------------------------------------------

from calc_engine.formulas.expense_templates import CountOutcome  # noqa: E402


def per_order(**kw) -> NewTemplate:
    base = dict(kind="PER_ORDER", category="packaging", cost_class="DIRECT", effective_from=date(2026, 1, 1), rate_paise=500)
    base.update(kw)
    return NewTemplate(**base)


def provider(counts: dict, log: list | None = None):
    def get(start, end, per):
        if log is not None:
            log.append((start, end, per))
        return counts.get((start, end), counts.get("default", CountOutcome(None, "ORDERS_UNAVAILABLE", True)))
    return get


def test_pt1_a_per_order_template_makes_rate_times_the_engine_count(two_tenants):
    a, _ = two_tenants
    repo.create(a, per_order(description="Mailer"), created_by=USER)
    log: list = []
    out = repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER, counts=provider({"default": CountOutcome(200, None, True)}, log), today=date(2026, 3, 1))
    assert len(out.created) == 1 and out.skipped == []
    row = rows(a)[0]
    assert (row["amount_paise"], row["review_state"], row["recurring"]) == (100_000, "pending_review", True)  # 200 x Rs 5.00, waiting for the seller
    assert row["description"] == "Mailer: 200 orders x Rs 5.00" and row["effective_date"] == date(2026, 1, 1)
    assert log == [(date(2026, 1, 1), date(2026, 1, 31), "ORDER")]


def test_a_per_unit_template_asks_for_units(two_tenants):
    a, _ = two_tenants
    repo.create(a, per_order(kind="PER_UNIT", rate_paise=250), created_by=USER)
    log: list = []
    repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER, counts=provider({"default": CountOutcome(40, None, True)}, log), today=date(2026, 3, 1))
    assert log[0][2] == "UNIT" and rows(a)[0]["amount_paise"] == 10_000 and "40 units x Rs 2.50" in rows(a)[0]["description"]


def test_pt3_a_true_zero_count_makes_a_real_zero_entry_shown_with_its_count(two_tenants):
    a, _ = two_tenants
    repo.create(a, per_order(), created_by=USER)
    repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER, counts=provider({"default": CountOutcome(0, None, True)}), today=date(2026, 3, 1))
    assert rows(a)[0]["amount_paise"] == 0 and "0 orders x Rs 5.00" in rows(a)[0]["description"]


def test_pt2_pt4_an_unavailable_count_creates_nothing_and_says_why(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, per_order(), created_by=USER)
    for outcome, reason in ((CountOutcome(None, "ORDERS_UNAVAILABLE", True), "ORDERS_UNAVAILABLE"), (CountOutcome(None, "NO_ORDERS_IN_PERIOD", False), "NO_ORDERS_IN_PERIOD")):
        out = repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER, counts=provider({"default": outcome}), today=date(2026, 6, 1))
        assert out.created == [] and out.skipped == [(str(key), reason)]  # once per template, not per month
    assert rows(a) == []


def test_without_a_count_source_nothing_is_made_up(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, per_order(), created_by=USER)
    out = repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER)
    assert out.created == [] and out.skipped == [(str(key), "ORDERS_UNAVAILABLE")] and rows(a) == []


def test_a_month_that_has_not_finished_is_not_priced(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, per_order(), created_by=USER)
    out = repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER, counts=provider({"default": CountOutcome(10, None, True)}), today=date(2026, 2, 10))
    assert [r["effective_date"] for r in rows(a)] == [date(2026, 1, 1)]  # January is finished, February is not
    assert out.skipped == [(str(key), "MONTH_NOT_FINISHED")]


def test_pt5_a_rate_change_mid_month_prices_each_part_at_its_own_rate(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, per_order(effective_from=date(2026, 2, 1), effective_to=date(2026, 2, 14)), created_by=USER)
    repo.new_version(a, key, per_order(effective_from=date(2026, 2, 15), rate_paise=600), created_by=USER)
    counts = {(date(2026, 2, 1), date(2026, 2, 14)): CountOutcome(10, None, True), (date(2026, 2, 15), date(2026, 2, 28)): CountOutcome(20, None, True)}
    log: list = []
    repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER, counts=provider(counts, log), today=date(2026, 6, 1))
    assert [r["amount_paise"] for r in rows(a)] == [17_000]  # 10 x 500 + 20 x 600
    assert log == [(date(2026, 2, 1), date(2026, 2, 14), "ORDER"), (date(2026, 2, 15), date(2026, 2, 28), "ORDER")]
    assert rows(a)[0]["description"] == "10 orders x Rs 5.00 + 20 orders x Rs 6.00"


def test_one_unavailable_part_of_a_month_makes_the_whole_month_unavailable(two_tenants):
    a, _ = two_tenants
    key = repo.create(a, per_order(effective_from=date(2026, 2, 1), effective_to=date(2026, 2, 14)), created_by=USER)
    repo.new_version(a, key, per_order(effective_from=date(2026, 2, 15), rate_paise=600), created_by=USER)
    counts = {(date(2026, 2, 1), date(2026, 2, 14)): CountOutcome(10, None, True), (date(2026, 2, 15), date(2026, 2, 28)): CountOutcome(None, "ORDERS_UNAVAILABLE", True)}
    out = repo.materialise(a, through_month=date(2026, 2, 1), created_by=USER, counts=provider(counts), today=date(2026, 6, 1))
    assert rows(a) == [] and out.skipped == [(str(key), "ORDERS_UNAVAILABLE")]


def test_a_per_order_entry_is_made_once_and_a_voided_one_is_not_recreated(two_tenants):
    a, _ = two_tenants
    repo.create(a, per_order(), created_by=USER)
    c = provider({"default": CountOutcome(5, None, True)})
    repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER, counts=c, today=date(2026, 6, 1))
    again = repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER, counts=provider({"default": CountOutcome(9, None, True)}), today=date(2026, 6, 1))
    assert again.created == [] and again.replayed == 1 and rows(a)[0]["amount_paise"] == 2_500  # the first count stands
    ledger.append_review(a, rows(a)[0]["id"], review_state="voided", reason="wrong", created_by=USER)
    assert repo.materialise(a, through_month=date(2026, 1, 1), created_by=USER, counts=c, today=date(2026, 6, 1)).created == []
