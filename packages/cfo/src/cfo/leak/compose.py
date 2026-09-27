"""`classify_and_rank_leaks` — cfo-agent.md §6.4: builds `Finding` tuples from reconciliation
exceptions and calls the REAL `rank_findings` (`calc_engine.formulas.severity`) unchanged.

**Now wired (D5).** `reconcile()` (`calc_engine.api.reconcile`, D4) is real, and this module is
now called from `backend.services.cfo_actions.run_leak_shield_reconciliation`, reachable via
`POST /cfo/reconcile` and the `cfo.reconcile` CEO Hub dispatch action
(`backend.agents.ceo_hub.dispatch_cfo_reconcile`) — guardrail 4 (`twinkly-mapping-canyon.md`
CP2: "no seller-facing Leak Shield findings until a real `reconcile()` exists") is closed as
of D5. This module itself still performs no persistence — it does not import
`leak_finding_repo` and never calls it; `run_leak_shield_reconciliation` is the caller that
persists each `ComposedFinding` via `leak_finding_repo.insert`, field-for-field, after this
module returns.

No arithmetic on `Paise`/`amount_paise` happens here: `Finding.amount_paise` is an `int`
**copied unchanged** from the exception input (§6.4 rule 1 — "amounts are the engine's"), and
severity/ordering are `rank_findings`'s arithmetic, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from calc_engine.formulas.leak import ReconciliationOutcome
from calc_engine.formulas.severity import (
    Finding,
    SeverityBand,
    SeverityConfigRow,
    WindowStatus,
    rank_findings,
)
from calc_engine.types import Unavailable

from cfo.leak.classification import ExceptionContext, LeakCategory, classify_leak_category


@dataclass(frozen=True, slots=True)
class LeakExceptionInput:
    """One reconciliation_exception, as this module needs it. `amount_paise` and
    `engine_result_ref` both originate from the engine/exception row — this dataclass only
    carries them through, it never computes either. As of D5, real instances are built by
    `backend.services.cfo_actions.run_leak_shield_reconciliation` from real, persisted
    `reconciliation_exception` rows (see module docstring); this package's own tests still also
    exercise it against synthetic fixtures."""

    exception_id: str
    engine_result_ref: str
    marketplace: str
    outcome: ReconciliationOutcome
    amount_paise: int
    affected_line_count: int
    first_observed_at: datetime
    age_days: int
    claim_window_days: int | None
    sku: str | None = None
    component_kind: str | None = None
    variance_is_settlement_higher: bool | None = None
    is_return_linked: bool = False
    is_levy_component: bool = False


@dataclass(frozen=True, slots=True)
class ComposedFinding:
    """One ranked, categorized finding — the exact shape a caller would hand to
    `leak_finding_repo.insert` (field-for-field), without this module calling that repository
    itself. `severity`/`window_status` come straight from `rank_findings`'s return value;
    `leak_category` from the PROVISIONAL classification table (Q12)."""

    exception: LeakExceptionInput
    leak_category: LeakCategory
    severity: SeverityBand | Unavailable
    window_status: WindowStatus


def classify_and_rank_leaks(
    exceptions: list[LeakExceptionInput],
    *,
    as_of_date: date,
    config_rows: list[SeverityConfigRow],
    ordering_basis: str = "WINDOW_THEN_AMOUNT",
    closing_soon_days: int = 14,
) -> list[ComposedFinding]:
    """Classifies each exception (skipping non-leak outcomes per `classify_leak_category`),
    builds the `Finding` tuple `rank_findings` needs, and returns the real engine ordering
    with each finding's category attached. `rank_findings` (real, unchanged,
    `calc_engine.formulas.severity`) does all the ordering/severity/window-status arithmetic;
    this function does none of it."""
    categorized: dict[str, tuple[LeakExceptionInput, LeakCategory]] = {}
    findings: list[Finding] = []

    for exc in exceptions:
        category = classify_leak_category(
            ExceptionContext(
                outcome=exc.outcome,
                component_kind=exc.component_kind,
                variance_is_settlement_higher=exc.variance_is_settlement_higher,
                is_return_linked=exc.is_return_linked,
                is_levy_component=exc.is_levy_component,
            )
        )
        if category is None:
            continue  # not a reportable leak (§6.2/§6.4) — matched or still within lag
        categorized[exc.exception_id] = (exc, category)
        findings.append(
            Finding(
                exception_id=exc.exception_id,
                amount_paise=exc.amount_paise,  # copied, never recomputed (§6.4 rule 1)
                age_days=exc.age_days,
                claim_window_days=exc.claim_window_days,
            )
        )

    ranked = rank_findings(
        findings,
        as_of_date=as_of_date,
        config_rows=config_rows,
        ordering_basis=ordering_basis,
        closing_soon_days=closing_soon_days,
    )

    composed: list[ComposedFinding] = []
    for finding, severity, window_status in ranked:
        exc, category = categorized[finding.exception_id]
        composed.append(
            ComposedFinding(
                exception=exc,
                leak_category=category,
                severity=severity,
                window_status=window_status,
            )
        )
    return composed
