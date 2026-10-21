"""SETTLEMENT_RECEIPTS — deterministic-engine.md §5.17.1 (4).

Σ settlement-side net amount whose **settlement date** falls in the period (receipts are not revenue and not profit; the gap is
timing, returns, fees and levies). Missing is never zero:
  * no settlement lines at all, or none dated in the period, or none carrying a settled amount -> `Unavailable`;
  * a line with no date cannot be assigned to a period, a line with no amount cannot be summed, a held duplicate is not posted:
    each is excluded and counted, and the result is `PARTIAL`.
Marketplace behaviour: Amazon's V2 adapter deliberately never fills the settled amount (a later aggregation stage owns it), so Amazon
lines arrive amount-less and Amazon receipts are `Unavailable` until that stage exists; Meesho and Flipkart carry the amount.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from calc_engine.formulas.completeness import Completeness
from calc_engine.types import Unavailable


@dataclass(frozen=True, slots=True)
class SettlementLineInput:
    line_id: str
    marketplace: str
    settlement_date: date | None
    amount_paise: int | None
    held: bool = False  # a held duplicate/conflict row: not posted, so never summed


@dataclass(frozen=True, slots=True)
class SettlementReceipts:
    value_paise: int
    line_count: int
    excluded_undated: int
    excluded_no_amount: int
    excluded_held: int
    completeness: Completeness


def settlement_receipts(lines: Sequence[SettlementLineInput], period_start: date, period_end: date) -> SettlementReceipts | Unavailable:
    if period_end < period_start:
        raise ValueError("period_end precedes period_start")
    if not lines:
        return Unavailable(reason="no settlement data", missing_inputs=("settlement_lines",))
    total = count = undated = no_amount = held = in_period_seen = 0
    for ln in lines:
        if ln.held:
            held += 1
            continue
        if ln.settlement_date is None:
            undated += 1
            continue
        if not (period_start <= ln.settlement_date <= period_end):
            continue
        in_period_seen += 1
        if ln.amount_paise is None:
            no_amount += 1
            continue
        total += ln.amount_paise
        count += 1
    if count == 0:
        if no_amount or undated:
            return Unavailable(reason="settlement lines exist but none carries a settled amount and a settlement date in this period",
                               missing_inputs=("settled_amount", "settlement_date"))
        return Unavailable(reason="no settlement lines are dated in this period", missing_inputs=("settlement_lines_in_period",))
    excluded = undated + no_amount + held
    return SettlementReceipts(total, count, undated, no_amount, held, Completeness.PARTIAL if excluded else Completeness.COMPLETE)


@dataclass(frozen=True, slots=True)
class ConsolidatedReceipts:
    value_paise: int | None  # Σ of the marketplaces that are available; None when none is
    per_marketplace: Mapping[str, SettlementReceipts]
    unavailable: Mapping[str, str]  # marketplace -> reason
    completeness: Completeness


def settlement_receipts_by_marketplace(lines: Sequence[SettlementLineInput], period_start: date, period_end: date) -> ConsolidatedReceipts:
    """Per-marketplace results and their consolidation. An unavailable marketplace is *named* and makes the consolidated figure
    PARTIAL; it is never silently summed as zero. Σ available marketplaces equals the consolidated value exactly."""
    groups: dict[str, list[SettlementLineInput]] = {}
    for ln in lines:
        groups.setdefault(ln.marketplace, []).append(ln)
    per: dict[str, SettlementReceipts] = {}
    unavailable: dict[str, str] = {}
    for mp, group in sorted(groups.items()):
        r = settlement_receipts(group, period_start, period_end)
        if isinstance(r, Unavailable):
            unavailable[mp] = r.reason
        else:
            per[mp] = r
    if not per:
        return ConsolidatedReceipts(None, per, unavailable, Completeness.UNAVAILABLE)
    total = sum(r.value_paise for r in per.values())
    partial = bool(unavailable) or any(r.completeness is not Completeness.COMPLETE for r in per.values())
    return ConsolidatedReceipts(total, per, unavailable, Completeness.PARTIAL if partial else Completeness.COMPLETE)
