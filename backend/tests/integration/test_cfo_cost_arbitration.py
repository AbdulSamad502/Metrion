"""Cost-ownership arbitration with real Postgres (docs/specs/cfo-expense-ledger.md D5 / AC-L8): a cost recorded in the Expense Tracker AND the ledger counts once, never twice.

GST: the ledger stores a GST amount beside the cost, and the GST TREATMENT stays unconfirmed (NULL) — it is not settable through the HTTP surface."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import text

from calc_engine.expense_ledger import NewEntry
from calc_engine.formulas.expense_accounting import ExpenseClass
from calc_engine.repositories import cost_owner_repo, expense_ledger_repo as repo
from calc_engine.repositories.manual_adjustment_repo import insert_adjustment

from tests.integration.test_cfo_ads import book, cp
from tests.integration.test_cfo_expense_ledger import _register_owner, app_client, body, e, fake_clerk  # noqa: F401

USER = uuid.uuid4()
SEP_START, SEP_END = date(2026, 9, 1), date(2026, 9, 30)


def packaging_pool(t: uuid.UUID, amount: int) -> None:
    insert_adjustment(t, target_type="PERIOD", target_ref="2026-09", field="expense.packaging", value={"amount_paise": amount}, created_by=USER, created_at=datetime.now(timezone.utc))


def packaging_ledger(t: uuid.UUID, amount: int) -> None:
    repo.add_entries(t, [NewEntry(entry_date=date(2026, 9, 10), amount_paise=amount, category="Packaging", vendor="P")], USER)
    repo.confirm_class(t, klass=ExpenseClass.ALLOCATED_COST, confirmed_by=USER, category="Packaging", allocated_component="PACKAGING")


def test_a_cost_in_both_places_is_counted_once_and_the_seller_choice_flips_which_one() -> None:
    t, _ = book()
    base = cp(t)
    assert base.value_paise is not None
    packaging_pool(t, 20_000)
    pool_only = cp(t)
    assert pool_only.value_paise == base.value_paise - 20_000

    packaging_ledger(t, 7_000)
    both = cp(t)  # unresolved: the established pool keeps counting, the ledger entry is NOT added on top
    assert both.value_paise == base.value_paise - 20_000
    assert any(lbl.startswith("COST_SOURCE_CONFLICT_PACKAGING") for lbl in both.labels)

    cost_owner_repo.choose_owner(t, "PACKAGING", "ALL", SEP_START, SEP_END, "LEDGER", USER)
    ledger_chosen = cp(t)
    assert ledger_chosen.value_paise == base.value_paise - 7_000 and "COSTS_FROM_LEDGER" in ledger_chosen.labels
    assert not any(lbl.startswith("COST_SOURCE_CONFLICT") for lbl in ledger_chosen.labels)

    cost_owner_repo.choose_owner(t, "PACKAGING", "ALL", SEP_START, SEP_END, "POOL", USER)  # a later choice supersedes
    assert cp(t).value_paise == base.value_paise - 20_000


def test_a_ledger_cost_alone_reaches_contribution_profit() -> None:
    t, _ = book()
    base = cp(t)
    packaging_ledger(t, 7_000)
    only_ledger = cp(t)
    assert only_ledger.value_paise == base.value_paise - 7_000 and "COSTS_FROM_LEDGER" in only_ledger.labels


def test_arbitration_choices_are_tenant_isolated() -> None:
    a, _ = book()
    b, _ = book()
    for t in (a, b):
        packaging_pool(t, 20_000)
        packaging_ledger(t, 7_000)
    base_b = cp(b)
    cost_owner_repo.choose_owner(a, "PACKAGING", "ALL", SEP_START, SEP_END, "LEDGER", USER)
    assert cp(b).value_paise == base_b.value_paise  # b's conflict is untouched by a's choice
    assert any(lbl.startswith("COST_SOURCE_CONFLICT_PACKAGING") for lbl in cp(b).labels)


def test_cost_owner_route_validates_and_gates(app_client, fake_clerk, two_tenants):  # noqa: F811
    tenant_a, _ = two_tenants
    h = _register_owner(fake_clerk, tenant_a)
    ok = {"component": "packaging", "period_start": "2026-09-01", "period_end": "2026-09-30", "owner": "ledger"}
    assert app_client.post("/api/v1/cfo/costs/owner", json=ok, headers=h).status_code == 200
    assert app_client.post("/api/v1/cfo/costs/owner", json={**ok, "owner": "WHOEVER"}, headers=h).status_code == 400
    assert app_client.post("/api/v1/cfo/costs/owner", json={**ok, "component": "COGS"}, headers=h).status_code == 400
    assert app_client.post("/api/v1/cfo/costs/owner", json={**ok, "extra": 1}, headers=h).status_code == 422
    assert app_client.post("/api/v1/cfo/costs/owner", json={**ok, "tenant_id": str(tenant_a)}, headers=h).status_code == 422  # a client never supplies a tenant


def test_gst_treatment_is_not_settable_and_stays_unconfirmed(app_client, fake_clerk, two_tenants):  # noqa: F811
    tenant_a, _ = two_tenants
    h = _register_owner(fake_clerk, tenant_a)
    refused = app_client.post("/api/v1/cfo/ledger/entries", json=body(e(1_180_00, "Software", gst_amount_paise=180_00, gst_treatment="INPUT_CREDIT")), headers=h)
    assert refused.status_code == 422
    ok = app_client.post("/api/v1/cfo/ledger/entries", json=body(e(1_180_00, "Software", gst_amount_paise=180_00)), headers=h)
    assert ok.status_code == 200, ok.text
    listed = app_client.get("/api/v1/cfo/ledger/entries", headers=h).json()["entries"]
    assert listed[0]["gstAmountPaise"] == 180_00 and listed[0]["gstTreatment"] is None


def test_database_refuses_an_allocated_entry_without_a_component(migrate_engine) -> None:
    t = uuid.uuid4()
    repo.add_entries(t, [NewEntry(entry_date=date(2026, 9, 10), amount_paise=100, category="Packaging")], USER)
    try:
        repo.confirm_class(t, klass=ExpenseClass.ALLOCATED_COST, confirmed_by=USER, category="Packaging")
    except Exception as exc:  # the repository (or the constraint beneath it) refuses
        assert "which cost" in str(exc) or "allocated" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("an allocated cost without a component must be refused")
    with migrate_engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM expense_class_assignment WHERE tenant_id = :t AND class = 'ALLOCATED_COST' AND state = 'CONFIRMED'"), {"t": str(t)}).scalar_one()
    assert n == 0
