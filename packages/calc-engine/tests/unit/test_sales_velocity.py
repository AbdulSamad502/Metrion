"""sales_velocity.py — cfo-agent.md §6.12 (Batch size), `twinkly-mapping-canyon.md` CP B3b.

Covers `observed_units_sold` (real sum over `billable_quantity`, `Unavailable` propagation,
legitimate empty-lines zero) and `parse_batch_budget_adjustment`/`BatchBudget.is_expired_as_of`
(§7.2.1 `batch.budget` shape, expiry).
"""

from __future__ import annotations

from datetime import date

import pytest

from calc_engine.formulas.sales_velocity import (
    BatchBudget,
    observed_units_sold,
    parse_batch_budget_adjustment,
)
from calc_engine.types import Unavailable

from tests.fixtures.canonical_builder import CanonicalDataBuilder

_AS_OF = date(2026, 9, 24)


# --- observed_units_sold -----------------------------------------------------------------------


def test_sums_billable_quantity_across_several_lines():
    line_a = CanonicalDataBuilder().quantity(5).gross(100_000).build()  # fully resolved, no return/RTO -> 5
    line_b = CanonicalDataBuilder().quantity(3).gross(60_000).returned(1, refunded_amount_paise=20_000).build()  # 3 - 1 = 2
    line_c = CanonicalDataBuilder().quantity(2).gross(40_000).rto(1, outcome="RECOVERED_DAMAGED").build()  # RTO excludes all: 0... but full qty consumed as cost? billable_quantity excludes RTO'd units regardless of outcome -> 2 - rto_qty(1) = 1

    result = observed_units_sold([line_a, line_b, line_c], as_of=_AS_OF)

    expected = 5 + 2 + 1
    assert result == expected


def test_unavailable_propagates_from_one_unclassified_line():
    resolved_line = CanonicalDataBuilder().quantity(5).gross(100_000).build()
    unclassified_cancelled_after_dispatch = (
        CanonicalDataBuilder()
        .quantity(1)
        .gross(20_000)
        .dispatched_on(date(2026, 8, 18))
        .cancelled()
        .build()
    )  # rto_outcome not classified -> billable_quantity returns Unavailable

    result = observed_units_sold([resolved_line, unclassified_cancelled_after_dispatch], as_of=_AS_OF)

    assert isinstance(result, Unavailable)
    assert "rto_outcome" in result.missing_inputs


def test_empty_lines_is_a_real_legitimate_zero_not_unavailable():
    result = observed_units_sold([], as_of=_AS_OF)
    assert result == 0
    assert not isinstance(result, Unavailable)


# --- parse_batch_budget_adjustment ---------------------------------------------------------------


def test_parses_amount_paise_and_valid_until():
    budget = parse_batch_budget_adjustment({"amount_paise": 500_000, "valid_until": "2026-12-31"})
    assert budget.amount_paise == 500_000
    assert budget.valid_until == date(2026, 12, 31)


def test_parses_amount_paise_with_no_valid_until():
    budget = parse_batch_budget_adjustment({"amount_paise": 500_000})
    assert budget.amount_paise == 500_000
    assert budget.valid_until is None


def test_missing_amount_paise_raises():
    with pytest.raises(ValueError, match="amount_paise"):
        parse_batch_budget_adjustment({"valid_until": "2026-12-31"})


def test_bool_amount_paise_raises():
    with pytest.raises(ValueError, match="amount_paise"):
        parse_batch_budget_adjustment({"amount_paise": True})


def test_unparseable_valid_until_falls_back_to_none_not_raise():
    budget = parse_batch_budget_adjustment({"amount_paise": 500_000, "valid_until": "not-a-date"})
    assert budget.amount_paise == 500_000
    assert budget.valid_until is None


# --- BatchBudget.is_expired_as_of ----------------------------------------------------------------


def test_no_valid_until_never_expires():
    budget = BatchBudget(amount_paise=500_000, valid_until=None)
    assert budget.is_expired_as_of(date(2099, 1, 1)) is False


def test_valid_until_before_as_of_is_expired():
    budget = BatchBudget(amount_paise=500_000, valid_until=date(2026, 1, 1))
    assert budget.is_expired_as_of(date(2026, 9, 24)) is True


def test_valid_until_equal_to_as_of_is_not_yet_expired():
    budget = BatchBudget(amount_paise=500_000, valid_until=date(2026, 9, 24))
    assert budget.is_expired_as_of(date(2026, 9, 24)) is False


def test_valid_until_after_as_of_is_not_expired():
    budget = BatchBudget(amount_paise=500_000, valid_until=date(2027, 1, 1))
    assert budget.is_expired_as_of(date(2026, 9, 24)) is False
