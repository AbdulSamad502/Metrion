"""Recurring-expense arithmetic — deterministic-engine.md §5.18.1 (amortization) and §5.18.2 (per-order / per-unit templates), both APPROVED (Round 7, 2026-10-16).

Pure functions over integers: no database, no clock, no float. The browser and the LLM never compute any of this; a template only stores its inputs, and the amounts that
become ledger entries come from here.

Amortization (§5.18.1): `A` spread over `N` calendar months starting at `start`; month i gets floor(|A| / N) paise and the leftover paise go to the first months, one each
(deterministic largest remainder), so the shares sum exactly to A. A negative A (a credit) keeps its sign on every share. `N` missing, not an integer, a bool, zero or
negative -> the schedule is INVALID (`AMORTIZATION_INVALID`): it is never counted whole and never as zero. A period before the start or after the last month receives nothing
(not applicable, which is not "zero spend").

Per-order / per-unit (§5.18.2): `amount = rate_paise × count`, an exact integer product. The count is the engine's own count; a missing count is `UNAVAILABLE`
(`ORDERS_UNAVAILABLE` / `UNITS_UNAVAILABLE`), no sales lines at all is `NO_ORDERS_IN_PERIOD` (unavailable, not zero), and a true count of 0 is a real ₹0 shown with its count.
Rate changes are new template versions: the version effective on each date is used (`rate_for_date`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from calc_engine.types import ZERO, CanonicalLine, Paise

AMORTIZATION_INVALID = "AMORTIZATION_INVALID"
ORDERS_UNAVAILABLE = "ORDERS_UNAVAILABLE"
UNITS_UNAVAILABLE = "UNITS_UNAVAILABLE"
NO_ORDERS_IN_PERIOD = "NO_ORDERS_IN_PERIOD"
RATE_MISSING = "RATE_MISSING"
MONTH_NOT_FINISHED = "MONTH_NOT_FINISHED"
NO_REMAINING_SCHEDULE = "NO_REMAINING_SCHEDULE"
REFUND_EXCEEDS_REMAINING = "REFUND_EXCEEDS_REMAINING"


def first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(first: date, n: int) -> date:
    """The first day of the month `n` calendar months after `first` (itself the first of a month). Integer calendar arithmetic only."""
    index = first.year * 12 + (first.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def months_inclusive(first: date, last: date) -> list[date]:
    """First-of-month dates from `first` to `last` inclusive (both normalised to their month); empty when last is before first."""
    a, b = first_of_month(first), first_of_month(last)
    out: list[date] = []
    cur = a
    while cur <= b:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


@dataclass(frozen=True, slots=True)
class AmortizationSchedule:
    months: tuple[date, ...]  # first-of-month dates, in order; empty when invalid
    shares: tuple[Paise, ...]  # one per month; sums exactly to the amount; empty when invalid
    reason: str | None = None  # AMORTIZATION_INVALID when the inputs cannot form a schedule

    @property
    def valid(self) -> bool:
        return self.reason is None

    @property
    def total(self) -> Paise:
        t = ZERO
        for s in self.shares:
            t = t + s
        return t


def amortization_schedule(amount_paise: int, months: object, start: date | None) -> AmortizationSchedule:
    if start is None or not isinstance(months, int) or isinstance(months, bool) or months < 1 or not isinstance(amount_paise, int) or isinstance(amount_paise, bool):
        return AmortizationSchedule((), (), AMORTIZATION_INVALID)
    magnitude = abs(amount_paise)
    base, extra = divmod(magnitude, months)
    sign = -1 if amount_paise < 0 else 1
    first = first_of_month(start)
    return AmortizationSchedule(
        months=tuple(add_months(first, i) for i in range(months)),
        shares=tuple(Paise(sign * (base + (1 if i < extra else 0))) for i in range(months)),
    )


def amortized_in_period(schedule: AmortizationSchedule, period_start: date, period_end: date) -> Paise | None:
    """The sum of the shares of the calendar months that fall inside the period, or None when the schedule is invalid or no month of it falls inside (not applicable)."""
    if not schedule.valid:
        return None
    lo = first_of_month(period_start)  # periods are whole calendar months (engine §5.18.1)
    inside = [s for m, s in zip(schedule.months, schedule.shares) if lo <= m <= period_end]
    if not inside:
        return None
    total = ZERO
    for s in inside:
        total = total + s
    return total


def remaining_balance(schedule: AmortizationSchedule, after_month: date) -> Paise | None:
    """What is left to amortize after the given month (shares of later months), shown as its own value. None when the schedule is invalid."""
    if not schedule.valid:
        return None
    cutoff = first_of_month(after_month)
    total = ZERO
    for m, s in zip(schedule.months, schedule.shares):
        if m > cutoff:
            total = total + s
    return total


@dataclass(frozen=True, slots=True)
class TemplateAmount:
    amount: Paise | None  # None = UNAVAILABLE (never zero)
    reason: str | None
    count: int | None
    rate_paise: int | None


def rate_for_date(versions: Sequence[tuple[date, date | None, int]], on: date) -> int | None:
    """The rate of the template version effective on `on`: versions are (effective_from, effective_to or None, rate_paise); the latest `effective_from` not after `on`
    whose `effective_to` is not before `on` wins. None when no version covers the date."""
    covering = [v for v in versions if v[0] <= on and (v[1] is None or on <= v[1])]
    if not covering:
        return None
    return max(covering, key=lambda v: v[0])[2]


def per_count_amount(rate_paise: int | None, count: int | None, *, per: str, any_sales_lines: bool = True) -> TemplateAmount:
    """`amount = rate × count` for `per` in ORDER | UNIT. The count is supplied by the engine's own counting; there is no input through which a model could supply one."""
    unavailable = ORDERS_UNAVAILABLE if per == "ORDER" else UNITS_UNAVAILABLE
    if rate_paise is None or not isinstance(rate_paise, int) or isinstance(rate_paise, bool) or rate_paise < 0:
        return TemplateAmount(None, RATE_MISSING, count, None)
    if not any_sales_lines:
        return TemplateAmount(None, NO_ORDERS_IN_PERIOD, None, rate_paise)
    if count is None or isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return TemplateAmount(None, unavailable, None, rate_paise)
    return TemplateAmount(Paise(rate_paise * count), None, count, rate_paise)


@dataclass(frozen=True, slots=True)
class CountOutcome:
    count: int | None  # None = unavailable
    reason: str | None  # ORDERS_UNAVAILABLE / UNITS_UNAVAILABLE / NO_ORDERS_IN_PERIOD when count is None
    any_lines: bool  # False only when there are no sales lines at all in scope


def count_for_scope(lines: Sequence[CanonicalLine], order_ref_by_line: Mapping[str, str | None], per: str, *, blocked_lines: int = 0) -> CountOutcome:
    """The engine's own count for a template (section 5.18.2, with the 5.10.1 definitions): `ORDER` = distinct order ids of the in-scope lines that are not cancelled;
    `UNIT` = net units kept (units placed less returned and RTO units, zero for a cancelled line). Never a partial count: a line that could not be assembled (`blocked_lines`),
    or any line lacking a field the count needs (cancellation state, order id, or for units the return and RTO status), makes the whole count unavailable with the engine's
    reason; no lines at all is `NO_ORDERS_IN_PERIOD` (unavailable, not zero); a true count of 0 over real lines is 0."""
    unavailable = ORDERS_UNAVAILABLE if per == "ORDER" else UNITS_UNAVAILABLE
    if not lines and blocked_lines == 0:
        return CountOutcome(None, NO_ORDERS_IN_PERIOD, False)
    if blocked_lines > 0:
        return CountOutcome(None, unavailable, True)
    orders: set[str] = set()
    units = 0
    for line in lines:
        if line.cancellation_state is None:
            return CountOutcome(None, unavailable, True)
        cancelled = line.cancellation_state == "CANCELLED"
        if per == "ORDER":
            ref = (order_ref_by_line.get(str(line.sales_line_id)) or "").strip()
            if not ref:
                return CountOutcome(None, unavailable, True)
            if not cancelled:
                orders.add(ref)
        else:
            if line.return_status is None or line.rto_status is None:
                return CountOutcome(None, unavailable, True)
            kept = 0 if cancelled else line.quantity - line.returned_qty - line.rto_qty
            if kept < 0:
                return CountOutcome(None, unavailable, True)
            units += kept
    return CountOutcome(len(orders) if per == "ORDER" else units, None, True)


# ---- a refund of an amortized expense (section 5.18.1, Q31) -------------------------------------------------------------------------------------------------------


def effective_schedule(versions: Sequence[tuple[date, int, int]]) -> AmortizationSchedule:
    """The schedule in force from a template's versions, each `(start_month, remaining_total_paise, months)` read as "from this month on, this amount is spread over this many months":
    the first version is the original schedule; a later version (a refund) replaces every month from its own start and drops what the earlier one had after it. Months before the
    later version's start keep their earlier shares, so a refund never restates a past month."""
    shares: dict[date, Paise] = {}
    for start, total, months in versions:
        schedule = amortization_schedule(total, months, start)
        if not schedule.valid:
            return schedule
        first = first_of_month(start)
        for m in [m for m in shares if m >= first]:
            del shares[m]
        for m, share in zip(schedule.months, schedule.shares):
            shares[m] = share
    ordered = sorted(shares)
    return AmortizationSchedule(tuple(ordered), tuple(shares[m] for m in ordered))


@dataclass(frozen=True, slots=True)
class RefundOutcome:
    start: date | None  # first month of the re-spread remainder
    remaining_total: Paise | None  # what is left to spread from `start` after the refund
    months: int | None
    reason: str | None  # NO_REMAINING_SCHEDULE / REFUND_EXCEEDS_REMAINING when nothing could be done


def refund_remaining(schedule: AmortizationSchedule, refund_paise: int, from_month: date) -> RefundOutcome:
    """A refund of an amortized expense reduces what is left to amortize from the refund month on, spread over the months that remain; earlier months are untouched. With no month
    left in the schedule there is nothing to reduce (`NO_REMAINING_SCHEDULE`: the refund belongs to its own period as an ordinary refund); a refund larger than what remains is
    refused (`REFUND_EXCEEDS_REMAINING`)."""
    if not schedule.valid or isinstance(refund_paise, bool) or not isinstance(refund_paise, int) or refund_paise <= 0:
        return RefundOutcome(None, None, None, AMORTIZATION_INVALID)
    first = first_of_month(from_month)
    remaining = [(m, s) for m, s in zip(schedule.months, schedule.shares) if m >= first]
    if not remaining:
        return RefundOutcome(None, None, None, NO_REMAINING_SCHEDULE)
    left = sum(s.value for _, s in remaining)
    if refund_paise > left:
        return RefundOutcome(None, None, None, REFUND_EXCEEDS_REMAINING)
    return RefundOutcome(remaining[0][0], Paise(left - refund_paise), len(remaining), None)
