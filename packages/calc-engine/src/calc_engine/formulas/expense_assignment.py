"""Multi-SKU assignment of one expense — deterministic-engine.md §5.18.3 (APPROVED Round 8; Q33 bases and seller-chosen assignment approved Round 6).

The seller assigns ONE ledger record to several SKUs and picks the split basis: `EQUAL`, `EXPLICIT_SHARES` (basis points per SKU, summing to at most 10,000), or one of the
data-driven bases `NET_REVENUE`, `UNITS`, `ORDERS` (section 5.10.1, restricted to the assigned SKUs: the shares follow each SKU's own revenue, net units or order count for the
period, through the same `allocate_with_basis` the other pools use). Pure integer arithmetic (floor division and largest remainder, ties by SKU order); no float, no clock, no
database. Whatever is not assigned stays visible as an unassigned
business-level remainder with its reason, and conservation always holds: assigned + unassigned = amount.

* No basis chosen -> nothing assigned, the whole amount unassigned (`BASIS_NOT_SELECTED`).
* A SKU not in the seller's catalog gets no share and is returned in `unmapped` (the caller puts it in the review queue, Q29): under EQUAL the amount is split across the
  mapped SKUs only; under EXPLICIT_SHARES that SKU's basis points are simply not assigned and stay in the unassigned remainder.
* Shares summing above 10,000 basis points are INVALID (`SHARES_ABOVE_100_PERCENT`), rejected at entry (`validate`), and never computed.
* Assigned shares are SKU-level but flagged manual (Q29): the feed counts them in the pool's manual SKU-level part.
* A single-SKU assignment is the ordinary Q29 manual tag. A negative amount (a refund) is split with the same rule and keeps its sign on every share.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from calc_engine.formulas.allocation import AllocationBasis
from calc_engine.formulas.allocation_outcome import AllocationTarget, allocate_with_basis
from calc_engine.types import ZERO, Paise, Unavailable

DATA_BASES = ("NET_REVENUE", "UNITS", "ORDERS")
BASES = ("EQUAL", "EXPLICIT_SHARES", *DATA_BASES)
ASSIGNMENT_PERIOD = "ASSIGNMENT_PERIOD"  # the data window and scope every basis target must carry, so a mismatch is the caller's error and not silently mixed
ASSIGNMENT_SCOPE = "BUSINESS"
FULL_BP = 10_000
BASIS_NOT_SELECTED = "BASIS_NOT_SELECTED"
NO_MAPPED_SKU = "NO_MAPPED_SKU"
SHARES_ABOVE_100_PERCENT = "SHARES_ABOVE_100_PERCENT"
INVALID_ASSIGNMENT = "INVALID_ASSIGNMENT"


@dataclass(frozen=True, slots=True)
class SkuAssignment:
    basis: str | None
    shares: tuple[tuple[str, int | None], ...]  # (sku, basis points); basis points are None under EQUAL


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    assigned: Mapping[str, Paise]  # mapped SKU -> its share (SKUs in sorted order)
    unassigned: Paise
    reason: str | None  # why anything is unassigned (None when everything is assigned)
    unmapped: tuple[str, ...]  # SKUs not in the catalog: no share, to the review queue

    @property
    def assigned_total(self) -> Paise:
        total = ZERO
        for v in self.assigned.values():
            total = total + v
        return total


def basis_target(sku: str, *, net_revenue: Paise | Unavailable | None = None, units_sold: int | None = None, units_returned: int | None = None,
                 order_ids: frozenset[str] | None = None) -> AllocationTarget:
    """One SKU's basis data for a data-driven assignment; a value left `None` is "not available" (never zero)."""
    return AllocationTarget(sku, ASSIGNMENT_PERIOD, ASSIGNMENT_SCOPE, net_revenue=net_revenue, units_sold=units_sold, units_returned=units_returned, order_ids=order_ids)


def validate(assignment: SkuAssignment) -> str | None:
    """The reason an assignment cannot be accepted at entry, or None. `SHARES_ABOVE_100_PERCENT` for explicit shares summing above 10,000 basis points."""
    skus = [s for s, _ in assignment.shares]
    if assignment.basis not in BASES or not skus or len(set(skus)) != len(skus) or any(not isinstance(s, str) or not s.strip() for s in skus):
        return INVALID_ASSIGNMENT
    if assignment.basis == "EQUAL" or assignment.basis in DATA_BASES:
        return INVALID_ASSIGNMENT if any(bp is not None for _, bp in assignment.shares) else None  # no basis points: the data decides (or the split is equal)
    bps = [bp for _, bp in assignment.shares]
    if any(isinstance(bp, bool) or not isinstance(bp, int) or bp < 1 for bp in bps):
        return INVALID_ASSIGNMENT
    return SHARES_ABOVE_100_PERCENT if sum(bp for bp in bps if bp is not None) > FULL_BP else None


def _largest_remainder(total: int, numerators: Sequence[tuple[str, int]], denominator: int) -> dict[str, int]:
    """Splits `total` (>= 0) in proportion numerator/denominator: the floor of each exact share, then one paisa at a time to the largest fractional parts (ties by SKU)."""
    floors = {sku: (total * n) // denominator for sku, n in numerators}
    left = total * sum(n for _, n in numerators) // denominator - sum(floors.values())
    order = sorted(numerators, key=lambda sn: (-((total * sn[1]) % denominator), sn[0]))
    for sku, _ in order[:left]:
        floors[sku] += 1
    return floors


def assign(amount: Paise, assignment: SkuAssignment, catalog: Mapping[str, str], basis_data: Mapping[str, AllocationTarget] | None = None) -> AssignmentResult:
    if assignment.basis is None:
        return AssignmentResult({}, amount, BASIS_NOT_SELECTED, ())
    problem = validate(assignment)
    if problem is not None:
        return AssignmentResult({}, amount, problem, ())
    sign = -1 if amount.value < 0 else 1
    magnitude = abs(amount.value)
    mapped = [(catalog[s], bp) for s, bp in assignment.shares if s in catalog]
    unmapped = tuple(sorted(s for s, _ in assignment.shares if s not in catalog))
    if not mapped:
        return AssignmentResult({}, amount, NO_MAPPED_SKU, unmapped)
    if assignment.basis in DATA_BASES:
        data = basis_data or {}
        targets = [data.get(sku) or AllocationTarget(sku, ASSIGNMENT_PERIOD, ASSIGNMENT_SCOPE) for sku, _ in mapped]  # a SKU with no data: every figure "not available"
        outcome = allocate_with_basis(Paise(magnitude), pool_period=ASSIGNMENT_PERIOD, pool_scope=ASSIGNMENT_SCOPE, basis=AllocationBasis(assignment.basis), targets=targets)
        assigned_data = {sku: Paise(sign * v.value) for sku, v in sorted(outcome.allocated.items())}
        rest_data = Paise(amount.value - sum((v.value for v in assigned_data.values()), 0))
        return AssignmentResult(assigned_data, rest_data, outcome.reason if rest_data.value != 0 else ("UNMAPPED_SKU" if unmapped else None), unmapped)
    if assignment.basis == "EQUAL":
        parts = _largest_remainder(magnitude, [(sku, 1) for sku, _ in mapped], len(mapped))
    else:
        parts = _largest_remainder(magnitude, [(sku, int(bp or 0)) for sku, bp in mapped], FULL_BP)
    assigned = {sku: Paise(sign * parts[sku]) for sku in sorted(parts)}
    total = ZERO
    for v in assigned.values():
        total = total + v
    rest = Paise(amount.value - total.value)
    reason = None
    if rest.value != 0:
        reason = "SHARES_BELOW_100_PERCENT" if not unmapped else "UNMAPPED_SKU"
    elif unmapped:
        reason = "UNMAPPED_SKU"
    return AssignmentResult(assigned, rest, reason, unmapped)
