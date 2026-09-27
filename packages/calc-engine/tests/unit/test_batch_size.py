"""batch_size.py / compute_batch_constrained_quantity — cfo-agent.md §6.12,
deterministic-engine.md §7.2.1."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from calc_engine.api.compute_metric import compute_batch_constrained_quantity
from calc_engine.formulas.batch_size import BudgetConstrainedQuantity, budget_constrained_quantity
from calc_engine.types import Paise

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


# --- budget_constrained_quantity ----------------------------------------------------------------


def test_hand_verified_no_moq():
    # floor(100000 / 3333) = 30: 3333*30=99990 <= 100000, 3333*31=103323 > 100000.
    result = budget_constrained_quantity(Paise(100_000), Paise(3_333), None)
    assert result.max_affordable_units == 30
    assert result.meets_moq is True
    assert result.recommended_quantity == 30
    assert result.units_short == 0


def test_moq_met():
    result = budget_constrained_quantity(Paise(100_000), Paise(3_333), 20)
    assert result.max_affordable_units == 30
    assert result.meets_moq is True
    assert result.recommended_quantity == 30
    assert result.units_short == 0


def test_moq_not_met_reports_shortfall_never_recommends_unpurchasable_quantity():
    # floor(10000 / 3333) = 3: 3333*3=9999 <= 10000, 3333*4=13332 > 10000.
    result = budget_constrained_quantity(Paise(10_000), Paise(3_333), 20)
    assert result.max_affordable_units == 3
    assert result.meets_moq is False
    # Never silently recommend an unpurchasable quantity as if MOQ didn't exist.
    assert result.recommended_quantity == 0
    assert result.units_short == 17


def test_never_rounds_up_exact_boundary():
    # 3333*3 = 9999 exactly: budget=9999 affords exactly 3 units.
    result_exact = budget_constrained_quantity(Paise(9_999), Paise(3_333), None)
    assert result_exact.max_affordable_units == 3
    # One paise short of that exact boundary must NOT round up to 3 -- floor must stay at 2.
    result_short = budget_constrained_quantity(Paise(9_998), Paise(3_333), None)
    assert result_short.max_affordable_units == 2


def test_zero_budget_is_not_a_caller_bug():
    result = budget_constrained_quantity(Paise(0), Paise(3_333), None)
    assert result.max_affordable_units == 0
    assert result.meets_moq is True  # no MOQ declared
    assert result.recommended_quantity == 0


def test_zero_budget_with_moq_reports_full_shortfall():
    result = budget_constrained_quantity(Paise(0), Paise(3_333), 5)
    assert result.max_affordable_units == 0
    assert result.meets_moq is False
    assert result.recommended_quantity == 0
    assert result.units_short == 5


def test_negative_budget_raises():
    with pytest.raises(ValueError):
        budget_constrained_quantity(Paise(-1), Paise(3_333), None)


def test_landed_cost_per_unit_zero_raises():
    with pytest.raises(ValueError):
        budget_constrained_quantity(Paise(100_000), Paise(0), None)


def test_landed_cost_per_unit_negative_raises():
    with pytest.raises(ValueError):
        budget_constrained_quantity(Paise(100_000), Paise(-1), None)


def test_moq_zero_raises():
    with pytest.raises(ValueError):
        budget_constrained_quantity(Paise(100_000), Paise(3_333), 0)


def test_moq_negative_raises():
    with pytest.raises(ValueError):
        budget_constrained_quantity(Paise(100_000), Paise(3_333), -5)


def test_moq_none_always_meets():
    result = budget_constrained_quantity(Paise(0), Paise(3_333), None)
    assert result.meets_moq is True


# --- compute_batch_constrained_quantity ----------------------------------------------------------


def test_compute_batch_constrained_quantity_result_shape():
    adjustment_id = uuid4()
    result = compute_batch_constrained_quantity(
        Paise(100_000),
        Paise(3_333),
        20,
        sku="SKU-1",
        active_adjustment_ids=[adjustment_id],
        computed_at=NOW,
    )
    assert result.metric_code == "BATCH_CONSTRAINED_QUANTITY"
    assert result.is_available is True
    assert result.value_paise == 30
    assert result.canonical_data_version == "non-canonical"
    assert result.confidence == "MANUAL"
    assert isinstance(result.id, UUID)
    assert result.manual_adjustment_set == (str(adjustment_id),)
    assert "meets_moq=True" in result.calculation_basis
    assert "unit COUNT, not paise" in result.calculation_basis


def test_compute_batch_constrained_quantity_moq_not_met_reflected_in_basis():
    result = compute_batch_constrained_quantity(
        Paise(10_000),
        Paise(3_333),
        20,
        sku="SKU-1",
        active_adjustment_ids=[],
        computed_at=NOW,
    )
    assert result.value_paise == 3
    assert "meets_moq=False" in result.calculation_basis
    assert "recommended_quantity=0" in result.calculation_basis
    assert "units_short=17" in result.calculation_basis


def test_compute_batch_constrained_quantity_propagates_caller_bug():
    with pytest.raises(ValueError):
        compute_batch_constrained_quantity(
            Paise(100_000),
            Paise(0),
            None,
            sku="SKU-1",
            active_adjustment_ids=[],
            computed_at=NOW,
        )


# --- Hypothesis property tests -------------------------------------------------------------------


@given(
    budget_low=st.integers(min_value=0, max_value=10_000_000),
    budget_delta=st.integers(min_value=0, max_value=10_000_000),
    unit_cost=st.integers(min_value=1, max_value=1_000_000),
)
def test_monotonic_non_decreasing_in_budget(budget_low, budget_delta, unit_cost):
    low = budget_constrained_quantity(Paise(budget_low), Paise(unit_cost), None)
    high = budget_constrained_quantity(Paise(budget_low + budget_delta), Paise(unit_cost), None)
    assert high.max_affordable_units >= low.max_affordable_units


@given(
    budget=st.integers(min_value=0, max_value=10_000_000),
    unit_cost_low=st.integers(min_value=1, max_value=1_000_000),
    unit_cost_delta=st.integers(min_value=0, max_value=1_000_000),
)
def test_monotonic_non_increasing_in_unit_cost(budget, unit_cost_low, unit_cost_delta):
    low_cost = budget_constrained_quantity(Paise(budget), Paise(unit_cost_low), None)
    high_cost = budget_constrained_quantity(Paise(budget), Paise(unit_cost_low + unit_cost_delta), None)
    assert high_cost.max_affordable_units <= low_cost.max_affordable_units


@given(
    budget=st.integers(min_value=0, max_value=10_000_000),
    unit_cost=st.integers(min_value=1, max_value=1_000_000),
)
def test_affordability_invariant_never_exceeds_budget(budget, unit_cost):
    # The single most important invariant in this checkpoint: the recommended affordable
    # quantity, multiplied back out, must never exceed the budget -- violating this would mean
    # recommending a batch the seller literally cannot afford.
    result = budget_constrained_quantity(Paise(budget), Paise(unit_cost), None)
    assert result.max_affordable_units * unit_cost <= budget
