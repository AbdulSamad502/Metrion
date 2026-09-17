"""V-TAX-003 plausibility check against gst_slab_reference — deterministic-engine.md §8.2.1 (U7, confirmed).

Backs a plausibility/warning check only — never GST classification or tax advice, never
blocking, never asserts a rate is correct. An observed rate with no matching seeded slab
produces a WARNING; the row stays included in aggregates either way (§8.2.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Sequence


@dataclass(frozen=True, slots=True)
class GstSlabRow:
    """Mirrors one row of the `gst_slab_reference` table (§8.2.1)."""

    rate_pct: Fraction
    label: str
    effective_from: date
    effective_to: date | None
    confidence: str = "PROVISIONAL"


@dataclass(frozen=True, slots=True)
class PlausibilityResult:
    matched: bool
    severity: str  # always "WARNING" when matched is False; this check never raises ERROR


def check_rate_plausibility(observed_rate_pct: Fraction, slabs: Sequence[GstSlabRow], as_of: date) -> PlausibilityResult:
    """WARNING (never ERROR) when `observed_rate_pct` matches no slab active as of `as_of`.

    A slab is active as of `as_of` when `effective_from <= as_of` and
    (`effective_to` is None or `as_of <= effective_to`) — never applied retroactively to a
    row that predates its own `effective_from` (§8.2.1).
    """
    for slab in slabs:
        if slab.effective_from > as_of:
            continue
        if slab.effective_to is not None and as_of > slab.effective_to:
            continue
        if slab.rate_pct == observed_rate_pct:
            return PlausibilityResult(matched=True, severity="INFO")
    return PlausibilityResult(matched=False, severity="WARNING")
