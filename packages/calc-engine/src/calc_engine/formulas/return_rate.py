"""ReturnRate% — docs/specs/anomaly-detection.md §6.1 `RETURN_RATE_PCT`.

ReturnRate%(lines) = returned_qty_all_outcomes / quantity x 100, aggregated over one period's
`CanonicalLine`s (engine §5.6's `billable_quantity` inputs).

"All outcomes" = a plain return AND an RTO both count toward the numerator —
`total_returned_all_outcomes = sum(line.returned_qty + line.rto_qty for line in lines)`. This
is not invented here: `formulas/return_rto_losses.py`'s own `affected_qty = line.returned_qty
+ line.rto_qty` already combines the two fields this exact way, for a different purpose (the
COGS/logistics loss a returned-or-RTO'd unit causes) — this formula mirrors that established
combination rather than deciding its own. `deterministic-engine.md` §7.4.2's "never collapses
the three RTO outcomes (RECOVERED_SELLABLE/RECOVERED_DAMAGED/LOST) into one bucket" rule is
about NARRATION distinguishing those three inventory outcomes from each other — it says
nothing about whether an RTO'd unit counts as "returned" for a returned-quantity ratio, and
this formula's numerator is not that narration.

Pure `Fraction` arithmetic — no float, and `Paise` never appears here (this is a UNIT quantity
ratio, not a money figure).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Sequence

from calc_engine.types import CanonicalLine, Unavailable

CALCULATION_BASIS = (
    "ReturnRate% = (returned_qty + rto_qty) / quantity x 100, summed over the period's lines "
    "(anomaly-detection.md §6.1 RETURN_RATE_PCT)"
)


def return_rate_pct(lines: Sequence[CanonicalLine]) -> Fraction | Unavailable:
    """Never a division by zero, never a fabricated 0%/100% — a period with no billable
    quantity (empty `lines`, or every line's `quantity` is zero) is `Unavailable`, exactly the
    same "missing input is UNAVAILABLE, never zero" discipline every other formula in this
    package already follows."""
    total_quantity = sum(line.quantity for line in lines)
    if total_quantity == 0:
        return Unavailable(
            reason="no lines with non-zero quantity in scope for this period",
            missing_inputs=("quantity",),
        )

    total_returned_all_outcomes = sum(line.returned_qty + line.rto_qty for line in lines)
    return Fraction(total_returned_all_outcomes, total_quantity) * 100
