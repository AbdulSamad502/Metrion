"""`backend.services.cfo_actions.compute_period_pnl` — end-to-end at the unit level, real
engine functions, constructed `CanonicalLine`s. The one DB-touching call this composition
makes when COGS is missing (`cfo.repositories.agent_data_request_repo.insert`, imported into
`cfo_actions` as `insert_data_request`) is monkeypatched — no live Postgres in this session
(see conftest `no_live_db` fixture note in the test bodies below).

Covers: both MetricResults carry engineResultRef/confidence/basis; missing COGS triggers
exactly one agent_data_request (E2); TCS/TDS never appear in CP inputs (AC9, checked by
construction — the six `compute_contribution_profit` keyword inputs this module assembles
are enumerated and none of them is fed from a TCS/TDS-named component code anywhere in
`cfo.pnl.inputs`); `CONTRIBUTION_MARGIN_PCT` is composed from the already-computed
`CONTRIBUTION_PROFIT`/`NET_REALIZED_REVENUE` results (E3's `compute_contribution_margin_pct`,
now wired into this production flow) and persisted via the same `metric_result_repo.save`
TENANT_PERIOD shape those two already use — happy path AND the COGS-unavailable propagation.

Also covers `FEE_RATIO_PCT` (anomaly-detection.md §6.1 P2's resolution — `MARKETPLACE_FEES` now
gets a real `engine_result_ref` via `compute_marketplace_fees`, and `FEE_RATIO_PCT` composes
from it + `nrr_result`) and `RETURN_RATE_PCT` (a fresh per-period computation directly over
`request.lines`, not a composition of two prior results) — both persisted with the SAME
TENANT_PERIOD grain/target_ref/period as every other figure this function computes.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from calc_engine.formulas.cost_components import CostEntry
from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise, RecognitionState

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import PeriodPnlRequest, compute_period_pnl

_AS_OF = date(2026, 9, 23)


def _line(*, quantity: int = 2, components: tuple[ComponentRow, ...] = ()) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=quantity,
        invoice_date=_AS_OF,
        dispatch_date=_AS_OF,
        order_date=_AS_OF,
        gross_item_amount=Paise(1_000_00),
        components=components,
        confidence=Confidence.VERIFIED,
        cancellation_state="NOT_CANCELLED",
        return_status="DELIVERED",
        rto_status="NOT_RTO",
    )


def _component(*, kind: str, code: str, amount_paise: int, side: str = "INVOICE") -> ComponentRow:
    return ComponentRow(id=uuid4(), component_kind=kind, component_code=code, source_side=side, amount=Paise(amount_paise))


def _base_request(*, lines, sku_by_line, cost_history_by_sku) -> PeriodPnlRequest:
    return PeriodPnlRequest(
        lines=lines,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        as_of_date=_AS_OF,
        recognition_state=RecognitionState.RECOGNISED,
        sku_by_line=sku_by_line,
        cost_history_by_sku=cost_history_by_sku,
        fee_component_codes=frozenset({"COMMISSION"}),
        forward_logistics_codes=frozenset(),
        reverse_logistics_codes=frozenset(),
        non_refunded_fee_codes=frozenset(),
        advertising_adjustment_values=[],
        other_adjustment_values=[],
        ingestion_run_ids=["run-1"],
        adapter_versions=["meesho.v1"],
        active_adjustment_ids=[],
        requested_by=uuid4(),
        computed_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def _stub_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """`metric_result_repo.save` also opens a real DB connection — no live Postgres in this
    session, so persistence is stubbed to a no-op for these unit-level composition tests.
    (`cfo_actions.py`'s own module docstring is explicit that no arithmetic happens here;
    this fixture only removes the DB round-trip, not any logic under test.)"""
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", lambda *a, **k: None)


def test_pnl_with_full_inputs_both_results_carry_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    line = _line(components=(_component(kind="FEE", code="COMMISSION", amount_paise=50_00),))
    sku = "SKU-1"
    request = _base_request(
        lines=[line],
        sku_by_line={str(line.sales_line_id): sku},
        cost_history_by_sku={sku: [CostEntry(amount_paise=Paise(100_00), effective_from=date(2026, 1, 1))]},
    )

    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = compute_period_pnl(uuid4(), request)

    for result in (
        outcome.nrr,
        outcome.contribution_profit,
        outcome.margin_pct,
        outcome.fee_ratio_pct,
        outcome.return_rate_pct,
    ):
        assert result.id is not None  # engine_result_ref
        assert result.confidence is not None
        assert result.calculation_basis
    assert outcome.contribution_profit.is_available
    assert outcome.data_request_id is None
    assert captured_requests == []

    # E3's compute_contribution_margin_pct, now wired into production: a real
    # CONTRIBUTION_MARGIN_PCT figure, not just a test-seeded row.
    assert outcome.margin_pct.metric_code == "CONTRIBUTION_MARGIN_PCT"
    assert outcome.margin_pct.is_available is True
    assert outcome.margin_pct.value_paise is None  # a percentage, never paise-shaped
    assert outcome.margin_pct.value_fraction is not None
    assert outcome.margin_pct.input_refs == (outcome.contribution_profit.id, outcome.nrr.id)

    # anomaly-detection.md §6.1 P2's resolution, now wired into production: FEE_RATIO_PCT
    # composes from a real MARKETPLACE_FEES engine_result_ref + the already-computed nrr_result.
    assert outcome.fee_ratio_pct.metric_code == "FEE_RATIO_PCT"
    assert outcome.fee_ratio_pct.is_available is True
    assert outcome.fee_ratio_pct.value_paise is None
    assert outcome.fee_ratio_pct.value_fraction is not None
    assert outcome.fee_ratio_pct.input_refs[1] == outcome.nrr.id

    # RETURN_RATE_PCT — a fresh per-period computation directly over request.lines, never a
    # composition of two prior results.
    assert outcome.return_rate_pct.metric_code == "RETURN_RATE_PCT"
    assert outcome.return_rate_pct.is_available is True
    assert outcome.return_rate_pct.value_paise is None
    assert outcome.return_rate_pct.value_fraction is not None
    assert outcome.return_rate_pct.input_refs == (line.sales_line_id,)


def test_missing_cogs_yields_unavailable_cp_and_exactly_one_data_request(monkeypatch: pytest.MonkeyPatch) -> None:
    line = _line()
    request = _base_request(
        lines=[line],
        sku_by_line={},  # no SKU mapping at all -> COGS Unavailable (E9)
        cost_history_by_sku={},
    )

    captured_requests: list[dict[str, object]] = []

    def _fake_insert(tenant_id, **kwargs):
        captured_requests.append(kwargs)
        return uuid4()

    monkeypatch.setattr(cfo_actions_module, "insert_data_request", _fake_insert)

    outcome = compute_period_pnl(uuid4(), request)

    assert outcome.contribution_profit.is_available is False
    assert outcome.contribution_profit.value_paise is None
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["requested_field"] == "cogs_per_unit"
    assert captured_requests[0]["blocking_metric"] == "CONTRIBUTION_PROFIT"
    # never a silent zero: NRR itself is unaffected (it does not need COGS), only CP is UNAVAILABLE
    assert outcome.nrr.is_available is True

    # CONTRIBUTION_PROFIT unavailable propagates one step further into CONTRIBUTION_MARGIN_PCT
    # (E3's own propagation rule) — a crash-free UNAVAILABLE result, never silently omitted from
    # the outcome, and never a guessed/zero margin.
    assert outcome.margin_pct.metric_code == "CONTRIBUTION_MARGIN_PCT"
    assert outcome.margin_pct.is_available is False
    assert outcome.margin_pct.value_fraction is None
    assert "ContributionProfit unavailable" in (outcome.margin_pct.unavailable_reason or "")

    # FEE_RATIO_PCT and RETURN_RATE_PCT do not depend on COGS at all (neither
    # MarketplaceFees/NetRealizedRevenue nor the line-level quantity/returned_qty/rto_qty
    # fields need a SKU cost lookup) — a missing COGS never drags either of them down with CP.
    assert outcome.fee_ratio_pct.is_available is True
    assert outcome.return_rate_pct.is_available is True


def test_margin_pct_is_persisted_with_the_same_tenant_period_shape_as_nrr_and_cp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line = _line(components=(_component(kind="FEE", code="COMMISSION", amount_paise=50_00),))
    sku = "SKU-1"
    request = _base_request(
        lines=[line],
        sku_by_line={str(line.sales_line_id): sku},
        cost_history_by_sku={sku: [CostEntry(amount_paise=Paise(100_00), effective_from=date(2026, 1, 1))]},
    )

    saved_calls: list[dict[str, object]] = []

    def _fake_save(tenant_id, result, *, grain, target_ref, period, config_version, is_trial=False):
        saved_calls.append(
            {
                "tenant_id": tenant_id,
                "metric_code": result.metric_code,
                "grain": grain,
                "target_ref": target_ref,
                "period": period,
                "config_version": config_version,
            }
        )
        return uuid4()

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", _fake_save)

    tenant_id = uuid4()
    outcome = compute_period_pnl(tenant_id, request)

    margin_saves = [c for c in saved_calls if c["metric_code"] == "CONTRIBUTION_MARGIN_PCT"]
    nrr_saves = [c for c in saved_calls if c["metric_code"] == "NET_REALIZED_REVENUE"]
    cp_saves = [c for c in saved_calls if c["metric_code"] == "CONTRIBUTION_PROFIT"]
    fees_saves = [c for c in saved_calls if c["metric_code"] == "MARKETPLACE_FEES"]
    fee_ratio_saves = [c for c in saved_calls if c["metric_code"] == "FEE_RATIO_PCT"]
    return_rate_saves = [c for c in saved_calls if c["metric_code"] == "RETURN_RATE_PCT"]

    assert len(margin_saves) == 1
    margin_save = margin_saves[0]
    assert margin_save["tenant_id"] == tenant_id
    assert margin_save["grain"] == "TENANT_PERIOD"
    assert margin_save["target_ref"] == str(tenant_id)
    assert margin_save["period"] == "2026-09-01/2026-09-30"

    # Same grain/target_ref/period/config_version as the NRR and CP rows this function already
    # persists — CONTRIBUTION_MARGIN_PCT is not a differently-shaped surface, and neither are
    # MARKETPLACE_FEES/FEE_RATIO_PCT/RETURN_RATE_PCT (this checkpoint's new figures).
    assert len(nrr_saves) == 1 and len(cp_saves) == 1
    assert len(fees_saves) == 1 and len(fee_ratio_saves) == 1 and len(return_rate_saves) == 1
    for other in (nrr_saves[0], cp_saves[0], fees_saves[0], fee_ratio_saves[0], return_rate_saves[0]):
        assert other["grain"] == margin_save["grain"]
        assert other["target_ref"] == margin_save["target_ref"]
        assert other["period"] == margin_save["period"]
        assert other["config_version"] == margin_save["config_version"]

    assert outcome.margin_pct.metric_code == "CONTRIBUTION_MARGIN_PCT"


def test_tcs_tds_never_appear_in_contribution_profit_inputs() -> None:
    """AC9 — checked by construction: `compute_contribution_profit`'s six cost keyword
    arguments this module assembles (`cogs`, `marketplace_fees`, `shipping_logistics`,
    `advertising_costs`, `return_rto_losses`, `other_allocated_costs`) are each resolved by a
    named `cfo.pnl.inputs` function; none of those functions' source ever references a
    TCS/TDS-named component code or field."""
    import inspect

    from cfo.pnl import inputs as pnl_inputs

    source = inspect.getsource(pnl_inputs)
    for forbidden in ("TCS", "TDS"):
        assert forbidden not in source, f"{forbidden} must never be read into a CP input (AC9)"

    # And directly on the composition root itself.
    cfo_actions_source = inspect.getsource(cfo_actions_module)
    for forbidden in ("TCS", "TDS"):
        assert forbidden not in cfo_actions_source


# --- ST-01: display-only "was advertising entered?" (docs/specs/expense-tracker.md Appendix D) ---
# The two additive outcome fields must never change any figure: ContributionProfit is
# numerically identical whether advertising was absent, an explicit zero, or (for the non-zero
# case) reduced by exactly the entered amount.


def _adv_request(advertising: list[dict[str, object]]) -> PeriodPnlRequest:
    line = _line(components=(_component(kind="FEE", code="COMMISSION", amount_paise=50_00),))
    sku = "SKU-1"
    request = _base_request(
        lines=[line],
        sku_by_line={str(line.sales_line_id): sku},
        cost_history_by_sku={sku: [CostEntry(amount_paise=Paise(100_00), effective_from=date(2026, 1, 1))]},
    )
    return _replace_adv(request, advertising)


def _replace_adv(request: PeriodPnlRequest, advertising: list[dict[str, object]]) -> PeriodPnlRequest:
    import dataclasses

    return dataclasses.replace(request, advertising_adjustment_values=advertising)


def test_absent_advertising_is_reported_as_not_entered_and_value_is_unchanged() -> None:
    outcome = compute_period_pnl(uuid4(), _replace_adv(_adv_request([]), []))
    assert outcome.advertising_entered is False
    assert outcome.advertising_costs_paise is None
    assert outcome.contribution_profit.is_available


def test_explicit_zero_advertising_is_entered_and_contribution_profit_is_identical() -> None:
    absent = compute_period_pnl(uuid4(), _replace_adv(_adv_request([]), []))
    zero = compute_period_pnl(uuid4(), _replace_adv(_adv_request([]), [{"amount_paise": 0}]))
    assert zero.advertising_entered is True
    assert zero.advertising_costs_paise == 0
    assert zero.contribution_profit.value_paise == absent.contribution_profit.value_paise
    assert zero.margin_pct.value_fraction == absent.margin_pct.value_fraction


def test_nonzero_advertising_is_entered_and_reduces_contribution_profit_by_exactly_the_amount() -> None:
    absent = compute_period_pnl(uuid4(), _replace_adv(_adv_request([]), []))
    entered = compute_period_pnl(uuid4(), _replace_adv(_adv_request([]), [{"amount_paise": 4_500}, {"amount_paise": 500}]))
    assert entered.advertising_entered is True
    assert entered.advertising_costs_paise == 5_000
    assert absent.contribution_profit.value_paise - entered.contribution_profit.value_paise == 5_000
