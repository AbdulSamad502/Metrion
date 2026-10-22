"""Total profit, `StorageCosts` and the contribution-profit v2 terms — deterministic-engine.md §5.8 amendment and §5.8.1 (Round 6, Option A).

**Inactive formula versions.** `CONTRIBUTION_PROFIT.v2` and `TOTAL_PROFIT.v1` are added here but are NOT the default and NOT seeded:
`contribution_profit.py` (v1) and `compute_period_pnl` are untouched and keep emitting `CONTRIBUTION_PROFIT.v1`. The release date
(Q15) is not set; nothing selects v2 yet.

Definitions (pools `p` ∈ advertising, storage, overhead; `Pool_p = SKU-level + Allocated_p + Unallocated_p`, conservation §5.10):

    ContributionProfit.v2 = NRR − COGS − MarketplaceFees − ShippingLogistics − ReturnRTOLosses − OtherAttributedCosts
                            − (AdvertisingSKU + AllocatedAdvertising) − (StorageSKU + AllocatedStorage)
    FullyAllocatedProfit  = ContributionProfit.v2 − AllocatedOverhead
    TotalProfit (A)       = ContributionProfit.v2 − UnallocatedAdvertising − UnallocatedStorage − AllocatedOverhead − UnallocatedOverhead

Overhead is **not** a parameter of contribution profit (A10). `TotalProfit` depends only on the pool sizes, so changing the allocation method
moves cost between the allocated and unallocated lines but never changes it (F5). A missing COGS or RTO classification makes contribution and
total profit `UNAVAILABLE` (E9); the unallocated lines still report.
"""

from __future__ import annotations

from dataclasses import dataclass

from calc_engine.formulas.allocation_outcome import AllocationOutcome
from calc_engine.types import ZERO, Paise, Unavailable

CONTRIBUTION_PROFIT_V2 = "CONTRIBUTION_PROFIT.v2"
TOTAL_PROFIT_V1 = "TOTAL_PROFIT.v1"
FULLY_ALLOCATED_PROFIT_V1 = "FULLY_ALLOCATED_PROFIT.v1"


@dataclass(frozen=True, slots=True)
class PoolSplit:
    """One business pool: `pool = sku_level + allocated + unallocated` (conservation)."""

    pool: Paise
    sku_level: Paise
    allocated: Paise
    unallocated: Paise
    reason: str | None = None
    detail: str | None = None


def pool_split(pool_total: Paise, sku_level: Paise, outcome: AllocationOutcome) -> PoolSplit:
    """Combine the directly attributed (SKU-level) part with the allocation outcome for the business-level remainder."""
    if outcome.pool != pool_total - sku_level:
        raise ValueError(
            f"allocation outcome is for a pool of {outcome.pool.value}, expected {(pool_total - sku_level).value} "
            f"(pool {pool_total.value} − SKU-level {sku_level.value})"
        )
    return PoolSplit(pool_total, sku_level, outcome.allocated_total, outcome.unallocated, outcome.reason, outcome.detail)


def contribution_profit_v2(
    net_realized_revenue: Paise,
    cogs: Paise | Unavailable,
    marketplace_fees: Paise,
    shipping_logistics: Paise,
    advertising_costs: Paise,
    storage_costs: Paise,
    return_rto_losses: Paise | Unavailable,
    other_attributed_costs: Paise,
) -> Paise | Unavailable:
    """`advertising_costs` and `storage_costs` are the SKU-level plus allocated parts only. No overhead term exists here (A10)."""
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
        - storage_costs
        - return_rto_losses
        - other_attributed_costs
    )


@dataclass(frozen=True, slots=True)
class ProfitStatement:
    contribution_profit: Paise | Unavailable
    fully_allocated_profit: Paise | Unavailable
    total_profit: Paise | Unavailable
    allocated_overhead: Paise
    unallocated_advertising: Paise
    unallocated_storage: Paise
    unallocated_overhead: Paise
    pl_expense_lines: Paise  # the expense lines of the P&L: SKU-level + allocated pools, other attributed costs, allocated overhead
    unallocated_lines: Paise  # the labelled unallocated lines (advertising + storage + overhead)
    advertising_reason: str | None = None
    storage_reason: str | None = None
    overhead_reason: str | None = None
    overhead_detail: str | None = None


def compute_profit_statement(
    *,
    net_realized_revenue: Paise,
    cogs: Paise | Unavailable,
    marketplace_fees: Paise,
    shipping_logistics: Paise,
    return_rto_losses: Paise | Unavailable,
    other_attributed_costs: Paise,
    advertising: PoolSplit,
    storage: PoolSplit,
    overhead: PoolSplit,
) -> ProfitStatement:
    cp = contribution_profit_v2(
        net_realized_revenue, cogs, marketplace_fees, shipping_logistics,
        advertising.sku_level + advertising.allocated, storage.sku_level + storage.allocated,
        return_rto_losses, other_attributed_costs,
    )
    overhead_in_pl = overhead.sku_level + overhead.allocated
    if isinstance(cp, Unavailable):
        fap: Paise | Unavailable = cp
        total: Paise | Unavailable = cp
    else:
        fap = cp - overhead_in_pl
        total = fap - advertising.unallocated - storage.unallocated - overhead.unallocated
    pl_lines = (
        advertising.sku_level + advertising.allocated + storage.sku_level + storage.allocated + other_attributed_costs + overhead_in_pl
    )
    unalloc = advertising.unallocated + storage.unallocated + overhead.unallocated
    return ProfitStatement(
        contribution_profit=cp, fully_allocated_profit=fap, total_profit=total,
        allocated_overhead=overhead_in_pl, unallocated_advertising=advertising.unallocated,
        unallocated_storage=storage.unallocated, unallocated_overhead=overhead.unallocated,
        pl_expense_lines=pl_lines, unallocated_lines=unalloc,
        advertising_reason=advertising.reason, storage_reason=storage.reason, overhead_reason=overhead.reason, overhead_detail=overhead.detail,
    )
