"""compute_marketplace_fees / compute_fee_ratio_pct — anomaly-detection.md §6.1 `FEE_RATIO_PCT`
(P2's resolution). Mirrors `test_compute_contribution_margin_pct.py`'s exact structure and
`MetricResult`-construction helper.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import uuid4

from calc_engine.api.compute_metric import MetricResult, compute_fee_ratio_pct, compute_marketplace_fees
from calc_engine.types import Paise, RecognitionState

_AS_OF = date(2026, 9, 25)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)


def _metric_result(
    *,
    metric_code: str,
    value_paise: int | None,
    is_available: bool = True,
    confidence: str = "VERIFIED",
    unavailable_reason: str | None = None,
    canonical_data_version: str = "cdv-1",
) -> MetricResult:
    return MetricResult(
        id=uuid4(),
        metric_code=metric_code,
        value_paise=value_paise,
        recognition_state=RecognitionState.RECOGNISED if is_available else RecognitionState.UNAVAILABLE,
        confidence=confidence,
        calculation_basis=f"{metric_code} test fixture",
        formula_version=f"{metric_code}.v1",
        canonical_data_version=canonical_data_version,
        as_of_date=_AS_OF,
        input_refs=(),
        exclusions=(),
        computed_at=_COMPUTED_AT,
        is_available=is_available,
        manual_adjustment_set=(),
        unavailable_reason=unavailable_reason,
    )


# --- compute_marketplace_fees --------------------------------------------------------------


def test_compute_marketplace_fees_mints_a_real_engine_result_ref():
    result = compute_marketplace_fees(Paise(50_00), computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.metric_code == "MARKETPLACE_FEES"
    assert result.is_available is True
    assert result.value_paise == 50_00
    assert result.value_fraction is None
    assert result.confidence == "DERIVED"
    assert result.id is not None
    assert result.formula_version == "MARKETPLACE_FEES.v1"


def test_compute_marketplace_fees_never_recomputes_the_sum_it_only_wraps_it():
    # Negative fees (a rare but legitimate correction/refund case) pass through unchanged —
    # this wrapper performs no arithmetic of its own.
    result = compute_marketplace_fees(Paise(-10_00), computed_at=_COMPUTED_AT, as_of_date=_AS_OF)
    assert result.value_paise == -10_00


def test_compute_marketplace_fees_accepts_input_refs_and_confidence_overrides():
    ref = uuid4()
    result = compute_marketplace_fees(
        Paise(10_00),
        computed_at=_COMPUTED_AT,
        as_of_date=_AS_OF,
        input_refs=(ref,),
        confidence="VERIFIED",
    )
    assert result.input_refs == (ref,)
    assert result.confidence == "VERIFIED"


# --- compute_fee_ratio_pct ------------------------------------------------------------------


def test_happy_path_computes_fraction_percentage_not_paise():
    fees = _metric_result(metric_code="MARKETPLACE_FEES", value_paise=10_00, confidence="VERIFIED")
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=100_00, confidence="VERIFIED")

    result = compute_fee_ratio_pct(fees, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.metric_code == "FEE_RATIO_PCT"
    assert result.is_available is True
    assert result.value_paise is None  # never a paise-shaped value for a percentage result
    assert result.value_fraction == Fraction(10, 100) * 100 == Fraction(10)
    assert result.confidence == "VERIFIED"
    assert result.input_refs == (fees.id, nrr.id)
    assert result.formula_version == "FEE_RATIO_PCT.v1"
    assert "MarketplaceFees" in result.calculation_basis


def test_fees_unavailable_propagates():
    fees = _metric_result(
        metric_code="MARKETPLACE_FEES",
        value_paise=None,
        is_available=False,
        unavailable_reason="no fee components in scope",
    )
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=100_00)

    result = compute_fee_ratio_pct(fees, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert result.value_paise is None
    assert result.value_fraction is None
    assert result.input_refs == (fees.id, nrr.id)
    assert "MarketplaceFees unavailable" in (result.unavailable_reason or "")
    assert "no fee components in scope" in (result.unavailable_reason or "")


def test_nrr_unavailable_propagates():
    fees = _metric_result(metric_code="MARKETPLACE_FEES", value_paise=10_00)
    nrr = _metric_result(
        metric_code="NET_REALIZED_REVENUE",
        value_paise=None,
        is_available=False,
        unavailable_reason="no canonical lines",
    )

    result = compute_fee_ratio_pct(fees, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert result.value_fraction is None
    assert "NetRealizedRevenue unavailable" in (result.unavailable_reason or "")
    assert "no canonical lines" in (result.unavailable_reason or "")


def test_both_unavailable_names_both():
    fees = _metric_result(
        metric_code="MARKETPLACE_FEES", value_paise=None, is_available=False, unavailable_reason="reason A"
    )
    nrr = _metric_result(
        metric_code="NET_REALIZED_REVENUE", value_paise=None, is_available=False, unavailable_reason="reason B"
    )

    result = compute_fee_ratio_pct(fees, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert "reason A" in (result.unavailable_reason or "")
    assert "reason B" in (result.unavailable_reason or "")


def test_nrr_zero_guard_never_divides_by_zero():
    fees = _metric_result(metric_code="MARKETPLACE_FEES", value_paise=10_00)
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=0)

    result = compute_fee_ratio_pct(fees, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert result.value_paise is None
    assert result.value_fraction is None
    assert "division by zero" in (result.unavailable_reason or "").lower() or "zero" in (
        result.unavailable_reason or ""
    ).lower()


def test_confidence_is_the_weaker_of_the_two_inputs():
    fees = _metric_result(metric_code="MARKETPLACE_FEES", value_paise=10_00, confidence="VERIFIED")
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=100_00, confidence="MANUAL")

    result = compute_fee_ratio_pct(fees, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    # MANUAL is the weakest confidence rank (data-foundation.md §7.1) — combine_confidence
    # never lets the total present as more certain than its weakest input.
    assert result.confidence == "MANUAL"
