"""round_half_up_paise, largest_remainder_allocate — deterministic-engine.md §5.11, D8.

Negative amounts round half-away-from-zero (confirmed decision, §G of the approved plan).
Rounding happens once, at the final presented figure — never on intermediates (§5.11).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Sequence, TypeVar

from calc_engine.types import ZERO, Paise

T = TypeVar("T")


def round_half_up_paise(amount: Fraction) -> Paise:
    """Half-up at paise; negative amounts round half-away-from-zero (confirmed, §G)."""
    sign = 1 if amount >= 0 else -1
    magnitude = abs(amount)
    whole, remainder = divmod(magnitude.numerator, magnitude.denominator)
    if 2 * remainder >= magnitude.denominator:
        whole += 1
    return Paise(sign * whole)


def largest_remainder_allocate(total: Paise, weights: Sequence[tuple[T, Fraction]]) -> dict[T, Paise]:
    """Allocate `total` across `weights` so shares sum exactly to `total` (AC7, §5.10).

    `weights` MUST already be in a stable, caller-defined order (e.g. sorted by target_ref) —
    determinism (AC1) depends on tie-breaking by that order, never by dict/DB row order.
    A zero weight_sum returns an all-zero allocation — reported unallocated, never dropped
    (§5.10: "lines with zero or negative net revenue are excluded ... and reported as
    unallocated").
    """
    if not weights:
        return {}

    weight_sum = sum((w for _, w in weights), start=Fraction(0))
    if weight_sum == 0:
        return {ref: ZERO for ref, _ in weights}

    sign = 1 if total.value >= 0 else -1
    magnitude = abs(total.value)

    raw_shares = [(ref, Fraction(magnitude) * w / weight_sum) for ref, w in weights]
    floors = [(ref, share.numerator // share.denominator) for ref, share in raw_shares]
    remainders = [(ref, share - (share.numerator // share.denominator)) for ref, share in raw_shares]

    shortfall = magnitude - sum(f for _, f in floors)

    # Deterministic tie-break: largest remainder first; ties broken by input order index,
    # never by float comparison or dict/DB row order (AC1).
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i][1], i))

    result: dict[T, int] = {ref: floor_val for ref, floor_val in floors}
    for i in order[:shortfall]:
        ref = weights[i][0]
        result[ref] += 1

    allocated_magnitude = sum(result.values())
    assert allocated_magnitude == magnitude, (
        f"largest_remainder_allocate invariant violated: {allocated_magnitude} != {magnitude}"
    )  # AC7 — displayed components must reconcile exactly to displayed totals

    return {ref: Paise(sign * v) for ref, v in result.items()}
