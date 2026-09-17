"""MarketplaceFees — deterministic-engine.md §5.6, with duplicate-fee detection (V-FEE-002, E12).

MarketplaceFees = Σ[FEE where side = settlement, else invoice], tax-exclusive

`V-FEE-002` (data-foundation.md §4.2, WARNING) flags candidate duplicate fee lines — equal
amount, overlapping semantics — e.g. Amazon's reference row where `Platform Fee` and
`Marketplace Fee Amount` are both ₹50 (A2/U1: may be the same charge counted twice). Per E12:
"Included once, flagged; both candidates disclosed; seller resolves." This module never
decides FOR the seller which of the two is real — it counts the ambiguous amount once and
surfaces both candidate codes so a human (or the CFO agent, narrating only) can resolve it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from calc_engine.formulas.component_sum import sum_components
from calc_engine.types import ZERO, CanonicalLine, ComponentRow, Paise

_FEE_KIND = "FEE"


def marketplace_fees(
    lines: Sequence[CanonicalLine],
    fee_component_codes: frozenset[str],
    duplicate_candidate_codes: frozenset[str] = frozenset(),
    side: str = "INVOICE",
) -> tuple[Paise, tuple[dict[str, object], ...]]:
    """Returns (MarketplaceFees total, V-FEE-002 flags).

    `duplicate_candidate_codes` names the codes known to sometimes double-represent the same
    charge (e.g. `{"PLATFORM_FEE", "MARKETPLACE_FEE_AMOUNT"}`); codes outside that set are
    summed normally via `sum_components`. This dedup path only compares components on the same
    `side` as the one requested here — a settlement-vs-invoice duplicate is a different concern
    (§5.12's leak-delta signal), not this rule.
    """
    non_candidate_codes = fee_component_codes - duplicate_candidate_codes
    total = sum_components(lines, component_codes=non_candidate_codes, component_kind=_FEE_KIND, side=side)

    flags: list[dict[str, object]] = []
    for line in lines:
        candidates = [
            c
            for c in line.components
            if c.component_code in duplicate_candidate_codes
            and c.component_kind == _FEE_KIND
            and c.source_side == side
        ]
        if not candidates:
            continue

        by_amount: dict[int, list[ComponentRow]] = defaultdict(list)
        for component in candidates:
            by_amount[component.amount.value].append(component)

        for amount_value, components in by_amount.items():
            if len(components) > 1:
                # suspected duplicate (equal amount, overlapping semantics) — counted once
                total = total + components[0].amount
                flags.append(
                    {
                        "rule": "V-FEE-002",
                        "sales_line_id": str(line.sales_line_id),
                        "component_codes": tuple(c.component_code for c in components),
                        "amount_paise": amount_value,
                        "note": "counted once; both candidates disclosed; seller resolves (E12)",
                    }
                )
            else:
                # distinct amounts among candidate codes -> evidently not the same charge
                total = total + components[0].amount

    return total, tuple(flags)
