"""Cost-ownership arbitration (cost-ownership matrix, V-DUP-2; docs/specs/cfo-expense-ledger.md D5 / AC-L8, cfo-phase3-scope.md AD4).

A seller's allocated costs (advertising, packaging, storage, logistics, other) can be recorded in three places: the Expense Tracker's pool (legacy), the expense
ledger (an entry confirmed as ALLOCATED_COST with a named component) and — for advertising only — an uploaded report. **For a component, a marketplace and a
period exactly one source counts**, or the cost would reach Contribution Profit twice. When two or more sources are present the seller's recorded choice
(`cost_owner_choice`) says which; without a choice the situation is a **conflict**: the established source (the legacy pool, then a report, then the ledger) keeps
counting so existing figures do not silently change, the other sources are excluded, and the conflict is returned so the figure can be labelled and the seller asked.

`resolve` is pure (no I/O, no clock, no arithmetic): it only decides which items count. The amounts are summed by the engine downstream.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from calc_engine.formulas.expense_accounting import ExpenseClass, ExpenseHold
from calc_engine.repositories import ad_report_repo, cost_owner_repo, expense_ledger_repo, manual_adjustment_repo

from backend.services import cfo_actions

COMPONENTS = cost_owner_repo.COMPONENTS
_FALLBACK = ("POOL", "REPORT", "LEDGER")  # the established source keeps counting when the seller has not chosen


@dataclass(frozen=True, slots=True)
class Item:
    component: str
    marketplace: str | None  # None = recorded for the whole account
    value: Mapping[str, object]  # pool-shaped: at least {"amount_paise": int}
    source: str  # POOL | LEDGER | REPORT
    span: tuple[date, date] | None = None  # the period this record covers (a pool's label period; the calendar month of a ledger entry; a report's dates are in its coverage)


@dataclass(frozen=True, slots=True)
class Conflict:
    component: str
    marketplace: str  # a marketplace or "ALL"
    sources: tuple[str, ...]
    counted: str  # the source that keeps counting until the seller chooses


@dataclass(frozen=True, slots=True)
class Sources:
    pools: Sequence[Item] = ()
    ledger: Sequence[Item] = ()
    reports: Sequence[Item] = ()


@dataclass
class Resolved:
    advertising: list[Mapping[str, object]] = field(default_factory=list)
    other: list[Mapping[str, object]] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    counted: list[Item] = field(default_factory=list)

    def values_for(self, component: str) -> list[Mapping[str, object]]:
        return self.advertising if component == "ADVERTISING" else self.other


Chooser = Callable[[str, str], str | None]  # (component, marketplace-or-"ALL") -> POOL | LEDGER | REPORT | None


def _pick(component: str, key: str, present: dict[str, list[Item]], choose: Chooser) -> tuple[str, Conflict | None]:
    if len(present) == 1:
        return next(iter(present)), None
    owner = choose(component, key)
    if owner in present:
        return owner, None
    counted = next(s for s in _FALLBACK if s in present)
    return counted, Conflict(component, key, tuple(sorted(present)), counted)


def resolve(sources: Sources, scope_marketplaces: Sequence[str], choose: Chooser) -> Resolved:
    """Which items count. For each component: per-marketplace groups, then the account-level group, then — for advertising — account-level hand-entered
    costs against any report in scope. Nothing is summed here."""
    out = Resolved()
    mps = list(scope_marketplaces)

    def add(item: Item) -> None:
        out.counted.append(item)
        out.values_for(item.component).append(item.value)

    for comp in COMPONENTS:
        pools = [i for i in sources.pools if i.component == comp]
        ledger = [i for i in sources.ledger if i.component == comp]
        reports = [i for i in sources.reports if i.component == comp]
        dropped_reports = False
        # per marketplace
        for mp in mps:
            groups = {"POOL": [i for i in pools if i.marketplace == mp], "LEDGER": [i for i in ledger if i.marketplace == mp], "REPORT": [i for i in reports if i.marketplace == mp]}
            present = {k: v for k, v in groups.items() if v}
            if not present:
                continue
            winner, conflict = _pick(comp, mp, present, choose)
            if conflict:
                out.conflicts.append(conflict)
            for item in present[winner]:
                add(item)
        # account level (recorded without a marketplace)
        acct = {"POOL": [i for i in pools if i.marketplace is None], "LEDGER": [i for i in ledger if i.marketplace is None]}
        acct_present = {k: v for k, v in acct.items() if v}
        in_scope_reports = [i for i in reports if i.marketplace in mps]
        if acct_present:
            candidates = dict(acct_present)
            if in_scope_reports:
                candidates["REPORT"] = in_scope_reports  # an account-wide cost entered by hand may be the same money a report shows per marketplace
            winner, conflict = _pick(comp, "ALL", candidates, choose)
            if conflict:
                out.conflicts.append(conflict)
            if winner == "REPORT":
                pass  # the reports were already counted in their marketplace groups; the account-level entries are excluded
            else:
                for item in acct_present[winner]:
                    add(item)
                dropped_reports = bool(in_scope_reports)
        if dropped_reports:  # the seller (or the fallback) chose the hand-entered account-wide cost over the reports: the reports must not also count
            keep = [i for i in out.counted if not (i.component == comp and i.source == "REPORT")]
            drop = [i for i in out.counted if i.component == comp and i.source == "REPORT"]
            out.counted = keep
            values = out.values_for(comp)
            for item in drop:
                values.pop(next(n for n, v in enumerate(values) if v is item.value))  # by identity: an equal-looking hand-entered figure must stay
    return out


# ------------------------------------------------------------------------------------------------ loading
def month_bounds(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    nxt = first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)
    return first, date.fromordinal(nxt.toordinal() - 1)


def _norm_mp(v: object) -> str | None:
    return str(v).strip().upper() or None if v else None


def load_sources(tenant_id: UUID, scope_marketplaces: Sequence[str], start: date, end: date) -> Sources:
    pools: list[Item] = []
    for row in manual_adjustment_repo.active_adjustments_by_field(tenant_id, field_prefix="expense."):
        comp = row["field"].removeprefix("expense.").upper()
        if comp not in COMPONENTS:
            continue  # expense.budget and anything else are not cost pools
        span = cfo_actions._expense_period_label_range(row["target_type"], row["target_ref"])
        if span is None or span[1] < start or span[0] > end:
            continue
        v = dict(row["value"])
        pools.append(Item(comp, _norm_mp(v.get("marketplace")), v, "POOL", span))
    ledger: list[Item] = []
    for ln in expense_ledger_repo.lines_for_period(tenant_id, start, end):
        if ln.confirmed_class is ExpenseClass.ALLOCATED_COST and ln.hold is ExpenseHold.NONE and ln.allocated_component:
            first, last = month_bounds(ln.entry_date)
            ledger.append(Item(ln.allocated_component, ln.marketplace, {"amount_paise": ln.amount_paise, "marketplace": ln.marketplace}, "LEDGER", (first, last)))
    reports: list[Item] = []
    for mp in scope_marketplaces:
        s = ad_report_repo.spend_in_period(tenant_id, mp, start, end)
        if s is not None:
            reports.append(Item("ADVERTISING", mp, {"amount_paise": s.spend_paise, "marketplace": mp}, "REPORT"))
    return Sources(pools, ledger, reports)


def chooser(tenant_id: UUID, start: date, end: date) -> Chooser:
    def choose(component: str, marketplace: str) -> str | None:
        return cost_owner_repo.owner_for(tenant_id, component, marketplace, start, end)

    return choose


def resolve_for(tenant_id: UUID, scope_marketplaces: Sequence[str], start: date, end: date) -> Resolved:
    return resolve(load_sources(tenant_id, scope_marketplaces, start, end), scope_marketplaces, chooser(tenant_id, start, end))
