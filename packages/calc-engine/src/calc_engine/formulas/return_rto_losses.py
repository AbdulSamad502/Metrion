"""ReturnRTOLosses — deterministic-engine.md §5.7, R6.

ReturnRTOLosses(line) =
      COGS_of_unrecovered_or_damaged_units
    + forward_logistics_incurred_on_failed_delivery
    + reverse_logistics_charged
    + non_refunded_fees_retained_by_marketplace

Outcome table (§5.7):
  RECOVERED_SELLABLE -> COGS term is zero (goods intact); both logistics legs charged.
  RECOVERED_DAMAGED   -> COGS term is the unit's full cost; both logistics legs charged.
  LOST                -> COGS term is the unit's full cost; forward leg only (nothing to
                          return, so no reverse leg).

`forward_logistics`, `reverse_logistics`, and `non_refunded_fees_retained` are pre-resolved
Paise amounts supplied by the caller (extracted from this line's components using whatever
component_code taxonomy distinguishes forward/reverse logistics — that mapping is an
adapter/component_code concern owned by data-foundation.md, not this formula). This function
composes already-resolved amounts; it does not itself inspect `line.components`.
"""

from __future__ import annotations

from calc_engine.types import ZERO, CanonicalLine, Paise, Unavailable

_RECOVERED_SELLABLE = "RECOVERED_SELLABLE"
_RECOVERED_DAMAGED = "RECOVERED_DAMAGED"
_LOST = "LOST"


def return_rto_losses(
    line: CanonicalLine,
    unit_cost: Paise | Unavailable,
    forward_logistics: Paise,
    reverse_logistics: Paise,
    non_refunded_fees_retained: Paise,
) -> Paise | Unavailable:
    is_return_or_rto = line.return_status == "RETURNED" or line.rto_status == "RTO"
    if not is_return_or_rto:
        return ZERO

    if line.rto_outcome is None:
        return Unavailable(
            reason="return/RTO confirmed but inventory outcome (rto_outcome) not yet classified",
            missing_inputs=("rto_outcome",),
        )

    affected_qty = line.returned_qty + line.rto_qty

    if line.rto_outcome == _RECOVERED_SELLABLE:
        cogs_loss = ZERO
        logistics = forward_logistics + reverse_logistics
    elif line.rto_outcome == _RECOVERED_DAMAGED:
        if isinstance(unit_cost, Unavailable):
            return unit_cost
        cogs_loss = unit_cost * affected_qty
        logistics = forward_logistics + reverse_logistics
    elif line.rto_outcome == _LOST:
        if isinstance(unit_cost, Unavailable):
            return unit_cost
        cogs_loss = unit_cost * affected_qty
        logistics = forward_logistics  # nothing to return — no reverse leg
    else:
        raise ValueError(f"unknown rto_outcome {line.rto_outcome!r} on line {line.sales_line_id}")

    return cogs_loss + logistics + non_refunded_fees_retained
