"""ContributionProfit / ContributionMargin% — deterministic-engine.md §5.8.

ContributionProfit =
      NetRealizedRevenue
    − COGS
    − MarketplaceFees
    − ShippingLogistics
    − AdvertisingCosts
    − ReturnRTOLosses
    − OtherAllocatedCosts

ContributionMargin% = ContributionProfit / NetRealizedRevenue × 100
Undefined — never zero — when NetRealizedRevenue = 0 (E8).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from calc_engine.types import Paise, Unavailable


def contribution_profit(
    net_realized_revenue: Paise,
    cogs: Paise | Unavailable,
    marketplace_fees: Paise,
    shipping_logistics: Paise,
    advertising_costs: Paise,
    return_rto_losses: Paise | Unavailable,
    other_allocated_costs: Paise,
) -> Paise | Unavailable:
    """Propagates Unavailable from COGS or ReturnRTOLosses (E9) — a missing SKU cost or an
    unclassified RTO outcome makes Contribution Profit UNAVAILABLE, never a number computed
    as if the missing term were zero."""
    if isinstance(cogs, Unavailable):
        return cogs
    if isinstance(return_rto_losses, Unavailable):
        return return_rto_losses
    return (
        net_realized_revenue
        - cogs
        - marketplace_fees
        - shipping_logistics
        - advertising_costs
        - return_rto_losses
        - other_allocated_costs
    )


def contribution_margin_pct(profit: Paise, net_realized_revenue: Paise) -> Fraction | Literal["UNDEFINED"]:
    """E8: NetRealizedRevenue == 0 -> the literal string "UNDEFINED", never 0, never an exception."""
    if net_realized_revenue.value == 0:
        return "UNDEFINED"
    return Fraction(profit.value, net_realized_revenue.value) * 100
