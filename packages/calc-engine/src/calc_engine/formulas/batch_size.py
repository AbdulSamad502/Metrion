"""batch_size — deterministic-engine.md §7.2.1 (`batch.budget` field registry), cfo-agent.md
§6.12 (Batch size).

**Scope of this module (CP B3a):** the budget-and-MOQ arithmetic core §6.12 itself names as the
honest floor when velocity is unavailable — "the estimate degrades to a budget-and-MOQ
arithmetic exercise and must say so." Sales velocity is a *separate* input CFO layers on top
in a later checkpoint (B3b), consuming observed CanonicalLine sales history — it is not part of
this formula. This module answers exactly one question: given a fixed budget ceiling and a
fixed per-unit landed cost, how many units can actually be afforded, and does that respect the
seller's MOQ. It is not yet the full "budget-constrained order-quantity *range*" §6.12
describes — that range is velocity-informed and is B3b's job; this is the deterministic ceiling
both the full-velocity case and the no-velocity degraded case both need as their foundation.

Like `landed_cost.py`, a `batch.budget` value and a `supplier.quote`'s `moq` are both
seller-declared, non-canonical inputs (§7.2.1) — there is no genuinely-missing-input case to
model as `Unavailable` here. Once inputs are validated, every remaining invalid case is a
caller bug, not missing data, and raises `ValueError` — the same convention
`landed_cost_per_unit` uses for `quantity <= 0`.

**Rounding direction is safety-critical**: the number of affordable units must never be rounded
up. Rounding up would tell a seller they can afford more units than their budget actually
covers — a real, harmful correctness bug for a real business, not an imprecision. This module
therefore uses plain integer floor division (`//`) on the raw paise ints, never
`round_half_up_paise` (which would round the boundary case up) and never
`largest_remainder_allocate` (which is for splitting a pool across recipients, not for counting
how many whole units a pool covers). See `rounding.py`'s module docstring for why this floor
case doesn't reuse either existing primitive and is not being added there as a new one: unlike
`round_half_up_paise`/`largest_remainder_allocate`, which both produce a `Paise` result from a
`Fraction`, this operation's result is a unit **count** (a plain `int`), not a money value — it
doesn't share those primitives' `Fraction -> Paise` shape, and `budget.value // unit_cost.value`
on two already-non-negative ints is exact, unambiguous floor division with no rounding-mode
choice to make (there is only one correct floor of a non-negative ratio). Keeping it inline here,
next to the one caller that needs it and the safety comment explaining why, is more honest than
manufacturing a one-line `rounding.py` wrapper that would exist only to say "call `//`."
"""

from __future__ import annotations

from dataclasses import dataclass

from calc_engine.types import Paise


@dataclass(frozen=True, slots=True)
class BudgetConstrainedQuantity:
    """The budget-and-MOQ arithmetic ceiling for one SKU/supplier combination (§6.12).

    `max_affordable_units` is the floor of `budget / landed_cost_per_unit` — never rounded up
    (see module docstring). `meets_moq` is `True` whenever `moq is None` (no MOQ constraint
    declared) or `max_affordable_units >= moq`. `recommended_quantity` is
    `max_affordable_units` when the MOQ is met, and `0` when it is not — a batch below MOQ is
    usually not purchasable at all, so recommending `max_affordable_units` units in that case
    would silently suggest an order the seller cannot actually place. `units_short` names the
    exact shortfall (`moq - max_affordable_units`, floored at 0) so the caller can state it
    plainly rather than the seller having to infer it.
    """

    budget: Paise
    landed_cost_per_unit: Paise
    moq: int | None
    max_affordable_units: int
    meets_moq: bool
    recommended_quantity: int
    units_short: int


def budget_constrained_quantity(
    budget: Paise, landed_cost_per_unit: Paise, moq: int | None
) -> BudgetConstrainedQuantity:
    """§6.12's budget-and-MOQ arithmetic core.

    `landed_cost_per_unit.value <= 0` is a caller bug (division by zero, or a nonsensical
    non-positive cost) — raises `ValueError`, mirroring `landed_cost_per_unit`'s own
    `quantity <= 0` convention exactly.

    `budget.value < 0` is also a caller bug — there is no such thing as a negative purchasing
    ceiling — and raises `ValueError`.

    `budget.value == 0` is NOT a caller bug: unlike `quantity == 0` in `landed_cost_per_unit`
    (where dividing a shipping cost across zero units is mathematically undefined), dividing a
    zero budget by a positive unit cost is perfectly well-defined — it evaluates to zero
    affordable units. A seller with literally no budget this cycle is a real, if degenerate,
    business state, not a malformed call — so it is reported as `max_affordable_units=0`,
    never raised.

    `moq`, if provided, must be a positive int — a zero or negative MOQ is not a real minimum
    order quantity and is a caller bug, raising `ValueError`.
    """
    if landed_cost_per_unit.value <= 0:
        raise ValueError(
            f"budget_constrained_quantity requires landed_cost_per_unit > 0: "
            f"landed_cost_per_unit={landed_cost_per_unit.value}"
        )
    if budget.value < 0:
        raise ValueError(f"budget_constrained_quantity requires budget >= 0: budget={budget.value}")
    if moq is not None and moq <= 0:
        raise ValueError(f"budget_constrained_quantity requires moq > 0 when provided: moq={moq}")

    # Floor division on two non-negative ints — never rounds up (see module docstring).
    max_affordable_units = budget.value // landed_cost_per_unit.value

    meets_moq = moq is None or max_affordable_units >= moq
    units_short = 0 if meets_moq else moq - max_affordable_units
    recommended_quantity = max_affordable_units if meets_moq else 0

    return BudgetConstrainedQuantity(
        budget=budget,
        landed_cost_per_unit=landed_cost_per_unit,
        moq=moq,
        max_affordable_units=max_affordable_units,
        meets_moq=meets_moq,
        recommended_quantity=recommended_quantity,
        units_short=units_short,
    )
