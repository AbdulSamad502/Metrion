"""GrossOrderValue — deterministic-engine.md §5.2.

GrossOrderValue(line) = Σ[gross_item_amount], pre-discount, normalised to tax-exclusive per §8.1.
"""

from __future__ import annotations

from typing import Sequence

from calc_engine.types import ZERO, CanonicalLine, Paise


def gross_order_value(lines: Sequence[CanonicalLine]) -> Paise:
    """Sum of gross_item_amount across lines. Each line's amount is assumed already
    normalised to tax-exclusive by the caller (gst.normalization, §8.1) before reaching
    this function — this formula does no GST-basis handling itself.
    """
    total = ZERO
    for line in lines:
        total = total + line.gross_item_amount
    return total
