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


# ---- the engine's own count (section 5.18.2 with the 5.10.1 definitions) -----------------------------------------------------------------------------------------


from uuid import uuid4  # noqa: E402

from calc_engine.types import CanonicalLine, Confidence  # noqa: E402


def cl(*, qty=1, cancelled="NOT_CANCELLED", ret="DELIVERED", rto="NOT_RTO", returned=0, rto_qty=0, day=date(2026, 9, 10)) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=uuid4(), marketplace="MEESHO", document_type="INVOICE", quantity=qty, invoice_date=day, dispatch_date=day, order_date=day, gross_item_amount=Paise(10_000),
        components=(), confidence=Confidence.VERIFIED, cancellation_state=cancelled, return_status=ret, returned_qty=returned, rto_status=rto, rto_qty=rto_qty,
    )


def refs(lines, *names):
    return {str(line.sales_line_id): n for line, n in zip(lines, names)}


def test_pt1_orders_are_distinct_order_ids_and_the_amount_is_exact() -> None:
    lines = [cl() for _ in range(200)]
    out = t.count_for_scope(lines, refs(lines, *[f"O{i}" for i in range(200)]), "ORDER")
    assert (out.count, out.reason) == (200, None)
    assert t.per_count_amount(500, out.count, per="ORDER").amount == Paise(100_000)


def test_two_lines_of_one_order_are_one_order_and_their_units_both_count() -> None:
    lines = [cl(qty=2), cl(qty=3)]
    assert t.count_for_scope(lines, refs(lines, "O1", "O1"), "ORDER").count == 1
    assert t.count_for_scope(lines, refs(lines, "O1", "O1"), "UNIT").count == 5


def test_a_cancelled_line_is_no_order_and_no_unit() -> None:
    lines = [cl(qty=4, cancelled="CANCELLED"), cl(qty=2)]
    assert t.count_for_scope(lines, refs(lines, "O1", "O2"), "ORDER").count == 1
    assert t.count_for_scope(lines, refs(lines, "O1", "O2"), "UNIT").count == 2


def test_units_are_net_of_returned_and_rto_units() -> None:
    lines = [cl(qty=5, ret="RETURNED", returned=2), cl(qty=3, rto="RTO", rto_qty=1)]
    assert t.count_for_scope(lines, refs(lines, "A", "B"), "UNIT").count == 5  # (5-2) + (3-1)


def test_pt2_a_line_missing_what_the_count_needs_makes_it_unavailable_not_partial() -> None:
    good = cl()
    for bad in (cl(cancelled=None), cl(ret=None), cl(rto=None)):
        lines = [good, bad]
        unit = t.count_for_scope(lines, refs(lines, "A", "B"), "UNIT")
        assert (unit.count, unit.reason, unit.any_lines) == (None, "UNITS_UNAVAILABLE", True)
    no_status = [good, cl(cancelled=None)]
    assert t.count_for_scope(no_status, refs(no_status, "A", "B"), "ORDER").reason == "ORDERS_UNAVAILABLE"
    blank = [good, cl()]
    assert t.count_for_scope(blank, refs(blank, "A", None), "ORDER").reason == "ORDERS_UNAVAILABLE"  # a line without an order id
    assert t.count_for_scope(blank, refs(blank, "A", "  "), "ORDER").reason == "ORDERS_UNAVAILABLE"


def test_ordering_does_not_need_return_status_but_units_do() -> None:
    lines = [cl(ret=None, rto=None)]
    assert t.count_for_scope(lines, refs(lines, "A"), "ORDER").count == 1
    assert t.count_for_scope(lines, refs(lines, "A"), "UNIT").reason == "UNITS_UNAVAILABLE"


def test_a_line_that_could_not_be_assembled_makes_the_count_unavailable() -> None:
    lines = [cl()]
    out = t.count_for_scope(lines, refs(lines, "A"), "ORDER", blocked_lines=1)
    assert (out.count, out.reason, out.any_lines) == (None, "ORDERS_UNAVAILABLE", True)


def test_pt3_a_true_zero_count_over_real_lines_is_zero() -> None:
    lines = [cl(cancelled="CANCELLED"), cl(cancelled="CANCELLED")]
    out = t.count_for_scope(lines, refs(lines, "A", "B"), "ORDER")
    assert (out.count, out.reason, out.any_lines) == (0, None, True)
    assert t.per_count_amount(500, out.count, per="ORDER", any_sales_lines=out.any_lines).amount == Paise(0)


def test_pt4_no_lines_at_all_is_unavailable_not_zero() -> None:
    out = t.count_for_scope([], {}, "ORDER")
    assert (out.count, out.reason, out.any_lines) == (None, "NO_ORDERS_IN_PERIOD", False)
    assert t.per_count_amount(500, out.count, per="ORDER", any_sales_lines=out.any_lines).reason == "NO_ORDERS_IN_PERIOD"


def test_more_returned_than_sold_is_unavailable_not_negative() -> None:
    lines = [cl(qty=1, ret="RETURNED", returned=3)]
    assert t.count_for_scope(lines, refs(lines, "A"), "UNIT").reason == "UNITS_UNAVAILABLE"


def test_pt6_the_counts_are_the_same_whatever_the_line_order() -> None:
    lines = [cl(qty=q) for q in (1, 2, 3, 4)]
    names = ("A", "B", "C", "D")
    forward = t.count_for_scope(lines, refs(lines, *names), "UNIT")
    backward = t.count_for_scope(lines[::-1], refs(lines, *names), "UNIT")
    assert forward == backward and forward.count == 10


# ---- AM7: a refund of an amortized expense reduces the remaining schedule from the refund month forward ------------------------------------------------------------


def test_am7_a_refund_reduces_the_remaining_months_and_leaves_the_past_alone() -> None:
    original = t.amortization_schedule(1_200_000, 12, date(2026, 1, 1))  # Rs 12,000 over 12 months: Rs 1,000 a month
    out = t.refund_remaining(original, 300_000, date(2026, 3, 20))  # a Rs 3,000 refund in March
    assert (out.start, out.remaining_total, out.months, out.reason) == (date(2026, 3, 1), Paise(700_000), 10, None)  # Rs 10,000 left, less Rs 3,000
    after = t.effective_schedule([(date(2026, 1, 1), 1_200_000, 12), (out.start, out.remaining_total.value, out.months)])
    shares = [x.value for x in after.shares]
    assert shares[:2] == [100_000, 100_000]  # January and February are not restated
    assert shares[2:] == [70_000] * 10 and sum(shares) == 900_000 and after.months == original.months


def test_the_re_spread_of_a_refund_uses_the_same_largest_remainder() -> None:
    original = t.amortization_schedule(100_000, 4, date(2026, 1, 1))
    out = t.refund_remaining(original, 1, date(2026, 2, 1))
    after = t.effective_schedule([(date(2026, 1, 1), 100_000, 4), (out.start, out.remaining_total.value, out.months)])
    assert sum(x.value for x in after.shares) == 99_999 and max(x.value for x in after.shares[1:]) - min(x.value for x in after.shares[1:]) <= 1


def test_a_refund_in_the_first_month_reduces_the_whole_schedule() -> None:
    original = t.amortization_schedule(120_000, 4, date(2026, 5, 1))
    out = t.refund_remaining(original, 40_000, date(2026, 5, 31))
    assert (out.start, out.remaining_total, out.months) == (date(2026, 5, 1), Paise(80_000), 4)


def test_a_refund_after_the_schedule_ended_has_no_remaining_schedule_to_reduce() -> None:
    original = t.amortization_schedule(120_000, 3, date(2026, 1, 1))
    out = t.refund_remaining(original, 1_000, date(2026, 6, 1))
    assert (out.remaining_total, out.reason) == (None, "NO_REMAINING_SCHEDULE")


def test_a_refund_larger_than_what_remains_is_refused_and_an_exact_clearing_is_allowed() -> None:
    original = t.amortization_schedule(120_000, 4, date(2026, 1, 1))
    assert t.refund_remaining(original, 90_001, date(2026, 2, 1)).reason == "REFUND_EXCEEDS_REMAINING"  # Rs 900.00 remains from February
    cleared = t.refund_remaining(original, 90_000, date(2026, 2, 1))
    assert (cleared.remaining_total, cleared.reason) == (Paise(0), None)
    after = t.effective_schedule([(date(2026, 1, 1), 120_000, 4), (cleared.start, 0, cleared.months)])
    assert [x.value for x in after.shares] == [30_000, 0, 0, 0]  # real zeros


@pytest.mark.parametrize("refund", [0, -5, True, 2.5])
def test_a_refund_amount_must_be_a_positive_whole_paise(refund) -> None:
    assert t.refund_remaining(t.amortization_schedule(100, 2, date(2026, 1, 1)), refund, date(2026, 1, 1)).reason == "AMORTIZATION_INVALID"


def test_an_invalid_schedule_cannot_be_refunded() -> None:
    assert t.refund_remaining(t.amortization_schedule(100, 0, date(2026, 1, 1)), 5, date(2026, 1, 1)).reason == "AMORTIZATION_INVALID"


def test_two_refunds_compose_and_a_repeated_identical_version_changes_nothing() -> None:
    v1 = (date(2026, 1, 1), 1_200_000, 12)
    first = t.refund_remaining(t.effective_schedule([v1]), 200_000, date(2026, 4, 1))
    v2 = (first.start, first.remaining_total.value, first.months)
    second = t.refund_remaining(t.effective_schedule([v1, v2]), 100_000, date(2026, 8, 1))
    v3 = (second.start, second.remaining_total.value, second.months)
    final = t.effective_schedule([v1, v2, v3])
    assert sum(x.value for x in final.shares) == 900_000 and len(final.months) == 12
    assert [x.value for x in final.shares[:3]] == [100_000] * 3  # January to March untouched by both refunds
    assert t.effective_schedule([v1, v2, v2]) == t.effective_schedule([v1, v2])
