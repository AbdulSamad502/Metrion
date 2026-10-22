"""The proactive CFO risk scan, real Postgres (docs/specs/cfo-phase3-scope.md AC-F1…F5). Rules are deterministic; wording is fixed; figures are references."""

from __future__ import annotations

import re
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

import pytest

from calc_engine.expense_ledger import NewEntry
from calc_engine.repositories import ad_report_repo, expense_ledger_repo as ledger, leak_claim_repo
from calc_engine.repositories import read_model_version_repo as rmv
from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
from cfo.repositories import leak_finding_repo

from backend.repositories import shared_finding_repo
from backend.services import cfo_risk_scan as scan
from tests.integration.test_cfo_ads import ad_lines, pool
from tests.integration.test_cfo_expense_ledger import _register_owner, app_client, fake_clerk, _seed_zero_cap  # noqa: F401
from tests.integration.test_cfo_leak_claims import finding as make_leak
from tests.integration.test_cfo_query_planner import _cogs, _file_and_run, _line

USER = uuid.uuid4()
AS_OF = date(2026, 10, 22)  # scan periods: September (latest complete month) vs August


def month_book(*, aug_fee: int = 2_500, sep_fee: int = 15_000, with_aug: bool = True) -> uuid.UUID:
    """Four Meesho lines per month, gross 50,000, qty 2, cost 4,000: Aug margin 79%, Sep margin 54% with the default fees."""
    t = uuid.uuid4()
    run = _file_and_run(t)
    _cogs(t, "A", 4_000)
    if with_aug:
        for d in (3, 4, 5, 6):
            _line(t, run, day=date(2026, 8, d), sku="A", gross=50_000, fee=aug_fee)
    for d in (3, 4, 5, 6):
        _line(t, run, day=date(2026, 9, d), sku="A", gross=50_000, fee=sep_fee)
    return t


def active(t: uuid.UUID) -> list[dict[str, Any]]:
    return shared_finding_repo.list_active(t)


def rules(r: scan.ScanResult) -> set[str]:
    return {s.rule for s in r.signals}


# ------------------------------------------------------------------------------------------------ margin drop
def test_a_margin_drop_is_recorded_as_a_margin_finding_citing_both_engine_results_with_digit_free_text() -> None:
    t = month_book()
    r = scan.run_scan(t, USER, AS_OF)
    sig = next(s for s in r.signals if s.rule == "MARGIN_DROP")
    assert sig.kind == "MARGIN_ISSUE" and sig.severity == "HIGH" and sig.persisted and len(sig.figure_refs) == 2  # 79% -> 54%: 25 points
    row = next(f for f in active(t) if f["kind"] == "MARGIN_ISSUE")
    assert row["trust"] == "ENGINE_VERIFIED" and not re.search(r"\d", row["text"]) and len(row["figure_refs"]) == 2 and row["agent_code"] == "CFO"


def test_scanning_the_same_data_again_adds_nothing_and_new_data_scans_again() -> None:
    t = month_book()
    first = scan.run_scan(t, USER, AS_OF)
    again = scan.run_scan(t, USER, AS_OF)
    assert first.recorded >= 1 and again.recorded == 0 and again.already_recorded == first.recorded + first.already_recorded
    assert len([f for f in active(t) if f["kind"] == "MARGIN_ISSUE"]) == 1
    rmv.bump(t)  # a change in the data: the same condition is a new finding for the new version
    third = scan.run_scan(t, USER, AS_OF)
    assert third.recorded >= 1 and len([f for f in active(t) if f["kind"] == "MARGIN_ISSUE"]) == 2


def test_no_signal_when_the_margin_holds_or_rises() -> None:
    t = month_book(aug_fee=15_000, sep_fee=15_000)
    r = scan.run_scan(t, USER, AS_OF)
    assert "MARGIN_DROP" not in rules(r) and not any(s.rule == "MARGIN_DROP" for s in r.signals)
    t2 = month_book(aug_fee=15_000, sep_fee=2_500)
    assert "MARGIN_DROP" not in rules(scan.run_scan(t2, USER, AS_OF))


def test_a_missing_previous_month_means_the_rule_could_not_run_and_says_so() -> None:
    t = month_book(with_aug=False)
    r = scan.run_scan(t, USER, AS_OF)
    assert "MARGIN_DROP" not in rules(r) and any(rule == "MARGIN_DROP" for rule, _ in r.not_run)


# ------------------------------------------------------------------------------------------------ stale / missing data
def test_stale_data_fires_past_the_threshold_and_not_within_it() -> None:
    t = month_book()
    assert "STALE_DATA" in rules(scan.run_scan(t, USER, AS_OF))  # newest document 6 Sep, 46 days before 22 Oct
    fresh = scan.run_scan(t, USER, date(2026, 9, 20))  # 14 days after 6 Sep: equality is not stale
    assert "STALE_DATA" not in rules(fresh)
    assert "STALE_DATA" in rules(scan.run_scan(t, USER, date(2026, 9, 21)))


def test_a_tenant_with_no_order_data_is_told_so_never_shown_a_zero() -> None:
    t = uuid.uuid4()
    r = scan.run_scan(t, USER, AS_OF)
    sig = next(s for s in r.signals if s.rule == "STALE_DATA")
    assert sig.severity == "HIGH" and sig.text == scan.T_NO_DATA and sig.figure_refs == () and sig.persisted
    assert [f["kind"] for f in active(t)] == ["DATA_GAP"]


# ------------------------------------------------------------------------------------------------ other rules
def test_unconfirmed_expenses_are_flagged_citing_the_provisional_operating_profit() -> None:
    t = month_book(aug_fee=15_000, sep_fee=15_000)
    ledger.add_entries(t, [NewEntry(entry_date=date(2026, 9, 10), amount_paise=30_000, category="Misc", vendor="V")], USER)
    r = scan.run_scan(t, USER, AS_OF)
    sig = next(s for s in r.signals if s.rule == "EXPENSES_UNCONFIRMED")
    assert sig.kind == "DATA_GAP" and sig.persisted and len(sig.figure_refs) == 1
    ledger.confirm_class(t, klass=__import__("calc_engine.formulas.expense_accounting", fromlist=["ExpenseClass"]).ExpenseClass.OVERHEAD, confirmed_by=USER, category="Misc")
    assert "EXPENSES_UNCONFIRMED" not in rules(scan.run_scan(t, USER, AS_OF))


def test_an_advertising_source_conflict_is_flagged_until_the_seller_chooses() -> None:
    t = month_book(aug_fee=15_000, sep_fee=15_000)
    run = _file_and_run(t)
    ad_lines(t, run)
    pool(t, 20_000)
    assert "AD_SOURCE_CONFLICT" in rules(scan.run_scan(t, USER, AS_OF))
    ad_report_repo.choose_owner(t, "MEESHO", date(2026, 9, 1), date(2026, 9, 30), "REPORT", USER)
    assert "AD_SOURCE_CONFLICT" not in rules(scan.run_scan(t, USER, AS_OF))


def test_a_closing_claim_window_is_flagged_unless_the_seller_already_raised_it_and_never_for_amazon() -> None:
    t = month_book(aug_fee=15_000, sep_fee=15_000)
    f = make_leak(t)
    other = make_leak(t, marketplace="AMAZON", order="AMZ-1", line="AMZ-1_1")
    from sqlalchemy import text
    from cfo.repositories.tenant_context import tenant_scope

    from calc_engine.api.compute_metric import mint_set_based_result
    from calc_engine.repositories import metric_result_repo

    res = mint_set_based_result("LEAK_AGGREGATE", 5_000, data_version=1, computed_at=datetime.now(timezone.utc))
    metric_result_repo.save(t, res, grain="TENANT_PERIOD", target_ref=str(t), period="2026-10", config_version="T")
    with tenant_scope(t) as conn:  # the window status and the engine result are inputs the reconciliation wrote; set them as it would
        conn.execute(text("UPDATE leak_finding SET window_status = 'CLOSING_SOON', engine_result_ref = :r WHERE tenant_id = :t"), {"t": str(t), "r": str(res.id)})
    r = scan.run_scan(t, USER, AS_OF)
    closing = [s for s in r.signals if s.rule == "LEAK_WINDOW_CLOSING"]
    assert [s.scope for s in closing] == [str(f)] and closing[0].kind == "LEAK_FOUND" and closing[0].persisted and str(other) not in [s.scope for s in closing]
    for step in ("ACKNOWLEDGED", "CLAIM_DRAFTED", "SELLER_REPORTED_RAISED"):
        leak_claim_repo.transition(t, f, step, USER)
    assert "LEAK_WINDOW_CLOSING" not in rules(scan.run_scan(t, USER, AS_OF))


def test_cash_at_risk_is_computed_and_returned_but_not_persisted() -> None:
    from tests.integration.test_cfo_cash import payable, seeded

    t = seeded()
    payable(t, 5_000, date(2026, 10, 30), "P1")
    r = scan.run_scan(t, USER, AS_OF)
    cash = [s for s in r.signals if s.rule == "CASH_AT_RISK"]
    assert len(cash) == 1 and cash[0].severity == "HIGH" and not cash[0].persisted and cash[0].figure_refs
    assert not any("CASH" in str(f["kind"]) for f in active(t))


# ------------------------------------------------------------------------------------------------ safety
def test_signals_never_leak_across_tenants_and_a_scan_needs_a_tenant() -> None:
    a, b = month_book(), uuid.uuid4()
    scan.run_scan(a, USER, AS_OF)
    assert [f for f in active(b) if f["kind"] == "MARGIN_ISSUE"] == []
    with pytest.raises(ValueError):
        scan.run_scan(None, USER, AS_OF)  # type: ignore[arg-type]


def test_every_template_is_digit_free_and_free_of_money_words() -> None:
    for t_ in (scan.T_MARGIN, scan.T_STALE, scan.T_NO_DATA, scan.T_EXPENSES, scan.T_AD_CONFLICT, scan.T_LEAK_CLOSING):
        assert not re.search(r"\d", t_) and not re.search(r"recover|refund|rupee|₹", t_, re.IGNORECASE)


def test_the_after_change_hook_is_off_by_default_and_never_breaks_the_write(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[uuid.UUID] = []
    done = threading.Event()

    def fake(tenant: uuid.UUID, requested_by: uuid.UUID, as_of: date) -> None:
        called.append(tenant)
        done.set()
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(scan, "run_scan", fake)
    monkeypatch.delenv("CFO_RISK_SCAN_ON_CHANGE", raising=False)
    assert scan.scan_in_background(uuid.uuid4()) is False and called == []
    monkeypatch.setenv("CFO_RISK_SCAN_ON_CHANGE", "true")
    t = uuid.uuid4()
    assert scan.scan_in_background(t) is True and done.wait(5) and called == [t]  # the thread ran; its failure was swallowed


def test_route_runs_the_scan_with_gates(app_client, fake_clerk, two_tenants, migrate_engine):
    from backend.auth.permissions import AGENT_CFO
    from tests.integration.test_cfo_pnl import _register_partner_with_permissions

    tenant_a, _ = two_tenants
    h = _register_owner(fake_clerk, tenant_a)
    r = app_client.post("/api/v1/cfo/risk-scan", json={"as_of_date": "2026-10-22"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asOfDate"] == "2026-10-22" and any(s["rule"] == "STALE_DATA" for s in body["signals"]) and body["recorded"] >= 1
    assert app_client.post("/api/v1/cfo/risk-scan", json={"as_of_date": "2026-10-22", "extra": 1}, headers=h).status_code == 422
    partner = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={AGENT_CFO: True})
    assert app_client.post("/api/v1/cfo/risk-scan", json={"as_of_date": "2026-10-22"}, headers=partner).status_code == 403
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.risk_scan")
    assert app_client.post("/api/v1/cfo/risk-scan", json={"as_of_date": "2026-10-22"}, headers=h).status_code == 402


def test_a_signal_whose_cited_result_does_not_resolve_is_reported_not_recorded_and_the_scan_continues() -> None:
    t = month_book(aug_fee=15_000, sep_fee=15_000)
    make_leak(t)  # its engine_result_ref points at nothing
    from sqlalchemy import text
    from cfo.repositories.tenant_context import tenant_scope

    with tenant_scope(t) as conn:
        conn.execute(text("UPDATE leak_finding SET window_status = 'CLOSING_SOON' WHERE tenant_id = :t"), {"t": str(t)})
    r = scan.run_scan(t, USER, AS_OF)
    assert any(rule == "LEAK_WINDOW_CLOSING" and "could not be recorded" in why for rule, why in r.not_run) and "STALE_DATA" in rules(r)
