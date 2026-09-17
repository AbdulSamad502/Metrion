"""CancellationReversal / ReturnReversal / RTOUnrecoveredRevenue — deterministic-engine.md §5.4.

CancellationReversal(line)  = GrossOrderValue  where state = CANCELLED            -- blocked, A6
ReturnReversal(line)        = refunded_amount  per settlement treatment (R5)
RTOUnrecoveredRevenue(line) = GrossOrderValue − SellerFundedDiscounts             -- where RTO, never settled (A7)

Every function here operates on a single CanonicalLine and returns Paise | Unavailable —
never a silent zero for a marketplace whose adapter cannot yet resolve the relevant status
(C1/C2). Aggregation across lines, and how an Unavailable line is excluded/disclosed at the
period level, is net_realized_revenue.py's responsibility, not this module's.
"""

from __future__ import annotations

from calc_engine.formulas.component_sum import BearerResolver
from calc_engine.formulas.discount_attribution import seller_funded_discounts
from calc_engine.types import ZERO, CanonicalLine, Paise, Unavailable


def cancellation_reversal(line: CanonicalLine) -> Paise | Unavailable:
    if line.cancellation_state is None:
        return Unavailable(
            reason=f"cancellation status not resolvable for marketplace {line.marketplace!r} (C1)",
            missing_inputs=("cancellation_state",),
        )
    if line.cancellation_state == "CANCELLED":
        return line.gross_item_amount
    return ZERO


def return_reversal(line: CanonicalLine) -> Paise | Unavailable:
    if line.return_status is None:
        return Unavailable(
            reason=f"return status not resolvable for marketplace {line.marketplace!r} (C1/A6)",
            missing_inputs=("return_status",),
        )
    if line.return_status != "RETURNED":
        return ZERO
    if line.refunded_amount is None:
        return Unavailable(
            reason="return occurred but refunded amount is not yet known (settlement absent, no manual override)",
            missing_inputs=("refunded_amount",),
        )
    return line.refunded_amount


def rto_unrecovered_revenue(line: CanonicalLine, bearer_resolver: BearerResolver) -> Paise | Unavailable:
    if line.rto_status is None:
        return Unavailable(
            reason=f"RTO status not resolvable for marketplace {line.marketplace!r} (C2/A7)",
            missing_inputs=("rto_status",),
        )
    if line.rto_status != "RTO":
        return ZERO
    seller_discount = seller_funded_discounts([line], bearer_resolver)
    return line.gross_item_amount - seller_discount
