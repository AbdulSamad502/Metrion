"""ReconciliationOutcome -> LeakCategory — cfo-agent.md §6.3, §6.4 rule 1 ("Classification is
CFO's; amounts are the engine's").

**PROVISIONAL — Q12 (cfo-agent.md §12).** `data-foundation.md` §5.2's reconciliation outcomes
(`ORPHAN_SETTLEMENT`, `DUPLICATE_SETTLEMENT`, `UNSETTLED_BEYOND_LAG`, ...) have **no stated
mapping** to §6.3's seven leak categories anywhere in the spec — this module is the mechanism
that mapping needs, built ahead of the product decision so the plumbing exists, but the table
below is this author's best-effort reading, not a confirmed decision. Do not treat it as
settled; it must be revisited once Q12 is actually answered.

This module performs no arithmetic and touches no `Paise` value — it only classifies. The
`ReconciliationOutcome` enum and its underlying variance math are `calc_engine.formulas.leak`'s
(real, unchanged); this file adds nothing to that arithmetic, only a category label on top of
an outcome the engine already computed.

**`AMBIGUOUS_MATCH` (Collision) is handled entirely outside this module (D5, Decision B).** It
is not a `ReconciliationOutcome` value at all — `classify_leak_category`'s `ctx.outcome`
parameter cannot even represent it — so an `AMBIGUOUS_MATCH` exception is filtered out one
layer up, at the composition layer (`backend.services.cfo_actions.
run_leak_shield_reconciliation`), before a `LeakExceptionInput`/`ExceptionContext` is ever
built for it. This module never sees an `AMBIGUOUS_MATCH` row and never needs to.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from calc_engine.formulas.leak import ReconciliationOutcome


class LeakCategory(str, Enum):
    """cfo-agent.md §6.3 — the seven categories, verbatim."""

    FEE_OVERCHARGE = "FEE_OVERCHARGE"
    SHORT_SETTLEMENT = "SHORT_SETTLEMENT"
    MISSING_SETTLEMENT = "MISSING_SETTLEMENT"
    UNEXPECTED_DEDUCTION = "UNEXPECTED_DEDUCTION"
    RETURN_NOT_CREDITED = "RETURN_NOT_CREDITED"
    TCS_TDS_MISMATCH = "TCS_TDS_MISMATCH"
    DUPLICATE_DEDUCTION = "DUPLICATE_DEDUCTION"


@dataclass(frozen=True, slots=True)
class ExceptionContext:
    """The minimal extra context category assignment needs beyond what
    `calc_engine.formulas.severity.Finding` carries for ranking — a reconciliation_exception's
    `outcome` alone is not enough to pick a §6.3 category (e.g. `VARIANCE_EXCEEDS_TOLERANCE`
    could be a fee overcharge or a short settlement depending on which side of revenue/fee the
    variance sits on and its sign). Field names are chosen to mirror the likely shape of a
    future real `reconciliation_exception` row (`data-foundation.md` §5) without asserting
    that table's final schema — this dataclass is exercised only against synthetic fixtures in
    this checkpoint (no real `reconcile()` exists yet, see `formulas/leak.py`'s docstring).
    """

    outcome: ReconciliationOutcome
    component_kind: str | None = None  # FEE | CHARGE | TAX | LEVY | DISCOUNT | None
    variance_is_settlement_higher: bool | None = None  # settlement > invoice; None if N/A
    is_return_linked: bool = False
    is_levy_component: bool = False  # TCS/TDS-bearing component (component_kind == "LEVY")


def classify_leak_category(ctx: ExceptionContext) -> LeakCategory | None:
    """Returns `None` for an outcome that is not a reportable leak at all
    (`MATCHED_EXACT`/`MATCHED_WITHIN_TOLERANCE`/`UNSETTLED_WITHIN_LAG`) — the caller must not
    build a `Finding` for those. PROVISIONAL mapping (Q12, see module docstring):

    | outcome                        | extra context                         | category               |
    |---------------------------------|----------------------------------------|-------------------------|
    | VARIANCE_EXCEEDS_TOLERANCE      | return-linked                          | RETURN_NOT_CREDITED     |
    | VARIANCE_EXCEEDS_TOLERANCE      | is_levy_component                      | TCS_TDS_MISMATCH        |
    | VARIANCE_EXCEEDS_TOLERANCE      | component_kind == FEE, settlement higher | FEE_OVERCHARGE        |
    | VARIANCE_EXCEEDS_TOLERANCE      | settlement lower (revenue/other)       | SHORT_SETTLEMENT        |
    | UNSETTLED_BEYOND_LAG             | —                                       | MISSING_SETTLEMENT      |
    | ORPHAN_SETTLEMENT                | —                                       | UNEXPECTED_DEDUCTION    |
    | DUPLICATE_SETTLEMENT             | —                                       | DUPLICATE_DEDUCTION     |
    | MATCHED_EXACT / MATCHED_WITHIN_TOLERANCE / UNSETTLED_WITHIN_LAG | — | None (not a leak) |
    """
    if ctx.outcome in (
        ReconciliationOutcome.MATCHED_EXACT,
        ReconciliationOutcome.MATCHED_WITHIN_TOLERANCE,
        ReconciliationOutcome.UNSETTLED_WITHIN_LAG,
    ):
        return None

    if ctx.outcome == ReconciliationOutcome.UNSETTLED_BEYOND_LAG:
        return LeakCategory.MISSING_SETTLEMENT

    if ctx.outcome == ReconciliationOutcome.ORPHAN_SETTLEMENT:
        return LeakCategory.UNEXPECTED_DEDUCTION

    if ctx.outcome == ReconciliationOutcome.DUPLICATE_SETTLEMENT:
        return LeakCategory.DUPLICATE_DEDUCTION

    if ctx.outcome == ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE:
        if ctx.is_return_linked:
            return LeakCategory.RETURN_NOT_CREDITED
        if ctx.is_levy_component:
            return LeakCategory.TCS_TDS_MISMATCH
        if ctx.component_kind == "FEE" and ctx.variance_is_settlement_higher is True:
            return LeakCategory.FEE_OVERCHARGE
        return LeakCategory.SHORT_SETTLEMENT

    raise ValueError(f"unknown ReconciliationOutcome {ctx.outcome!r}")
