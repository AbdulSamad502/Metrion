"""allocate_pool / AllocationBasis — deterministic-engine.md §5.10, D7-D8.

allocated_cost(line) = pool_amount × ( NetRealizedRevenue(line) / Σ NetRealizedRevenue(pool_scope) )

Allocation basis is configurable: NET_REVENUE (default) | UNITS | ORDERS.
Every allocated figure is DERIVED and names its basis on display.
Remainders are distributed by largest remainder so allocations sum exactly to the pool (D8).
Lines with zero or negative net revenue are excluded from a NET_REVENUE basis and reported as
unallocated.
"""

from __future__ import annotations

from enum import Enum
from fractions import Fraction
from typing import Sequence, TypeVar

from calc_engine.rounding import largest_remainder_allocate
from calc_engine.types import Paise

T = TypeVar("T")


class AllocationBasis(str, Enum):
    NET_REVENUE = "NET_REVENUE"
    UNITS = "UNITS"
    ORDERS = "ORDERS"


def allocate_pool(
    pool: Paise,
    weights: Sequence[tuple[T, Fraction]],
    basis: AllocationBasis,
) -> dict[T, Paise]:
    """Allocates `pool` across `weights` under the largest-remainder rule (D8).

    `weights` is caller-prepared per `basis`: for NET_REVENUE, the caller must already have
    excluded targets with zero or negative net revenue (§5.10) — this function does not
    inspect the basis to decide inclusion, it only performs the arithmetic. `weights` must be
    in a stable, deterministic order (e.g. sorted by target_ref) for AC1 to hold.
    """
    return largest_remainder_allocate(pool, weights)
