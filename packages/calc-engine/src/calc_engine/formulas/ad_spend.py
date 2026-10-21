"""AD_SPEND_STATUS and ROAS / ACOS / TACOS — deterministic-engine.md §5.17.1 (5), (6); cfo-unified-financials.md §4.1c.

The legacy engine rule is untouched: a scope with no advertising entry resolves to ₹0 inside Contribution Profit (Category E). What
this module adds is the **status of what is known**, so new intelligence outputs never present an unknown or uncovered amount as a
verified zero:

    VERIFIED_ZERO     a covering source (or the seller's explicit "no advertising" declaration) reports no spend
    KNOWN_SPEND       a source covers the whole period and reports spend above zero
    MISSING_COVERAGE  a source exists for the marketplace but does not cover the whole period
    UNKNOWN           no source and no declaration at all

Status is derived only from declared coverage intervals — never from the mere absence of rows. Ratios are exact `Fraction`s and are
`None` (unavailable, with a reason) wherever their inputs or denominators are not known.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from fractions import Fraction

from calc_engine.formulas.completeness import Completeness


class AdSpendStatus(str, Enum):
    VERIFIED_ZERO = "VERIFIED_ZERO"
    KNOWN_SPEND = "KNOWN_SPEND"
    MISSING_COVERAGE = "MISSING_COVERAGE"
    UNKNOWN = "UNKNOWN"


class AdCoverageSource(str, Enum):
    REPORT = "REPORT"  # an ingested advertising report with a declared period
    DECLARATION_NO_ADS = "DECLARATION_NO_ADS"  # the seller explicitly declared no advertising
    MANUAL_POOL = "MANUAL_POOL"  # a seller-entered advertising pool for a period


@dataclass(frozen=True, slots=True)
class AdCoverage:
    marketplace: str
    start: date
    end: date
    source: AdCoverageSource

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("coverage end precedes start")


def _fully_covered(intervals: list[tuple[date, date]], start: date, end: date) -> bool:
    cursor = start
    for s, e in sorted(intervals):
        if e < cursor:
            continue
        if s > cursor:
            return False  # a gap before this interval
        cursor = e + timedelta(days=1)
        if cursor > end:
            return True
    return cursor > end


def ad_spend_status(
    *, marketplace: str, period_start: date, period_end: date, coverage: Sequence[AdCoverage], spend_paise: int | None
) -> AdSpendStatus:
    """`spend_paise` is the known spend inside the period from the covering sources (None when no amount is known)."""
    if period_end < period_start:
        raise ValueError("period_end precedes period_start")
    mine = [c for c in coverage if c.marketplace == marketplace]
    if not mine:
        return AdSpendStatus.UNKNOWN
    if not _fully_covered([(c.start, c.end) for c in mine], period_start, period_end):
        return AdSpendStatus.MISSING_COVERAGE
    if spend_paise is None:
        # Covered, but only a declaration can stand for "no amount": a report or pool with no known amount is not a verified zero.
        declared = [(c.start, c.end) for c in mine if c.source is AdCoverageSource.DECLARATION_NO_ADS]
        return AdSpendStatus.VERIFIED_ZERO if _fully_covered(declared, period_start, period_end) else AdSpendStatus.MISSING_COVERAGE
    if spend_paise < 0:
        raise ValueError("advertising spend cannot be negative")
    return AdSpendStatus.KNOWN_SPEND if spend_paise > 0 else AdSpendStatus.VERIFIED_ZERO


@dataclass(frozen=True, slots=True)
class AdRatios:
    status: AdSpendStatus
    roas: Fraction | None  # attributed sales / spend
    acos: Fraction | None  # spend / attributed sales
    tacos: Fraction | None  # spend / total sales
    unavailable: dict[str, str]
    completeness: Completeness


def ad_ratios(*, status: AdSpendStatus, spend_paise: int | None, attributed_sales_paise: int | None, total_sales_paise: int | None) -> AdRatios:
    names = ("roas", "acos", "tacos")
    if status in (AdSpendStatus.MISSING_COVERAGE, AdSpendStatus.UNKNOWN) or spend_paise is None:
        why = {AdSpendStatus.MISSING_COVERAGE: "advertising spend is not covered for the whole period",
               AdSpendStatus.UNKNOWN: "advertising spend is unknown (no report and no declaration)"}.get(status, "advertising spend is not known")
        return AdRatios(status, None, None, None, {n: why for n in names}, Completeness.UNAVAILABLE)
    if spend_paise < 0:
        raise ValueError("advertising spend cannot be negative")
    if status is AdSpendStatus.VERIFIED_ZERO and spend_paise != 0:
        raise ValueError("VERIFIED_ZERO requires zero spend")
    if status is AdSpendStatus.KNOWN_SPEND and spend_paise == 0:
        raise ValueError("KNOWN_SPEND requires spend above zero")

    unavailable: dict[str, str] = {}
    roas = acos = tacos = None
    if attributed_sales_paise is None:
        unavailable["roas"] = unavailable["acos"] = "the advertising report carries no attributed sales"
    else:
        if spend_paise > 0:
            roas = Fraction(attributed_sales_paise, spend_paise)
        else:
            unavailable["roas"] = "no advertising spend, so ROAS is undefined"
        if attributed_sales_paise > 0:
            acos = Fraction(spend_paise, attributed_sales_paise)
        else:
            unavailable["acos"] = "no attributed sales, so ACOS is undefined"
    if total_sales_paise is not None and total_sales_paise > 0:
        tacos = Fraction(spend_paise, total_sales_paise)
    else:
        unavailable["tacos"] = "total sales are missing or zero"
    got = sum(x is not None for x in (roas, acos, tacos))
    completeness = Completeness.COMPLETE if got == 3 else Completeness.PARTIAL if got else Completeness.UNAVAILABLE
    return AdRatios(status, roas, acos, tacos, unavailable, completeness)
