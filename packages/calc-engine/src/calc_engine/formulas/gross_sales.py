"""GROSS_SALES — deterministic-engine.md §5.17.1 (1).

The sum of `gross_order_value` over every order line in scope, **including cancelled and returned lines**: a volume measure,
tax-exclusive (§8.1). It is deliberately available where Net Realized Revenue is not: Amazon and Flipkart reports carry no
cancellation/RTO status, so NRR is `UNAVAILABLE` there while gross sales is a measured volume.

Lines that could not be assembled upstream (no quantity or gross amount) are not in `lines`; the caller passes how many were
blocked so the result is `PARTIAL` rather than silently complete.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from calc_engine.formulas.completeness import Completeness
from calc_engine.formulas.gross_order_value import gross_order_value
from calc_engine.types import CanonicalLine, Paise, Unavailable


@dataclass(frozen=True, slots=True)
class GrossSales:
    value: Paise
    line_count: int
    blocked_line_count: int  # lines excluded upstream (counted, never silently dropped)
    completeness: Completeness


def gross_sales(lines: Sequence[CanonicalLine], *, blocked_line_count: int = 0) -> GrossSales | Unavailable:
    if blocked_line_count < 0:
        raise ValueError("blocked_line_count cannot be negative")
    if not lines:
        return Unavailable(reason="no order lines in scope", missing_inputs=("sales_lines",))
    return GrossSales(
        value=gross_order_value(lines), line_count=len(lines), blocked_line_count=blocked_line_count,
        completeness=Completeness.PARTIAL if blocked_line_count else Completeness.COMPLETE,
    )


@dataclass(frozen=True, slots=True)
class ConsolidatedGrossSales:
    consolidated: GrossSales | Unavailable
    by_marketplace: Mapping[str, GrossSales | Unavailable]


def gross_sales_by_marketplace(
    lines: Sequence[CanonicalLine], *, blocked_by_marketplace: Mapping[str, int] | None = None
) -> ConsolidatedGrossSales:
    """Per-marketplace results, each computed on its own lines, and the consolidated result computed on all lines. Because every
    marketplace is summed from the same integers, Σ marketplaces equals the consolidated figure exactly (checked by the tests)."""
    blocked = dict(blocked_by_marketplace or {})
    groups: dict[str, list[CanonicalLine]] = {}
    for line in lines:
        groups.setdefault(line.marketplace, []).append(line)
    by_mp = {mp: gross_sales(group, blocked_line_count=blocked.get(mp, 0)) for mp, group in sorted(groups.items())}
    return ConsolidatedGrossSales(consolidated=gross_sales(lines, blocked_line_count=sum(blocked.values())), by_marketplace=by_mp)
