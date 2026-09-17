"""weighted_average_cost / billable_quantity / cogs — deterministic-engine.md §5.6, D3.

COGS(line) = weighted_average_cost(sku, as_of = document_date) × billable_quantity

billable_quantity = quantity − returned_qty − rto_qty   (ALL outcomes excluded — see the
§5.6 correction: a returned/RTO'd unit's cost is reversed out of ordinary COGS regardless of
whether it was recovered sellable, damaged, or lost. Recovered-sellable units then carry zero
cost anywhere; damaged/lost units carry their cost exactly once, inside ReturnRTOLosses
(return_rto_losses.py) — never here, to avoid double-counting.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from calc_engine.types import CanonicalLine, Paise, Unavailable


@dataclass(frozen=True, slots=True)
class CostEntry:
    """One weighted-average-cost data point from a `cogs_per_unit` manual_adjustment (§7.2.1)."""

    amount_paise: Paise
    effective_from: date


def weighted_average_cost(sku: str, as_of: date, cost_history: Sequence[CostEntry]) -> Paise | Unavailable:
    """Latest CostEntry with effective_from <= as_of (D3, E11). Unavailable if none exists —
    a missing SKU cost is never treated as zero (E9, AC8)."""
    eligible = [entry for entry in cost_history if entry.effective_from <= as_of]
    if not eligible:
        return Unavailable(
            reason=f"no cogs_per_unit adjustment for sku {sku!r} effective on or before {as_of.isoformat()}",
            missing_inputs=("cogs_per_unit",),
        )
    latest = max(eligible, key=lambda entry: entry.effective_from)
    return latest.amount_paise


def billable_quantity(line: CanonicalLine) -> int | Unavailable:
    """quantity minus every returned/RTO'd unit, regardless of outcome (§5.6, corrected).

    Cancellation splits into two cases (T10 vs T11, E15) that are NOT the same:

    - **Cancelled before dispatch** (`dispatch_date is None`): the order was never fulfilled —
      billable_quantity is unambiguously 0. No inventory left the warehouse, so there is
      nothing to classify.
    - **Cancelled after dispatch** (`dispatch_date` is set): the goods physically left the
      warehouse before the order was cancelled — functionally the same open question as an
      RTO (did the inventory come back sellable, damaged, or is it lost?). E15 only specifies
      that forward logistics is retained as a cost (handled naturally: cancellation never
      excludes a line from ShippingLogistics, only actual RETURNED/RTO lines do — see
      component_sum.py's `exclude_rto_lines`). E15 says nothing about COGS for this case, and
      guessing "recovered" would silently overstate profit if the goods were actually lost.
      This function therefore requires the same `rto_outcome` classification an RTO would
      need, returning UNAVAILABLE until it's supplied — never a silent zero. **This is an
      interpretive extension beyond E15's literal text, not a re-statement of something
      already decided — flag for confirmation alongside the other inferences in this module.**
    """
    if line.cancellation_state == "CANCELLED":
        if line.dispatch_date is None:
            return 0
        if line.rto_outcome is None:
            return Unavailable(
                reason="line cancelled after dispatch but inventory outcome (rto_outcome) not yet classified",
                missing_inputs=("rto_outcome",),
            )
        if line.rto_outcome == "RECOVERED_SELLABLE":
            return 0
        return line.quantity  # RECOVERED_DAMAGED or LOST: full cost consumed, goods didn't come back sellable

    remaining = line.quantity - line.returned_qty - line.rto_qty
    if remaining < 0:
        raise ValueError(
            f"billable_quantity negative for line {line.sales_line_id}: "
            f"quantity={line.quantity}, returned_qty={line.returned_qty}, rto_qty={line.rto_qty}"
        )
    return remaining


def cogs(line: CanonicalLine, unit_cost: Paise | Unavailable) -> Paise | Unavailable:
    """COGS(line) = unit_cost × billable_quantity(line). Propagates Unavailable from either
    input (E9) — a missing SKU cost or an unclassified cancelled-after-dispatch outcome both
    make COGS UNAVAILABLE, never a number computed as if the missing term were zero."""
    if isinstance(unit_cost, Unavailable):
        return unit_cost
    quantity = billable_quantity(line)
    if isinstance(quantity, Unavailable):
        return quantity
    return unit_cost * quantity


def parse_cogs_per_unit_adjustment(value: object, created_at: date) -> CostEntry:
    """Parses a `manual_adjustment.value` for field="cogs_per_unit" (§7.2.1, both shapes):

    - Pre-amendment shape: a bare scalar paise int -> effective_from defaults to `created_at`.
    - Amended shape: `{"amount_paise": int, "effective_from"?: "YYYY-MM-DD"}` -> effective_from
      defaults to `created_at` when the key is present but null/absent, exactly as the
      amendment specifies (backward compatible with any adjustment already recorded under the
      old shape).
    """
    if isinstance(value, bool):
        raise TypeError(f"cogs_per_unit value must be an int or dict, got bool: {value!r}")
    if isinstance(value, int):
        return CostEntry(Paise(value), created_at)
    if isinstance(value, dict):
        amount = value["amount_paise"]
        effective_from = value.get("effective_from")
        if effective_from is None:
            effective_from = created_at
        elif isinstance(effective_from, str):
            effective_from = date.fromisoformat(effective_from)
        return CostEntry(Paise(amount), effective_from)
    raise TypeError(f"unrecognized cogs_per_unit value shape: {value!r}")
