"""compute_contribution_margin_pct — docs/specs/anomaly-detection.md §6.1 `MARGIN_PCT`'s real
formula (`deterministic-engine.md` line 352: `ContributionMargin% = ContributionProfit /
NetRealizedRevenue x 100`), E3's one small approved composition function.

Mirrors `test_compute_metric.py`'s own MetricResult-construction style — no CanonicalLine
fixtures needed, since this function consumes two ALREADY-COMPUTED MetricResults directly and
never touches raw lines.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import uuid4

from calc_engine.api.compute_metric import MetricResult, compute_contribution_margin_pct
from calc_engine.types import RecognitionState

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


def test_happy_path_computes_fraction_percentage_not_paise():
    cp = _metric_result(metric_code="CONTRIBUTION_PROFIT", value_paise=25_00, confidence="VERIFIED")
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=100_00, confidence="VERIFIED")

    result = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.metric_code == "CONTRIBUTION_MARGIN_PCT"
    assert result.is_available is True
    assert result.value_paise is None  # never a paise-shaped value for a percentage result
    assert result.value_fraction == Fraction(25, 100) * 100 == Fraction(25)
    assert result.confidence == "VERIFIED"
    assert result.input_refs == (cp.id, nrr.id)
    assert result.formula_version == "CONTRIBUTION_MARGIN_PCT.v1"
    assert "line 352" in result.calculation_basis


def test_negative_contribution_profit_yields_negative_margin_never_floored():
    cp = _metric_result(metric_code="CONTRIBUTION_PROFIT", value_paise=-10_00)
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=50_00)

    result = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is True
    assert result.value_fraction == Fraction(-10, 50) * 100 == Fraction(-20)


def test_nrr_unavailable_propagates():
    cp = _metric_result(metric_code="CONTRIBUTION_PROFIT", value_paise=25_00)
    nrr = _metric_result(
        metric_code="NET_REALIZED_REVENUE",
        value_paise=None,
        is_available=False,
        unavailable_reason="no canonical lines",
    )

    result = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert result.value_paise is None
    assert result.value_fraction is None
    assert result.input_refs == (cp.id, nrr.id)
    assert "NetRealizedRevenue unavailable" in (result.unavailable_reason or "")
    assert "no canonical lines" in (result.unavailable_reason or "")


def test_contribution_profit_unavailable_propagates():
    cp = _metric_result(
        metric_code="CONTRIBUTION_PROFIT",
        value_paise=None,
        is_available=False,
        unavailable_reason="COGS unavailable",
    )
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=100_00)

    result = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert result.value_fraction is None
    assert "ContributionProfit unavailable" in (result.unavailable_reason or "")
    assert "COGS unavailable" in (result.unavailable_reason or "")


def test_both_unavailable_names_both():
    cp = _metric_result(
        metric_code="CONTRIBUTION_PROFIT", value_paise=None, is_available=False, unavailable_reason="reason A"
    )
    nrr = _metric_result(
        metric_code="NET_REALIZED_REVENUE", value_paise=None, is_available=False, unavailable_reason="reason B"
    )

    result = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert "reason A" in (result.unavailable_reason or "")
    assert "reason B" in (result.unavailable_reason or "")


def test_nrr_zero_guard_never_divides_by_zero():
    cp = _metric_result(metric_code="CONTRIBUTION_PROFIT", value_paise=25_00)
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=0)

    result = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    assert result.is_available is False
    assert result.value_paise is None
    assert result.value_fraction is None
    assert "division by zero" in (result.unavailable_reason or "").lower() or "zero" in (
        result.unavailable_reason or ""
    ).lower()


def test_confidence_is_the_weaker_of_the_two_inputs():
    cp = _metric_result(metric_code="CONTRIBUTION_PROFIT", value_paise=25_00, confidence="VERIFIED")
    nrr = _metric_result(metric_code="NET_REALIZED_REVENUE", value_paise=100_00, confidence="MANUAL")

    result = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)

    # MANUAL is the weakest confidence rank (data-foundation.md §7.1) — combine_confidence
    # never lets the total present as more certain than its weakest input.
    assert result.confidence == "MANUAL"
