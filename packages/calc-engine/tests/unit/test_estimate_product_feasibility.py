"""estimate_product_feasibility() — deterministic-engine.md §5.13.2. PI-exclusive.

Checkpoint 2's own sanity tests: one test per §5.13.2 rule this module implements. The full
systematic suite (narration-safety interplay, hypothesis-based property tests, etc.) is a
later checkpoint's job, per the PI build plan.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import UUID, uuid4

from calc_engine.api.compute_metric import MetricResult
from calc_engine.api.estimate_product_feasibility import (
    ProductFeasibilityEstimate,
    ProspectiveObservationSet,
    estimate_product_feasibility,
)
from calc_engine.formulas.fee_resolution import FeeReference
from calc_engine.types import Confidence, Paise, Unavailable

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
TENANT_ID = uuid4()


def _fee_reference(**overrides: object) -> FeeReference:
    base: dict[str, object] = dict(
        rate_pct=Fraction(10),
        rate_low_pct=None,
        rate_high_pct=None,
        source="Amazon Seller Central fee schedule",
        confidence="VERIFIED",
        version=3,
    )
    base.update(overrides)
    return FeeReference(**base)  # type: ignore[arg-type]


def _observation(**overrides: object) -> ProspectiveObservationSet:
    base: dict[str, object] = dict(
        marketplace="AMAZON",
        category="kitchen",
        candidate_prices=(Paise(50_000), Paise(70_000)),
        stated_cogs_paise=None,
        budget_paise=Paise(500_000),
        as_of_date=date(2026, 9, 30),
        source_url="https://example.com/candidate",
        fetched_at=NOW,
    )
    base.update(overrides)
    return ProspectiveObservationSet(**base)  # type: ignore[arg-type]


# --- rule 6: STATED vs UNKNOWN cogs_basis -------------------------------------------------


def test_stated_cogs_produces_stated_basis_and_subtracts_cogs():
    observation = _observation(stated_cogs_paise=Paise(20_000))
    result = estimate_product_feasibility(
        observation, fee_reference=_fee_reference(), tenant_id=TENANT_ID, computed_at=NOW
    )

    assert result.cogs_basis == "STATED"
    # price=50000, fee=10%*50000=5000, cogs=20000 -> net=25000 (lowest of the two prices' net-low)
    # price=70000, fee=10%*70000=7000, cogs=20000 -> net=43000 (highest of the two prices' net-high)
    assert result.low_paise == Paise(25_000)
    assert result.high_paise == Paise(43_000)
    assert any("margin estimate" in a and "IS a margin" in a for a in result.assumptions)


def test_unknown_cogs_basis_never_subtracts_cogs_and_names_the_gap():
    observation = _observation(stated_cogs_paise=None)
    result = estimate_product_feasibility(
        observation, fee_reference=_fee_reference(), tenant_id=TENANT_ID, computed_at=NOW
    )

    assert result.cogs_basis == "UNKNOWN"
    # price=50000, fee=5000 -> net=45000; price=70000, fee=7000 -> net=63000.
    assert result.low_paise == Paise(45_000)
    assert result.high_paise == Paise(63_000)
    assert any("NOT a margin estimate" in a for a in result.assumptions)


# --- rule 2: missing / range-only fee_reference widens the range, gap named ----------------


def test_missing_fee_reference_widens_range_and_names_the_gap():
    observation = _observation(stated_cogs_paise=Paise(20_000), candidate_prices=(Paise(50_000),))
    unavailable_fee = Unavailable(reason="no fee_reference row for AMAZON/kitchen/COMMISSION")

    result_missing = estimate_product_feasibility(
        observation, fee_reference=unavailable_fee, tenant_id=TENANT_ID, computed_at=NOW
    )
    result_resolved = estimate_product_feasibility(
        observation, fee_reference=_fee_reference(), tenant_id=TENANT_ID, computed_at=NOW
    )

    # No fee subtracted at all -> a strictly higher (wider, never suppressed) figure than the
    # resolved-fee case, for both ends of the range.
    assert result_missing.low_paise > result_resolved.low_paise
    assert result_missing.high_paise > result_resolved.high_paise
    assert result_missing.fee_reference_version == 0
    assert any("fee_reference unavailable" in a and "WIDENS" in a for a in result_missing.assumptions)
    assert result_missing.cogs_basis == "STATED"  # unrelated to the fee gap, still tracked correctly


def test_range_only_fee_reference_widens_range_and_names_the_gap():
    observation = _observation(stated_cogs_paise=Paise(20_000), candidate_prices=(Paise(50_000),))
    point_fee = _fee_reference()
    range_fee = _fee_reference(rate_pct=None, rate_low_pct=Fraction(8), rate_high_pct=Fraction(12))

    result_point = estimate_product_feasibility(
        observation, fee_reference=point_fee, tenant_id=TENANT_ID, computed_at=NOW
    )
    result_range = estimate_product_feasibility(
        observation, fee_reference=range_fee, tenant_id=TENANT_ID, computed_at=NOW
    )

    # A range-only fee_reference must widen (not narrow, not collapse to a midpoint) relative
    # to a point rate that sits inside that same range.
    assert result_range.low_paise <= result_point.low_paise
    assert result_range.high_paise >= result_point.high_paise
    assert result_range.low_paise < result_range.high_paise
    assert any(
        "provided only a rate range" in a and "WIDENED" in a for a in result_range.assumptions
    )


# --- rule 3: never returns (or is) a MetricResult -------------------------------------------


def test_never_returns_a_metric_result_shaped_object():
    observation = _observation(stated_cogs_paise=Paise(20_000))
    result = estimate_product_feasibility(
        observation, fee_reference=_fee_reference(), tenant_id=TENANT_ID, computed_at=NOW
    )

    assert isinstance(result, ProductFeasibilityEstimate)
    assert not isinstance(result, MetricResult)
    # This surface's id is an estimate_ref, structurally distinct from an engine_result_ref —
    # confirmed by the absence of every metric_result-only field (metric_code, value_paise,
    # recognition_state, is_available) anywhere on this dataclass.
    result_fields = {f for f in result.__dataclass_fields__}
    assert "metric_code" not in result_fields
    assert "value_paise" not in result_fields
    assert "recognition_state" not in result_fields
    assert "is_available" not in result_fields


# --- rule 1/4: always a range, confidence fixed at DERIVED ----------------------------------


def test_always_a_range_with_derived_confidence_and_valid_estimate_ref():
    observation = _observation(stated_cogs_paise=Paise(20_000))
    result = estimate_product_feasibility(
        observation, fee_reference=_fee_reference(), tenant_id=TENANT_ID, computed_at=NOW
    )

    assert isinstance(result.id, UUID)
    assert result.confidence == Confidence.DERIVED
    assert result.low_paise <= result.high_paise
    assert result.tenant_id == TENANT_ID


# --- no float anywhere in the calculation path ------------------------------------------------


def test_no_float_anywhere_in_source():
    source = inspect.getsource(
        __import__(
            "calc_engine.api.estimate_product_feasibility",
            fromlist=["estimate_product_feasibility"],
        )
    )
    assert "float(" not in source
    assert ": float" not in source
    assert "-> float" not in source
