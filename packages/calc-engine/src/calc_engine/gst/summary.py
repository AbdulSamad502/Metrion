"""GST period summary — deterministic-engine.md §8.3.

`gst_period_summary()` is a pure orchestration over the existing `sum_components()` primitive
(formulas/component_sum.py): for each tax head it issues one `sum_components(..., side="INVOICE")`
call and collects the result. No new arithmetic is introduced here — the one summation step
already lives in `sum_components`, and this module reuses it unchanged.

`side="INVOICE"` is a deliberate choice: GST liability is what the seller charged the buyer
(the invoice side), not a settlement-mechanics figure.
"""

from __future__ import annotations

from typing import Sequence

from calc_engine.formulas.component_sum import sum_components
from calc_engine.types import CanonicalLine, Paise

_TAX_KIND = "TAX"

DEFAULT_TAX_HEADS: frozenset[str] = frozenset({"CGST", "SGST", "IGST", "UTGST", "CESS"})


def gst_period_summary(
    lines: Sequence[CanonicalLine],
    *,
    tax_heads: frozenset[str] = DEFAULT_TAX_HEADS,
) -> dict[str, Paise]:
    """Sum TAX components per tax head, invoice side, over `lines`.

    Every head in `tax_heads` appears in the returned dict, even when its sum is `ZERO` — a
    period with no CESS charged is a real, legitimate zero, not a missing value, mirroring
    `tax_treatment.gst_on_fees_potentially_creditable`'s established precedent that a pure
    summation over already-present canonical components never fails for missing data.

    This function has no `Unavailable` path: summing real, already-present canonical
    components is always possible, by construction — there is no missing input it could
    depend on.
    """
    return {
        head: sum_components(lines, component_codes=frozenset({head}), component_kind=_TAX_KIND, side="INVOICE")
        for head in sorted(tax_heads)
    }


__all__ = ["gst_period_summary", "DEFAULT_TAX_HEADS"]
