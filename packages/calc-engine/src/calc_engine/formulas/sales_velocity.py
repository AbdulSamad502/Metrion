"""sales_velocity — cfo-agent.md §6.12 (Batch size)'s "sales velocity from uploaded reports
(observed)" input, `twinkly-mapping-canyon.md` CP B3b.

**Why this is a new small engine formula, not a CFO-side sum:** summing "units sold" across a
period is a real calculation (CLAUDE.md's hard rule — every calculation that touches the
business's numbers lives in the deterministic engine, Python/SQL, unit-tested, no LLM in the
path). That rule is usually stated about money, but this codebase's own established discipline
this session — "arithmetic lives in calc-engine, CFO only assembles/calls/persists" — applies
just as much to a unit count as to a paise figure; a CFO-side `sum()` over `CanonicalLine`s
would be exactly the kind of arithmetic-outside-the-engine this whole codebase's no-arithmetic
lint (`test_no_arithmetic_lint.py`) exists to catch, and inventing a second "how many units did
we actually sell" concept next to `cost_components.billable_quantity` (already used by COGS)
would be a second, competing definition of "sold" this codebase does not want.

`observed_units_sold` therefore reuses `billable_quantity` (real, unchanged,
`cost_components.py`) exactly — the SAME "actually sold" concept COGS already uses (excludes
returns/RTO/cancellation, §5.6), never a second one invented for velocity.

Like `rank_findings` (`severity.py`) — a supporting observed input feeding a larger composition,
not itself a headline financial figure — this function returns a plain `int | Unavailable`, not
a `MetricResult`. There is no `engine_result_ref` for an observed sales-velocity count in this
checkpoint's scope; CFO wiring (B3b, `backend.services.cfo_actions.
assemble_batch_size_estimate`) consumes this value as one input among several feeding the real,
`MetricResult`-wrapped `BATCH_CONSTRAINED_QUANTITY` figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from calc_engine.formulas.cost_components import billable_quantity
from calc_engine.types import CanonicalLine, Unavailable


def observed_units_sold(lines: Sequence[CanonicalLine], as_of: date) -> int | Unavailable:
    """Sums `billable_quantity(line)` (real, unchanged, `cost_components.py`) across `lines`.

    `as_of` is accepted for symmetry with every other observed-figure signature in this
    codebase (`weighted_average_cost(sku, as_of, ...)`) and to make explicit that this is a
    figure observed as of a point in time, not a live/streaming count — `billable_quantity`
    itself takes no date (a line's returned/RTO/cancellation classification is not itself
    date-dependent the way COGS's weighted-average lookup is), so `as_of` is not threaded any
    further than this signature; it is not a silent no-op, it documents the contract for a
    future caller that DOES need to filter `lines` to a period before calling this function
    (this function itself does not filter by date — the caller decides which lines are "in the
    period", the same division of responsibility `PeriodPnlRequest.lines` already establishes
    for `compute_period_pnl`).

    Propagates `Unavailable` the moment ANY line's `billable_quantity` comes back `Unavailable`
    (e.g. a line cancelled after dispatch with no `rto_outcome` classification yet) — the same
    propagation discipline `cogs()` already applies to a single line's cost: a partial/uncertain
    velocity figure is never silently reported as if it were a complete, trustworthy count.

    An empty `lines` sequence is a real, legitimate zero (`0`), never `Unavailable` — "no lines
    observed in this period" is a fact about the data (e.g. a genuinely never-sold SKU, §6.12),
    not a missing input.
    """
    total = 0
    for line in lines:
        quantity = billable_quantity(line)
        if isinstance(quantity, Unavailable):
            return quantity
        total += quantity
    return total


@dataclass(frozen=True, slots=True)
class BatchBudget:
    """One `batch.budget` manual_adjustment (deterministic-engine.md §7.2.1, line 795):
    `{amount_paise, valid_until?}`, `target_type` is `SKU` or `ACCOUNT`. `amount_paise` is the
    raw paise int this module hands to the caller as-is — this module performs no arithmetic on
    it, only parses and later (via `is_expired_as_of`) compares a `date`."""

    amount_paise: int
    valid_until: date | None

    def is_expired_as_of(self, as_of_date: date) -> bool:
        """`True` exactly when `valid_until` is set and falls strictly before `as_of_date` — a
        budget valid through today is not yet expired (`valid_until == as_of_date` still
        counts as valid), mirroring `weighted_average_cost`'s own `effective_from <= as_of`
        inclusive-boundary convention. A budget with no `valid_until` at all never expires by
        this check (the seller declared no expiry)."""
        return self.valid_until is not None and self.valid_until < as_of_date


def parse_batch_budget_adjustment(value: dict) -> BatchBudget:
    """§7.2.1 `batch.budget` shape: `{amount_paise, valid_until?}`. Mirrors
    `parse_supplier_quote_adjustment`'s exact style (`landed_cost.py`): the one field a budget
    is meaningless without (`amount_paise`) is required and raises `ValueError` if missing or
    the wrong type — not a partially-known budget, a malformed one, same convention
    `parse_expense_pool_adjustment`/`parse_supplier_quote_adjustment` both already use for
    their own required field. `valid_until` is parsed leniently: `None` if absent, parsed from
    an ISO date string if present as a `str`, passed through unchanged if already a `date`,
    and `None` (never raising) for any other type — an unparseable expiry is treated the same
    as "no expiry stated" rather than aborting the whole adjustment over a malformed date
    string, since `amount_paise` (the field this whole estimate depends on) is still usable."""
    amount_paise = value.get("amount_paise")
    if not isinstance(amount_paise, int) or isinstance(amount_paise, bool):
        raise ValueError(f"batch.budget adjustment missing/invalid amount_paise: {value!r}")

    valid_until_raw = value.get("valid_until")
    valid_until: date | None
    if isinstance(valid_until_raw, date):
        valid_until = valid_until_raw
    elif isinstance(valid_until_raw, str):
        try:
            valid_until = date.fromisoformat(valid_until_raw)
        except ValueError:
            valid_until = None
    else:
        valid_until = None

    return BatchBudget(amount_paise=amount_paise, valid_until=valid_until)
