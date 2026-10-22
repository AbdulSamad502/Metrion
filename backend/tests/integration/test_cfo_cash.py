"""Cash view and payables, real Postgres (docs/specs/cfo-phase3-scope.md AC-C1…C6). Golden values are hand-computed.

Meesho history: `HIST` settled lines, each gross 10,000 paise settled at 8,000 (ratio 4/5) after 7 days. Unsettled lines: gross 10,000 -> estimate 8,000."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import text

from calc_engine.repositories import cash_repo
from cfo.planner.cache_store import InMemoryEvidenceCache
from cfo.planner.pipeline import MockPlannerProvider, PlannerAnswer
from cfo.planner.plan import PeriodRef

from backend.services.cfo_query import answer_financial_query
from tests.integration.test_cfo_expense_ledger import _register_owner, app_client, fake_clerk, _seed_zero_cap  # noqa: F401
from tests.integration.test_cfo_query_planner import _file_and_run, plan

USER = uuid.uuid4()
HIST = 12
OCT = PeriodRef(date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 20))  # as_of 20 Oct


def scope(t: uuid.UUID):
    from cfo.repositories.tenant_context import tenant_scope

    return tenant_scope(t)


def add_line(t: uuid.UUID, run: uuid.UUID, ref: str, day: date, gross: int, *, marketplace: str = "MEESHO", line_ref: str | None = None) -> None:
    from data_foundation.repositories.sales_line_repo import insert_sales_line

    insert_sales_line(t, ingestion_run_id=run, marketplace=marketplace,
                      canonical_fields={"order_ref": ref, "line_ref": line_ref if line_ref is not None else ref + "_1", "quantity": 1, "gross_item_amount": gross, "taxable_amount": gross,
                                        "order_date": day, "return_status": "NOT_RETURNED", "sku": "A"},
                      source_row_number=1, source_row_json={}, confidence="PROVISIONAL")


def add_settlement(t: uuid.UUID, run: uuid.UUID, line_ref: str, day: date, amount: int | None, marketplace: str = "MEESHO") -> None:
    from data_foundation.repositories.settlement_line_repo import insert_settlement_line

    insert_settlement_line(t, ingestion_run_id=run, marketplace=marketplace,
                           canonical_fields={"order_ref": line_ref, "line_ref": line_ref, "settlement_id": "S", "currency": "INR", "settlement_date": day,
                                             "gross_settlement_amount": amount, "document_type": None},
                           source_row_number=1, source_row_json={}, confidence="PROVISIONAL")


def seeded(*, hist: int = HIST, unsettled: int = 3, settle_ratio: tuple[int, int] = (8_000, 10_000)) -> uuid.UUID:
    t = uuid.uuid4()
    run = _file_and_run(t)
    for i in range(hist):
        d = date(2026, 9, 1) + timedelta(days=i % 10)
        add_line(t, run, f"H{i}", d, 10_000)
        add_settlement(t, run, f"H{i}_1", d + timedelta(days=7), settle_ratio[0])
    for i in range(unsettled):  # sold early October, not yet settled: expected 8,000 each on doc date + 7 days
        add_line(t, run, f"U{i}", date(2026, 10, 10 + i), 10_000)
    return t


def ask(t: uuid.UUID, metric: str) -> Any:
    r = answer_financial_query(t, requested_by=USER, question="q", periods=[OCT], provider=MockPlannerProvider([plan([{"op": "metric", "params": {"metric": metric}}], periods=[OCT])]),
                               cache=InMemoryEvidenceCache())
    assert isinstance(r, PlannerAnswer), r
    return r.packet


def payable(t: uuid.UUID, amount: int, due: date | None, ref: str = "S1") -> str:
    return cash_repo.add_payable(t, USER, amount_paise=amount, due_date=due, supplier_ref=ref)


# ------------------------------------------------------------------------------------------------ expected receipts
def test_expected_receipts_are_estimates_with_estimate_refs_by_expected_date() -> None:
    t = seeded()
    p = ask(t, "EXPECTED_RECEIPTS")
    by = {dict(f.dimension_keys).get("expected_date", "ALL"): f for f in p.figures}
    # unsettled lines dated 10, 11, 12 Oct + lag 7 -> 17, 18, 19 Oct (all before as_of 20 Oct => OVERDUE: none is a future receipt)
    assert "OVERDUE" in by and by["OVERDUE"].value_paise == 24_000 and by["OVERDUE"].value_count == 3 and "OVERDUE_NOT_COUNTED_AS_COVER" in by["OVERDUE"].labels
    assert all(f.status == "ESTIMATED" and f.estimate_ref and f.engine_result_ref is None for f in p.figures)


def test_future_receipts_are_bucketed_and_overdue_is_never_counted_as_cover() -> None:
    t = seeded(unsettled=0)
    run = _file_and_run(t)
    for i, d in enumerate((date(2026, 10, 15), date(2026, 10, 18), date(2026, 10, 18))):  # doc dates -> expected 22, 25, 25 Oct; as_of 20 Oct
        add_line(t, run, f"F{i}", d, 10_000)
    add_line(t, run, "OLD", date(2026, 10, 2), 10_000)  # expected 9 Oct < as_of: overdue
    p = ask(t, "EXPECTED_RECEIPTS")
    by = {dict(f.dimension_keys).get("expected_date", "ALL"): f for f in p.figures}
    assert by["2026-10-22"].value_paise == 8_000 and by["2026-10-25"].value_paise == 16_000 and by["2026-10-25"].value_count == 2
    assert by["OVERDUE"].value_paise == 8_000
    assert by["ALL"].value_paise == 24_000  # the total is the future receipts only


def test_too_few_settled_lines_means_no_projection_and_it_says_what_is_needed() -> None:
    t = seeded(hist=5)  # fewer than the 10 required
    p = ask(t, "EXPECTED_RECEIPTS")
    f = p.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and "at least 10" in (f.unavailable_reason or "") and len(p.data_requests) == 1


def test_exactly_the_minimum_number_of_settled_lines_projects() -> None:
    t = seeded(hist=10)
    assert ask(t, "EXPECTED_RECEIPTS").figures[0].status == "ESTIMATED"


def test_the_ratio_is_what_the_marketplace_actually_paid_not_a_fixed_rate() -> None:
    t = seeded(settle_ratio=(7_000, 10_000))
    by = {dict(f.dimension_keys).get("expected_date", "ALL"): f for f in ask(t, "EXPECTED_RECEIPTS").figures}
    assert by["OVERDUE"].value_paise == 21_000  # 3 x 7,000


def test_marketplaces_without_a_validated_key_are_named_never_projected() -> None:
    t = seeded()
    run = _file_and_run(t)
    add_line(t, run, "AMZ", date(2026, 10, 18), 99_000, marketplace="AMAZON", line_ref="A1")
    p = ask(t, "EXPECTED_RECEIPTS")
    assert all(f.value_paise != 99_000 for f in p.figures)  # the Amazon line is not projected into anyone's cash
    amazon = [c for c in p.coverage if c.marketplace == "AMAZON"]
    assert amazon and not amazon[0].included and "PARTIAL_MARKETPLACE_COVERAGE" in p.labels  # named, with the reason, by the per-marketplace coverage rule


def test_a_tenant_with_no_data_has_nothing_to_project() -> None:
    f = ask(uuid.uuid4(), "EXPECTED_RECEIPTS").figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None


# ------------------------------------------------------------------------------------------------ shortfall (payables)
def test_each_payable_is_covered_or_at_risk_against_cumulative_expected_receipts() -> None:
    t = seeded(unsettled=0)
    run = _file_and_run(t)
    for i, d in enumerate((date(2026, 10, 15), date(2026, 10, 18))):  # expected 22 and 25 Oct, 8,000 each
        add_line(t, run, f"F{i}", d, 10_000)
    payable(t, 8_000, date(2026, 10, 22), "P1")    # covered exactly (equality)
    payable(t, 8_001, date(2026, 10, 25), "P2")    # cumulative due by 25 Oct = 16,001 vs cover 16,000
    payable(t, 500, None, "P3")                    # no due date
    p = ask(t, "CASH_SHORTFALL_STATUS")
    status = {dict(f.dimension_keys)["payable"]: [lbl for lbl in f.labels if lbl.startswith("SHORTFALL_")][0] for f in p.figures}
    refs = {ref: s for ref, s in status.items()}
    assert sorted(refs.values()) == ["SHORTFALL_AT_RISK", "SHORTFALL_COVERED", "SHORTFALL_UNKNOWN"]
    assert all(f.status == "ESTIMATED" and f.estimate_ref for f in p.figures)


def test_without_any_payable_there_is_nothing_to_compare() -> None:
    t = seeded()
    f = ask(t, "CASH_SHORTFALL_STATUS").figures[0]
    assert f.status == "UNAVAILABLE" and "payable" in (f.unavailable_reason or "")


def test_a_paid_payable_leaves_the_comparison_and_history_stays() -> None:
    t = seeded()
    a = payable(t, 5_000, date(2026, 10, 30), "P1")
    payable(t, 6_000, date(2026, 11, 5), "P2")
    assert len(ask(t, "CASH_SHORTFALL_STATUS").figures) == 2
    cash_repo.mark_paid(t, USER, a)
    assert len(ask(t, "CASH_SHORTFALL_STATUS").figures) == 1
    assert [p.status for p in cash_repo.list_payables(t, include_paid=True) if p.target_ref == a] == ["PAID"]
    with pytest.raises(cash_repo.CashRuleError, match="already marked paid"):
        cash_repo.mark_paid(t, USER, a)
    with pytest.raises(cash_repo.CashRuleError):
        cash_repo.mark_paid(t, USER, "payable:does-not-exist")


def test_payables_are_append_only_validated_and_tenant_isolated() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    ref = payable(a, 5_000, date(2026, 10, 30))
    assert cash_repo.list_payables(b) == []
    with pytest.raises(cash_repo.CashRuleError):
        cash_repo.add_payable(a, USER, amount_paise=0)
    with pytest.raises(cash_repo.CashRuleError):
        cash_repo.mark_paid(b, USER, ref)
    with pytest.raises(Exception, match="permission denied"):
        with scope(a) as conn:
            conn.execute(text("DELETE FROM manual_adjustment"))


def test_the_cash_view_never_reads_a_bank_balance() -> None:
    import inspect

    import backend.services.cfo_planner_backend as b

    src = inspect.getsource(b.PostgresPlannerBackend.run_cash_view)
    assert "bank" not in src.lower()


# ------------------------------------------------------------------------------------------------ routes
def test_payable_routes_gates_and_validation(app_client, fake_clerk, two_tenants, migrate_engine):
    from backend.auth.permissions import AGENT_CFO
    from tests.integration.test_cfo_pnl import _register_partner_with_permissions

    tenant_a, _ = two_tenants
    h = _register_owner(fake_clerk, tenant_a)
    r = app_client.post("/api/v1/cfo/payables", json={"amount_paise": 500_00, "due_date": "2026-10-30", "supplier_ref": "ACME", "po_ref": "PO-1"}, headers=h)
    assert r.status_code == 200, r.text
    ref = r.json()["payableRef"]
    listed = app_client.get("/api/v1/cfo/payables", headers=h).json()["payables"]
    assert [(p["payableRef"], p["amountPaise"], p["status"]) for p in listed] == [(ref, 500_00, "OPEN")]
    assert app_client.post("/api/v1/cfo/payables", json={"amount_paise": 0}, headers=h).status_code == 400
    assert app_client.post("/api/v1/cfo/payables", json={"amount_paise": 5, "balance": 1}, headers=h).status_code == 422
    assert app_client.post(f"/api/v1/cfo/payables/{ref}/paid", headers=h).status_code == 200
    assert app_client.post(f"/api/v1/cfo/payables/{ref}/paid", headers=h).status_code == 400
    assert app_client.get("/api/v1/cfo/payables", headers=h).json()["payables"] == []
    partner = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={AGENT_CFO: True})
    assert app_client.post("/api/v1/cfo/payables", json={"amount_paise": 5}, headers=partner).status_code == 403
    assert app_client.get("/api/v1/cfo/payables", headers=partner).status_code == 200
