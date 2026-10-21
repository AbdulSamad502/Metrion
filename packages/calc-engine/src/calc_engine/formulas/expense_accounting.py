"""EXPENSE_BY_CATEGORY and OPERATING_PROFIT — deterministic-engine.md §5.17.1 (2), (3); cfo-unified-financials.md §4.1, §4.2.

Storage-neutral: the input is `ExpenseLine`, which a dedicated ledger or a `manual_adjustment` extension can both produce (the
Phase 3 decision, `cfo-expense-model-options.md`). Pure integer arithmetic; no clock; nothing is rounded.

The accounting matrix (`PNL_TREATMENT`) is the single source of truth for how each expense class behaves, so inventory
purchases, owner drawings, capital items and tax assets can never reach a profit figure, and costs already inside Contribution
Profit (ads, packaging, logistics) are never subtracted a second time.

Classification is suggest-only: the effective class is the seller's *confirmed* class; a suggestion changes no figure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

from calc_engine.formulas.completeness import Completeness
from calc_engine.types import Unavailable


class ExpenseClass(str, Enum):
    ALLOCATED_COST = "ALLOCATED_COST"  # ads, packaging, logistics pools — already inside Contribution Profit
    OVERHEAD = "OVERHEAD"  # rent, salaries, software, professional fees — reduces operating profit
    OWNER_DRAWING = "OWNER_DRAWING"
    INVENTORY_PURCHASE = "INVENTORY_PURCHASE"  # COGS is recognised on units sold, never on purchases
    CAPITAL = "CAPITAL"
    TAX_ASSET = "TAX_ASSET"  # TCS / TDS
    OTHER_UNCLASSIFIED = "OTHER_UNCLASSIFIED"


class ExpenseHold(str, Enum):
    NONE = "NONE"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    MAY_OVERLAP_UNCONFIRMED = "MAY_OVERLAP_UNCONFIRMED"


class OverheadCoverage(str, Enum):
    SOURCE_PRESENT = "SOURCE_PRESENT"  # an expense source (ledger entries) covers the period
    DECLARED_NONE = "DECLARED_NONE"  # the seller explicitly declared "no overhead expenses" for the period
    NONE = "NONE"  # neither: the overhead is simply unknown


class OperatingProfitStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


@dataclass(frozen=True, slots=True)
class ExpenseLine:
    entry_id: str
    category: str
    amount_paise: int  # signed: a refund of an expense is negative and reduces its class
    entry_date: date
    paid_date: date | None = None
    confirmed_class: ExpenseClass | None = None
    suggested_class: ExpenseClass | None = None  # a hint only
    hold: ExpenseHold = ExpenseHold.NONE
    marketplace: str | None = None


@dataclass(frozen=True, slots=True)
class PnlTreatment:
    in_contribution_profit: bool  # already inside CP (so it must never be subtracted again)
    subtracted_in_operating_profit: bool
    cash_outflow: bool
    reduces_receipts: bool  # TCS/TDS reduce settlement receipts instead of being an outflow
    exposed_as_unclassified: bool


PNL_TREATMENT: dict[ExpenseClass, PnlTreatment] = {
    ExpenseClass.ALLOCATED_COST: PnlTreatment(True, False, True, False, False),
    ExpenseClass.OVERHEAD: PnlTreatment(False, True, True, False, False),
    ExpenseClass.OWNER_DRAWING: PnlTreatment(False, False, True, False, False),
    ExpenseClass.INVENTORY_PURCHASE: PnlTreatment(False, False, True, False, False),
    ExpenseClass.CAPITAL: PnlTreatment(False, False, True, False, False),
    ExpenseClass.TAX_ASSET: PnlTreatment(False, False, False, True, False),
    ExpenseClass.OTHER_UNCLASSIFIED: PnlTreatment(False, False, True, False, True),
}


def pnl_treatment(klass: ExpenseClass) -> PnlTreatment:
    return PNL_TREATMENT[klass]


def effective_class(line: ExpenseLine) -> ExpenseClass:
    """The seller's confirmed class, else OTHER_UNCLASSIFIED. A suggestion never counts (decision OQ2)."""
    return line.confirmed_class if line.confirmed_class is not None else ExpenseClass.OTHER_UNCLASSIFIED


@dataclass(frozen=True, slots=True)
class ExpenseGroup:
    category: str
    klass: ExpenseClass
    total_paise: int
    line_count: int


@dataclass(frozen=True, slots=True)
class ExcludedExpenses:
    hold: ExpenseHold
    total_paise: int
    line_count: int


@dataclass(frozen=True, slots=True)
class ExpenseBreakdown:
    groups: tuple[ExpenseGroup, ...]  # held lines are not in any group
    excluded: tuple[ExcludedExpenses, ...]  # held duplicates / unconfirmed overlap, counted and totalled

    @property
    def grouped_total_paise(self) -> int:
        return sum(g.total_paise for g in self.groups)

    @property
    def excluded_total_paise(self) -> int:
        return sum(e.total_paise for e in self.excluded)


def _in_period(line: ExpenseLine, start: date | None, end: date | None) -> bool:
    return (start is None or line.entry_date >= start) and (end is None or line.entry_date <= end)


def expense_breakdown(lines: Sequence[ExpenseLine], *, period_start: date | None = None, period_end: date | None = None) -> ExpenseBreakdown:
    """Totals by (category, effective class), with held lines separated. A partition: Σ groups + Σ excluded = Σ all in-scope lines."""
    totals: dict[tuple[str, ExpenseClass], list[int]] = {}
    held: dict[ExpenseHold, list[int]] = {}
    for line in lines:
        if not _in_period(line, period_start, period_end):
            continue
        if line.hold is not ExpenseHold.NONE:
            h = held.setdefault(line.hold, [0, 0])
            h[0] += line.amount_paise
            h[1] += 1
            continue
        g = totals.setdefault((line.category, effective_class(line)), [0, 0])
        g[0] += line.amount_paise
        g[1] += 1
    groups = tuple(ExpenseGroup(c, k, v[0], v[1]) for (c, k), v in sorted(totals.items(), key=lambda kv: (kv[0][0], kv[0][1].value)))
    excluded = tuple(ExcludedExpenses(h, v[0], v[1]) for h, v in sorted(held.items(), key=lambda kv: kv[0].value))
    return ExpenseBreakdown(groups=groups, excluded=excluded)


@dataclass(frozen=True, slots=True)
class ExpenseExposure:
    """A set of expense lines surfaced beside a figure so the seller sees exactly what makes it provisional."""

    total_paise: int
    line_count: int
    entry_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperatingProfit:
    value_paise: int
    contribution_profit_paise: int
    overhead_total_paise: int
    status: OperatingProfitStatus
    completeness: Completeness
    unclassified: ExpenseExposure  # no confirmed class: excluded from both profit figures and listed
    held: ExpenseExposure  # possible duplicates / unconfirmed overlap: excluded and listed
    non_pnl_totals: tuple[tuple[ExpenseClass, int, int], ...]  # (class, total, count) of owner drawings, purchases, capital, tax assets — informational
    allocated_cost_total_paise: int  # already inside Contribution Profit — informational, never subtracted again


def operating_profit(
    contribution_profit_paise: int | None,
    lines: Sequence[ExpenseLine],
    overhead_coverage: OverheadCoverage,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> OperatingProfit | Unavailable:
    """`OPERATING_PROFIT = CP − Σ overhead` with a PROVISIONAL / FINAL status and the unclassified and held lines exposed.

    UNAVAILABLE when Contribution Profit is, or when no overhead source and no "no overheads" declaration exists (a missing input is
    not zero: without this the figure would be Contribution Profit under another name). There is no materiality threshold (decision OQ1)."""
    if contribution_profit_paise is None:
        return Unavailable(reason="Contribution Profit is unavailable", missing_inputs=("CONTRIBUTION_PROFIT",))
    in_scope = [ln for ln in lines if _in_period(ln, period_start, period_end)]
    if overhead_coverage is OverheadCoverage.NONE:
        reason = ("no overhead expense data or declaration for the period" if not in_scope
                  else "expense entries exist but the overhead coverage for the period was not established")
        return Unavailable(reason=reason, missing_inputs=("expense_overhead_coverage",))
    if overhead_coverage is OverheadCoverage.DECLARED_NONE and any(effective_class(ln) is ExpenseClass.OVERHEAD for ln in in_scope):
        return Unavailable(reason="the seller declared no overhead expenses but overhead entries exist for the period; the declaration must be superseded",
                           missing_inputs=("expense_overhead_declaration",))

    overhead = 0
    unclassified: list[ExpenseLine] = []
    held: list[ExpenseLine] = []
    non_pnl: dict[ExpenseClass, list[int]] = {}
    allocated = 0
    for ln in in_scope:
        if ln.hold is not ExpenseHold.NONE:
            held.append(ln)
            continue
        klass = effective_class(ln)
        if klass is ExpenseClass.OVERHEAD:
            overhead += ln.amount_paise
        elif klass is ExpenseClass.OTHER_UNCLASSIFIED:
            unclassified.append(ln)
        elif klass is ExpenseClass.ALLOCATED_COST:
            allocated += ln.amount_paise
        else:
            t = non_pnl.setdefault(klass, [0, 0])
            t[0] += ln.amount_paise
            t[1] += 1

    def exposure(xs: list[ExpenseLine]) -> ExpenseExposure:
        return ExpenseExposure(sum(x.amount_paise for x in xs), len(xs), tuple(sorted(x.entry_id for x in xs)))

    final = not unclassified and not held
    return OperatingProfit(
        value_paise=contribution_profit_paise - overhead,
        contribution_profit_paise=contribution_profit_paise,
        overhead_total_paise=overhead,
        status=OperatingProfitStatus.FINAL if final else OperatingProfitStatus.PROVISIONAL,
        completeness=Completeness.COMPLETE if final else Completeness.PROVISIONAL,
        unclassified=exposure(unclassified),
        held=exposure(held),
        non_pnl_totals=tuple((k, v[0], v[1]) for k, v in sorted(non_pnl.items(), key=lambda kv: kv[0].value)),
        allocated_cost_total_paise=allocated,
    )
