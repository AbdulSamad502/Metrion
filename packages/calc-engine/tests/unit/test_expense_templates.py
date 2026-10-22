"""deterministic-engine.md §5.18.1 / §5.18.2 test series AM1–AM5, AM9 and PT1–PT5, PT7 (Round 7)."""

from __future__ import annotations

from datetime import date

import pytest

from calc_engine.formulas import expense_templates as t
from calc_engine.types import Paise


def total(shares) -> int:
    return sum(s.value for s in shares)


def test_am1_twelve_thousand_rupees_over_twelve_months_is_a_thousand_a_month() -> None:
    s = t.amortization_schedule(1_200_000, 12, date(2026, 1, 15))
    assert s.valid and [x.value for x in s.shares] == [100_000] * 12
    assert s.months[0] == date(2026, 1, 1) and s.months[-1] == date(2026, 12, 1)


def test_am2_an_uneven_amount_differs_by_at_most_one_paisa_and_sums_exactly() -> None:
    s = t.amortization_schedule(100_001, 12, date(2026, 4, 1))
    values = [x.value for x in s.shares]
    assert max(values) - min(values) == 1 and sum(values) == 100_001
    assert values == sorted(values, reverse=True)  # the leftover paise go to the first months


def test_am3_one_month_equals_the_plain_record() -> None:
    s = t.amortization_schedule(54_321, 1, date(2026, 5, 9))
    assert [x.value for x in s.shares] == [54_321] and s.months == (date(2026, 5, 1),)


@pytest.mark.parametrize("months", [None, 0, -1, 2.5, True, "12"])
def test_am4_invalid_months_are_not_amortized_and_not_zero(months) -> None:
    s = t.amortization_schedule(120_000, months, date(2026, 1, 1))
    assert not s.valid and s.reason == "AMORTIZATION_INVALID" and s.shares == ()
    assert t.amortized_in_period(s, date(2026, 1, 1), date(2026, 12, 31)) is None  # not counted, and not a zero


def test_am4_a_missing_start_is_invalid_too() -> None:
    assert t.amortization_schedule(1_000, 3, None).reason == "AMORTIZATION_INVALID"


def test_am5_a_period_before_the_start_or_after_the_end_receives_nothing() -> None:
    s = t.amortization_schedule(120_000, 3, date(2026, 3, 1))
    assert t.amortized_in_period(s, date(2026, 1, 1), date(2026, 2, 28)) is None
    assert t.amortized_in_period(s, date(2026, 6, 1), date(2026, 6, 30)) is None
    assert t.amortized_in_period(s, date(2026, 3, 1), date(2026, 3, 31)) == Paise(40_000)
    assert t.amortized_in_period(s, date(2026, 3, 1), date(2026, 5, 31)) == Paise(120_000)


def test_a_zero_amount_gives_shares_of_zero_that_are_shown_as_zero() -> None:
    s = t.amortization_schedule(0, 4, date(2026, 1, 1))
    assert s.valid and [x.value for x in s.shares] == [0, 0, 0, 0]
    assert t.amortized_in_period(s, date(2026, 1, 1), date(2026, 1, 31)) == Paise(0)


def test_a_credit_keeps_its_sign_on_every_share_and_conserves_the_total() -> None:
    s = t.amortization_schedule(-10_001, 3, date(2026, 1, 1))
    assert [x.value for x in s.shares] == [-3_334, -3_334, -3_333] and total(s.shares) == -10_001


def test_the_remaining_balance_is_its_own_value() -> None:
    s = t.amortization_schedule(120_000, 4, date(2026, 1, 1))
    assert t.remaining_balance(s, date(2026, 2, 15)) == Paise(60_000)
    assert t.remaining_balance(s, date(2025, 12, 1)) == Paise(120_000)
    assert t.remaining_balance(s, date(2026, 4, 1)) == Paise(0)
    assert t.remaining_balance(t.amortization_schedule(1, 0, date(2026, 1, 1)), date(2026, 1, 1)) is None


def test_the_month_arithmetic_crosses_a_year_end() -> None:
    assert t.add_months(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert t.months_inclusive(date(2026, 11, 20), date(2027, 1, 3)) == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)]
    assert t.months_inclusive(date(2026, 5, 1), date(2026, 4, 1)) == []


# ---- per-order / per-unit (§5.18.2) --------------------------------------------------------------------------------------------------------------------------


def test_pt1_five_rupees_times_two_hundred_orders_is_exactly_a_thousand_rupees() -> None:
    r = t.per_count_amount(500, 200, per="ORDER")
    assert r.amount == Paise(100_000) and r.count == 200 and r.reason is None


def test_pt2_a_missing_count_is_unavailable_not_partial_and_not_zero() -> None:
    assert t.per_count_amount(500, None, per="ORDER").reason == "ORDERS_UNAVAILABLE"
    r = t.per_count_amount(500, None, per="UNIT")
    assert r.amount is None and r.reason == "UNITS_UNAVAILABLE"


def test_pt3_a_true_zero_count_is_a_real_zero_shown_with_its_count() -> None:
    r = t.per_count_amount(500, 0, per="ORDER")
    assert r.amount == Paise(0) and r.count == 0 and r.reason is None


def test_pt4_no_sales_lines_is_unavailable_not_zero() -> None:
    r = t.per_count_amount(500, 0, per="ORDER", any_sales_lines=False)
    assert r.amount is None and r.reason == "NO_ORDERS_IN_PERIOD"


def test_a_rate_of_zero_is_allowed_and_a_missing_or_negative_rate_is_not() -> None:
    assert t.per_count_amount(0, 7, per="UNIT").amount == Paise(0)
    for bad in (None, -1, True):
        r = t.per_count_amount(bad, 7, per="UNIT")
        assert r.amount is None and r.reason == "RATE_MISSING"


def test_pt5_the_rate_version_effective_on_each_order_date_is_used() -> None:
    versions = [(date(2026, 1, 1), date(2026, 3, 14), 500), (date(2026, 3, 15), None, 600)]
    assert t.rate_for_date(versions, date(2026, 3, 14)) == 500
    assert t.rate_for_date(versions, date(2026, 3, 15)) == 600
    assert t.rate_for_date(versions, date(2025, 12, 31)) is None


def test_pt7_there_is_no_parameter_through_which_a_model_could_supply_a_count() -> None:
    import inspect

    assert set(inspect.signature(t.per_count_amount).parameters) == {"rate_paise", "count", "per", "any_sales_lines"}  # the count is the caller's engine count only
