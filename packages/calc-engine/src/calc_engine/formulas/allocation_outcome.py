"""Allocation with an explicit basis — deterministic-engine.md §5.10 and §5.10.1 (amended 2026-10-15; Rounds 6–8).

`allocate_pool` (allocation.py) stays the arithmetic primitive and is unchanged. This module is the policy around it:

- **No default basis.** `basis=None` means the seller has not selected one: the whole pool stays unallocated with `BASIS_NOT_SELECTED`.
  There is no hard-coded `NET_REVENUE` here (the older `expense_pools.allocate_account_level_expense_pool`, which has no production caller, is
  left untouched for its existing tests).
- **Weights come from the data the basis names:** `NET_REVENUE` = net realized revenue, `UNITS` = units sold minus units returned/RTO'd,
  `ORDERS` = distinct order ids per SKU. A missing input is never counted as zero; any in-scope target without the field makes the basis
  unusable and the pool unallocated with a reason code. Targets with a zero or negative weight are excluded and reported.
- **Same period and channel scope as the pool**, otherwise `INVALID_BASIS` with detail `PERIOD_MISMATCH` / `SCOPE_MISMATCH`.
- **Conservation:** allocated + unallocated == pool, always (largest remainder, D8). Zero denominators never divide.

Pure: no I/O, no clock. Money is `Paise`; weights are exact `Fraction`s built from integers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Mapping, Sequence

from calc_engine.formulas.allocation import AllocationBasis, allocate_pool
from calc_engine.types import ZERO, Confidence, Paise, Unavailable

# Reason codes (spec §5.10; additions approved in Round 6, 7c46d9d).
BASIS_NOT_SELECTED = "BASIS_NOT_SELECTED"
NO_REVENUE_FOR_PERIOD = "NO_REVENUE_FOR_PERIOD"
ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
UNITS_UNAVAILABLE = "UNITS_UNAVAILABLE"
ORDERS_UNAVAILABLE = "ORDERS_UNAVAILABLE"
BASIS_DATA_UNAVAILABLE = "BASIS_DATA_UNAVAILABLE"
INVALID_BASIS = "INVALID_BASIS"
PERIOD_MISMATCH = "PERIOD_MISMATCH"
SCOPE_MISMATCH = "SCOPE_MISMATCH"
NON_POSITIVE_WEIGHT = "NON_POSITIVE_WEIGHT"


@dataclass(frozen=True, slots=True)
class AllocationTarget:
    """One allocation target (a SKU, or a channel) with the basis data the caller has for it. `None` means "not available", never zero."""

    ref: str
    data_period: str
    data_scope: str
    net_revenue: Paise | Unavailable | None = None
    units_sold: int | None = None
    units_returned: int | None = None  # returns + RTO; None = unknown (not zero)
    order_ids: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class AllocationOutcome:
    pool: Paise
    basis: AllocationBasis | None
    allocated: Mapping[str, Paise]
    unallocated: Paise
    reason: str | None = None
    detail: str | None = None
    excluded: Mapping[str, str] = field(default_factory=dict)
    confidence: Confidence | None = None  # DERIVED whenever anything was allocated (§5.10)

    @property
    def allocated_total(self) -> Paise:
        total = ZERO
        for v in self.allocated.values():
            total = total + v
        return total


def _unallocated(pool: Paise, basis: AllocationBasis | None, reason: str, detail: str | None = None,
                 excluded: Mapping[str, str] | None = None) -> AllocationOutcome:
    return AllocationOutcome(pool=pool, basis=basis, allocated={}, unallocated=pool, reason=reason, detail=detail, excluded=dict(excluded or {}))


def _weights(basis: AllocationBasis, targets: Sequence[AllocationTarget]) -> tuple[dict[str, Fraction], str | None]:
    """Per-target integer weights, or `(…, reason)` when any in-scope target lacks the data the basis needs."""
    out: dict[str, Fraction] = {}
    for t in targets:
        if basis is AllocationBasis.NET_REVENUE:
            if t.net_revenue is None or isinstance(t.net_revenue, Unavailable):
                return {}, BASIS_DATA_UNAVAILABLE
            out[t.ref] = Fraction(t.net_revenue.value)
        elif basis is AllocationBasis.UNITS:
            if t.units_sold is None or t.units_returned is None:
                return {}, UNITS_UNAVAILABLE
            out[t.ref] = Fraction(t.units_sold - t.units_returned)
        else:  # ORDERS
            if t.order_ids is None:
                return {}, ORDERS_UNAVAILABLE
            out[t.ref] = Fraction(len(t.order_ids))
    return out, None


def allocate_with_basis(
    pool: Paise,
    *,
    pool_period: str,
    pool_scope: str,
    basis: AllocationBasis | None,
    targets: Sequence[AllocationTarget],
) -> AllocationOutcome:
    if basis is None:
        return _unallocated(pool, None, BASIS_NOT_SELECTED)

    if not targets:
        reason = {
            AllocationBasis.NET_REVENUE: NO_REVENUE_FOR_PERIOD,
            AllocationBasis.UNITS: UNITS_UNAVAILABLE,
            AllocationBasis.ORDERS: ORDERS_UNAVAILABLE,
        }[basis]
        return _unallocated(pool, basis, reason)

    if any(t.data_period != pool_period for t in targets):
        return _unallocated(pool, basis, INVALID_BASIS, PERIOD_MISMATCH)
    if any(t.data_scope != pool_scope for t in targets):
        return _unallocated(pool, basis, INVALID_BASIS, SCOPE_MISMATCH)

    weights, missing = _weights(basis, targets)
    if missing is not None:
        return _unallocated(pool, basis, missing)

    # stable order by ref -> AC1 determinism regardless of the caller's order
    eligible = [(ref, w) for ref, w in sorted(weights.items()) if w > 0]
    excluded = {ref: NON_POSITIVE_WEIGHT for ref, w in sorted(weights.items()) if w <= 0}
    if not eligible:
        return _unallocated(pool, basis, ZERO_DENOMINATOR, excluded=excluded)

    allocated = allocate_pool(pool, eligible, basis)
    return AllocationOutcome(
        pool=pool, basis=basis, allocated=dict(allocated), unallocated=ZERO, reason=None, excluded=excluded, confidence=Confidence.DERIVED
    )
