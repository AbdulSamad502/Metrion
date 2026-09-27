"""Provenance guarantees (AC18/AC23-style, twinkly-mapping-canyon.md CP3): every
`MetricResult`-returning path in `cfo_actions.py` yields an object with a non-null
`engine_result_ref`-equivalent (`.id`); every `GstLineResult` carries its §6.6 disclaimer and
an explicit availability flag.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import uuid4

import pytest
from calc_engine.formulas.cost_components import CostEntry
from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise, RecognitionState

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import GstLineInput, GstLineResult, PeriodPnlRequest, analyze_gst_lines, compute_period_pnl
from cfo.reasoning.prompts import GST_DISCLAIMER

_AS_OF = date(2026, 9, 23)


def _line(*, components: tuple[ComponentRow, ...] = ()) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=1,
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


@pytest.fixture(autouse=True)
def _stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", lambda *a, **k: None)
    monkeypatch.setattr(cfo_actions_module, "insert_data_request", lambda tenant_id, **kwargs: uuid4())
    monkeypatch.setattr(
        cfo_actions_module.config_repo,
        "gst_slabs_effective_on",
        lambda tenant_id, *, as_of_date: [
            {"rate_pct": Fraction(18), "label": "Standard", "effective_from": date(2020, 1, 1), "effective_to": None, "confidence": "PROVISIONAL"}
        ],
    )


def _pnl_request(*, with_cogs: bool) -> PeriodPnlRequest:
    line = _line()
    sku_by_line = {str(line.sales_line_id): "SKU-1"} if with_cogs else {}
    cost_history = (
        {"SKU-1": [CostEntry(amount_paise=Paise(100_00), effective_from=date(2026, 1, 1))]} if with_cogs else {}
    )
    return PeriodPnlRequest(
        lines=[line],
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        as_of_date=_AS_OF,
        recognition_state=RecognitionState.RECOGNISED,
        sku_by_line=sku_by_line,
        cost_history_by_sku=cost_history,
        fee_component_codes=frozenset(),
        forward_logistics_codes=frozenset(),
        reverse_logistics_codes=frozenset(),
        non_refunded_fee_codes=frozenset(),
        advertising_adjustment_values=[],
        other_adjustment_values=[],
        ingestion_run_ids=["run-1"],
        adapter_versions=["v1"],
        active_adjustment_ids=[],
        requested_by=uuid4(),
        computed_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


def test_pnl_results_carry_non_null_engine_result_ref_when_available() -> None:
    outcome = compute_period_pnl(uuid4(), _pnl_request(with_cogs=True))
    assert outcome.nrr.id is not None
    assert outcome.contribution_profit.id is not None
    assert outcome.margin_pct.id is not None
    # anomaly-detection.md §6.1 P2's resolution / RETURN_RATE_PCT — both real, minted
    # engine_result_refs too, not silently omitted from the provenance guarantee.
    assert outcome.fee_ratio_pct.id is not None
    assert outcome.return_rate_pct.id is not None


def test_pnl_results_carry_non_null_engine_result_ref_even_when_unavailable() -> None:
    """Even an UNAVAILABLE MetricResult still carries a minted engine_result_ref — the row is
    never simply absent, it's a persisted UNAVAILABLE record with its own id."""
    outcome = compute_period_pnl(uuid4(), _pnl_request(with_cogs=False))
    assert outcome.contribution_profit.id is not None
    assert outcome.contribution_profit.is_available is False
    # COGS unavailable -> ContributionProfit UNAVAILABLE -> CONTRIBUTION_MARGIN_PCT UNAVAILABLE
    # too (E3's own propagation rule), never a crash and never silently omitted.
    assert outcome.margin_pct.id is not None
    assert outcome.margin_pct.is_available is False
    # FEE_RATIO_PCT/RETURN_RATE_PCT do not depend on COGS — still real, minted
    # engine_result_refs, and still available.
    assert outcome.fee_ratio_pct.id is not None
    assert outcome.fee_ratio_pct.is_available is True
    assert outcome.return_rate_pct.id is not None
    assert outcome.return_rate_pct.is_available is True


def test_gst_line_result_always_carries_disclaimer_and_availability_flag() -> None:
    lines = [
        GstLineInput(line_ref="L1", listed_paise=1180_00, basis="INCLUSIVE", rate_pct=Fraction(18)),
        GstLineInput(line_ref="L2", listed_paise=1000_00, basis="INCLUSIVE", rate_pct=None),
    ]
    results: list[GstLineResult] = analyze_gst_lines(uuid4(), lines, as_of_date=_AS_OF)
    assert len(results) == 2
    for result in results:
        assert result.disclaimer == GST_DISCLAIMER
        assert isinstance(result.is_available, bool)
