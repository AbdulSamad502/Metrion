"""expense.advertising (and its §7.2.1 siblings: packaging/storage/logistics/other) —
deterministic-engine.md §5.6, §5.10 (D7), §7.2.1.

`contribution_profit()` already accepts `advertising_costs: Paise` as a plain parameter — this
module is the missing piece that resolves that value from a `manual_adjustment` row instead of
leaving the caller to invent one. Two distinct scopes, per §5.6's own confidence split:

- `target_type = SKU`: a direct per-SKU entry. Confidence `MANUAL`, no allocation.
- `target_type = ACCOUNT` or `PERIOD`: an account/period-level pool that must be spread across
  the SKUs in scope by net-revenue share (D7's default basis) via `allocation.allocate_pool()`.
  Confidence `DERIVED` (§5.10: "every allocated figure is DERIVED").

**Absent adjustment = zero, confirmed.** Unlike `cost_components.py`'s COGS handling (a
missing per-unit cost is `Unavailable` — the real cost was definitely incurred, we just don't
know it), advertising spend is opt-in seller-declared data (§5.6: "Seller-entered"). No
adjustment for a scope means the seller ran no ads there, the same treatment already given to
a line with zero matching `DISCOUNT` components — not a missing-input block on
`ContributionProfit`. This module does not extend that treatment to `COGS`.

This is written generically enough to serve any of §7.2.1's other pooled-cost fields
(`expense.packaging`, `expense.storage`, `expense.other`) that share the identical
`{amount_paise, gst_amount_paise?, marketplace?}` shape — only `expense.logistics` is
excluded, since it alone has the per-line-actual-wins precedence rule (§7.2.1) this module
does not implement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Sequence, TypeVar

from calc_engine.formulas.allocation import AllocationBasis, allocate_pool
from calc_engine.types import ZERO, Confidence, Paise

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ExpensePoolEntry:
    amount_paise: Paise
    gst_amount_paise: Paise | None
    marketplace: str | None


def parse_expense_pool_adjustment(value: dict[str, object]) -> ExpensePoolEntry:
    """§7.2.1: `{amount_paise, gst_amount_paise?, marketplace?}`. No default is invented for a
    missing `amount_paise` — a malformed adjustment raises, it is never silently treated as
    zero (that would hide a real data-entry problem behind a legitimate "no ads" zero)."""
    amount_paise = value.get("amount_paise")
    if not isinstance(amount_paise, int) or isinstance(amount_paise, bool):
        raise ValueError(f"expense pool adjustment missing/invalid amount_paise: {value!r}")
    gst_raw = value.get("gst_amount_paise")
    gst_amount_paise = Paise(gst_raw) if isinstance(gst_raw, int) and not isinstance(gst_raw, bool) else None
    marketplace = value.get("marketplace")
    return ExpensePoolEntry(
        amount_paise=Paise(amount_paise),
        gst_amount_paise=gst_amount_paise,
        marketplace=marketplace if isinstance(marketplace, str) else None,
    )


def resolve_sku_level_expense(adjustment_value: dict[str, object] | None) -> tuple[Paise, Confidence]:
    """`target_type = SKU`: a direct entry, MANUAL confidence. Absent -> ZERO, MANUAL is not
    claimed for a value that was never entered — PROVISIONAL is the honest floor for "nothing
    to report", matching how an absent DISCOUNT component contributes zero without asserting
    MANUAL confidence for the absence itself."""
    if adjustment_value is None:
        return ZERO, Confidence.PROVISIONAL
    entry = parse_expense_pool_adjustment(adjustment_value)
    return entry.amount_paise, Confidence.MANUAL


def allocate_account_level_expense_pool(
    adjustment_value: dict[str, object] | None,
    weights: Sequence[tuple[T, Fraction]],
) -> dict[T, Paise]:
    """`target_type = ACCOUNT` or `PERIOD`: spread across the SKUs in scope by net-revenue
    share (D7 default basis), via the same `allocate_pool()` every other allocated cost uses.
    Absent adjustment -> every target gets ZERO (still every key present, never dropped —
    T15's "unallocated pool reported, not dropped" pattern applies equally to "no pool at
    all"). Confidence is DERIVED for any nonzero result, per §5.10 — the caller stamps that;
    this function returns only the per-target Paise split, same contract as `allocate_pool`.
    """
    if adjustment_value is None:
        return {key: ZERO for key, _ in weights}
    entry = parse_expense_pool_adjustment(adjustment_value)
    return allocate_pool(entry.amount_paise, weights, AllocationBasis.NET_REVENUE)


@dataclass(frozen=True, slots=True)
class ExpenseBudgetEntry:
    """One `expense.budget` manual_adjustment (deterministic-engine.md §7.2.1, extended per
    the same table row's own "a parallel field ... precedent" pointer to `batch.budget`):
    `{category, amount_paise, period_start, period_end}`, `target_type = ACCOUNT` always.

    **Grain decision:** per-category, not one overall ceiling. `enter_expense`'s own five
    `expense.<category>` fields (`advertising`/`packaging`/`storage`/`logistics`/`other`) are
    already per-category — a single overall ceiling would not let a seller answer "did I
    overspend on packaging specifically," the exact question a category-level expense entry
    exists to answer. `category` is carried INSIDE the value (not encoded as a separate
    `field` per category) so a seller can hold more than one ACTIVE category budget
    simultaneously under the one `expense.budget` field name — the same multi-ACTIVE-row
    shape `supplier.quote` already established for "more than one thing can be active for
    the same (target_type, target_ref, field) at once, disambiguated by a value-level key.\""""

    category: str
    amount_paise: Paise
    period_start: date
    period_end: date


_EXPENSE_BUDGET_CATEGORIES = frozenset({"advertising", "packaging", "storage", "logistics", "other"})


def parse_expense_budget_adjustment(value: dict[str, object]) -> ExpenseBudgetEntry:
    """§7.2.1 `expense.budget` shape: `{category, amount_paise, period_start, period_end}`.
    All four fields are required — a budget with no category, no ceiling, or no period is not
    a partially-known budget, it is a malformed one (mirrors `parse_expense_pool_adjustment`'s
    own "malformed raises, never silently zeroed" convention). `category` must be one of the
    five real `expense.<category>` pools `enter_expense` already accepts — a budget for a
    category that can never be entered as an expense would be meaningless."""
    category = value.get("category")
    if not isinstance(category, str) or category not in _EXPENSE_BUDGET_CATEGORIES:
        raise ValueError(
            f"expense.budget adjustment missing/invalid category (must be one of "
            f"{sorted(_EXPENSE_BUDGET_CATEGORIES)}): {value!r}"
        )
    amount_paise = value.get("amount_paise")
    if not isinstance(amount_paise, int) or isinstance(amount_paise, bool):
        raise ValueError(f"expense.budget adjustment missing/invalid amount_paise: {value!r}")

    def _parse_date(raw: object, field_name: str) -> date:
        if isinstance(raw, date):
            return raw
        if isinstance(raw, str):
            try:
                return date.fromisoformat(raw)
            except ValueError:
                raise ValueError(f"expense.budget adjustment has unparseable {field_name}: {raw!r}") from None
        raise ValueError(f"expense.budget adjustment missing/invalid {field_name}: {value!r}")

    period_start = _parse_date(value.get("period_start"), "period_start")
    period_end = _parse_date(value.get("period_end"), "period_end")
    if period_end < period_start:
        raise ValueError(f"expense.budget adjustment has period_end before period_start: {value!r}")

    return ExpenseBudgetEntry(
        category=category,
        amount_paise=Paise(amount_paise),
        period_start=period_start,
        period_end=period_end,
    )


@dataclass(frozen=True, slots=True)
class ExpenseBudgetCheckResult:
    budget_paise: Paise
    spent_paise: Paise
    remaining_paise: Paise
    exceeded: bool


def check_expense_budget(budget_paise: Paise, spent_paise: Paise) -> ExpenseBudgetCheckResult:
    """The one real arithmetic step behind `expense.budget` (CLAUDE.md hard rule: money
    arithmetic lives in the deterministic engine, never in `backend`/`cfo`). `remaining_paise`
    is `budget_paise - spent_paise` via `Paise.__sub__` (real, unchanged) — NEVER floored to
    zero when negative; a negative `remaining_paise` is the real, honest overage amount, not a
    fact this function hides. `exceeded` is `remaining_paise.value < 0`, a plain comparison, not
    a fabricated judgement."""
    remaining_paise = budget_paise - spent_paise
    return ExpenseBudgetCheckResult(
        budget_paise=budget_paise,
        spent_paise=spent_paise,
        remaining_paise=remaining_paise,
        exceeded=remaining_paise.value < 0,
    )
