"""GSTOnFees_PotentiallyCreditable — deterministic-engine.md §5.9, D4-D6.

GSTOnFees_PotentiallyCreditable = Σ[line_component.tax_amount where kind = FEE]

Displayed as a distinct disclosure line, never folded into ContributionProfit unless a seller
explicitly toggles fee_gst_treatment=COST via manual_adjustment (§5.9, D5) — that toggle is
applied by the caller (compute_metric), not here.
"""

from __future__ import annotations

from typing import Sequence

from calc_engine.types import ZERO, CanonicalLine, Paise

_FEE_KIND = "FEE"


def gst_on_fees_potentially_creditable(lines: Sequence[CanonicalLine]) -> Paise:
    """A FEE component with tax_amount=None is treated as carrying no stated GST (not an
    unknown positive amount) — data-foundation.md §1.4 documents tax_amount as nullable
    ("GST charged on this fee, where stated"), and this is a disclosure-only figure, not a
    Contribution Profit input, so an absent value here does not trigger UNAVAILABLE."""
    total = ZERO
    for line in lines:
        for component in line.components:
            if component.component_kind == _FEE_KIND and component.tax_amount is not None:
                total = total + component.tax_amount
    return total


def apply_fee_gst_treatment(
    gst_on_fees: Paise,
    treatment: str,
    other_allocated_costs: Paise,
) -> tuple[Paise, Paise]:
    """T29, D5: a composition-scheme seller (who cannot claim ITC) may toggle GST-on-fees from
    a disclosure-only line into a real cost. Returns (disclosed_gst_on_fees,
    adjusted_other_allocated_costs).

    - `treatment == "CREDITABLE"` (default): unchanged — disclosed separately, never a
      Contribution Profit input (§5.9).
    - `treatment == "COST"`: the amount moves wholesale into OtherAllocatedCosts and the
      disclosure line becomes zero (it is no longer "potentially creditable" once reclassified
      as an actual cost) — the caller is responsible for recording this toggle as a manual
      input (§7), this function only performs the reclassification arithmetic.
    """
    if treatment == "CREDITABLE":
        return gst_on_fees, other_allocated_costs
    if treatment == "COST":
        return ZERO, other_allocated_costs + gst_on_fees
    raise ValueError(f"unknown fee_gst_treatment {treatment!r} — must be CREDITABLE or COST")
