"""`compose_strategic_signals` — cfo-agent.md §7.5 (Strategic Insight layer).

Mirrors `cfo.leak.compose.classify_and_rank_leaks`'s own established shape exactly: a pure
function, no database access, no LLM call, no arithmetic on money — it takes ALREADY-COMPUTED
outcomes (Financial Health bands, anomaly flags, persisted leak findings, expense-budget status,
open data requests) and turns them into one deterministically ranked list of `StrategicSignal`s.

**Why this exists, and what it deliberately does not do.** The user's own explicit brief:
"Functions calculate. The LLM reasons. The CFO recommends." This module is the "functions
calculate/decide" half for the Strategic Insight layer — it decides WHICH category a signal is,
HOW SEVERE it is, and WHAT closed action type it maps to, all via plain lookup tables over
values every one of those inputs already computed. `backend.services.cfo_actions.
assemble_strategic_briefing` is the only caller: it fetches the real data, builds these inputs,
calls this module, then hands the resulting ranked signals to Brain 3 (`cfo.reasoning.narrate`)
for ONE narration call — the LLM never sees raw figures this module didn't already classify,
and it never reorders or reclassifies what this module decided.

`severity_rank` is deterministic and closed (0..3) — the same "ranking is not judgement, it is
computed deterministically" principle `calc_engine.formulas.severity` already established for
Leak Shield findings, applied here across a wider set of signal sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Sequence
from uuid import UUID

# --- Severity ranks, and the closed action-type vocabulary a signal's category maps to --------
# Both tables are deliberately small, explicit dicts — never inferred, never left to the LLM to
# invent. A category/severity this module has never seen raises, rather than silently guessing
# an action type (the same "refuse to guess" discipline the deterministic engine applies to
# money, applied here to the recommendation vocabulary).

_SEVERITY_RANK: dict[str, int] = {
    "AT_RISK": 3,
    "HIGH": 3,
    "WATCH": 2,
    "MEDIUM": 2,
    "OPEN": 2,
    "LOW": 1,
    "GOOD": 0,
}

_ACTION_TYPE_BY_CATEGORY: dict[str, str] = {
    "PROFITABILITY": "REVIEW_PRICING_OR_COGS",
    "FEE_RATIO": "REVIEW_FEE_MAPPING_OR_NEGOTIATE",
    "RETURN_RATE": "INVESTIGATE_RETURNS_RTO",
    "LEAK": "REVIEW_LEAK_FINDING",
    "ANOMALY": "INVESTIGATE_ANOMALY",
    "EXPENSE_BUDGET": "REVIEW_EXPENSE_BUDGET",
    "DATA_GAP": "PROVIDE_MISSING_DATA",
    "PRICING": "CONSIDER_PRICE_CHANGE",
    "SUPPLIER": "CONSIDER_SUPPLIER_SWITCH",
}

# Metric -> signal category, for Financial Health Band inputs specifically (cfo-agent.md §6.15).
_HEALTH_METRIC_CATEGORY: dict[str, str] = {
    "CONTRIBUTION_MARGIN_PCT": "PROFITABILITY",
    "FEE_RATIO_PCT": "FEE_RATIO",
    "RETURN_RATE_PCT": "RETURN_RATE",
}


@dataclass(frozen=True, slots=True)
class SignalEvidence:
    """One already-computed value backing a signal — carried through unchanged, in whichever
    of the three shapes its own source used (never converted between them, never combined).
    Exactly one of `value_paise`/`value_fraction`/`text_value` is populated. Formatting into a
    display string happens in `backend.services.cfo_actions` (the established
    `_format_paise_for_narration`/`_format_fraction_as_decimal_for_narration` boundary), never
    here — this module is presentation-agnostic, same as `cfo.leak.compose`."""

    label: str
    value_paise: int | None = None
    value_fraction: Fraction | None = None
    text_value: str | None = None
    is_available: bool = True
    register: str = "DERIVED"
    engine_result_ref: UUID | None = None


@dataclass(frozen=True, slots=True)
class StrategicSignal:
    category: str  # PROFITABILITY | FEE_RATIO | RETURN_RATE | LEAK | ANOMALY | EXPENSE_BUDGET | DATA_GAP
    severity_rank: int  # 0 (GOOD) .. 3 (AT_RISK/HIGH/OPEN) — closed, deterministic
    severity_label: str  # the raw band/severity string this rank was computed from
    recommended_action_type: str  # closed vocabulary, from _ACTION_TYPE_BY_CATEGORY
    headline: str
    evidence: tuple[SignalEvidence, ...]


# --- Per-source signal builders ----------------------------------------------------------------
# Each function below takes ONE already-computed outcome shape and produces zero or more
# StrategicSignals from it — no cross-source logic, no arithmetic, no LLM. `compose_strategic_
# signals` at the bottom is the only place these are combined and ranked.


@dataclass(frozen=True, slots=True)
class FinancialHealthMetricInput:
    """One classified metric from `backend.services.cfo_actions.FinancialHealthOutcome`
    (cfo-agent.md §6.15) — `metric`/`band`/`value_fraction`/`engine_result_ref` copied through
    unchanged, never re-derived."""

    metric: str
    band: str  # HealthBand.value — GOOD | WATCH | AT_RISK
    value_fraction: Fraction
    engine_result_ref: UUID


def signals_from_financial_health(inputs: Sequence[FinancialHealthMetricInput]) -> list[StrategicSignal]:
    """Skips GOOD-band metrics entirely — a signal exists to flag something worth attention,
    not to restate "this is fine" (mirrors `finding_severity`'s own "never a default LOW/GOOD
    entry" discipline: absence of a signal for a healthy metric is itself the correct,
    honest output, not an omission)."""
    signals: list[StrategicSignal] = []
    for inp in inputs:
        if inp.band == "GOOD":
            continue
        category = _HEALTH_METRIC_CATEGORY.get(inp.metric)
        if category is None:
            raise ValueError(
                f"compose_strategic_signals has no signal category for financial-health metric "
                f"{inp.metric!r} — cfo-agent.md §6.15 only names "
                f"{sorted(_HEALTH_METRIC_CATEGORY)}; refusing to guess one."
            )
        signals.append(
            StrategicSignal(
                category=category,
                severity_rank=_SEVERITY_RANK[inp.band],
                severity_label=inp.band,
                recommended_action_type=_ACTION_TYPE_BY_CATEGORY[category],
                headline=f"{inp.metric} is {inp.band}",
                evidence=(
                    SignalEvidence(
                        label=inp.metric,
                        value_fraction=inp.value_fraction,
                        register="DERIVED",
                        engine_result_ref=inp.engine_result_ref,
                    ),
                ),
            )
        )
    return signals


@dataclass(frozen=True, slots=True)
class AnomalyFlagInput:
    """One fired `AnomalyFlag` (`calc_engine.anomaly.types`) — only FIRED flags are worth a
    signal; a non-fired/insufficient-history/zero-variance/configuration-gap outcome is not
    itself a strategic signal (it may still be worth surfacing elsewhere, e.g. as a
    DATA_GAP via `signals_from_data_requests`, but this builder's job is fired anomalies only)."""

    metric: str
    method: str
    target_ref: str
    severity: str  # LOW | MEDIUM | HIGH
    score: Fraction
    decorates_engine_result_ref: UUID


def signals_from_anomaly_flags(flags: Sequence[AnomalyFlagInput]) -> list[StrategicSignal]:
    signals: list[StrategicSignal] = []
    for flag in flags:
        signals.append(
            StrategicSignal(
                category="ANOMALY",
                severity_rank=_SEVERITY_RANK.get(flag.severity, 1),
                severity_label=flag.severity,
                recommended_action_type=_ACTION_TYPE_BY_CATEGORY["ANOMALY"],
                headline=f"{flag.metric} anomaly ({flag.method}) for {flag.target_ref}",
                evidence=(
                    SignalEvidence(
                        label=f"{flag.metric} anomaly score ({flag.method})",
                        value_fraction=flag.score,
                        register="DERIVED",
                        engine_result_ref=flag.decorates_engine_result_ref,
                    ),
                ),
            )
        )
    return signals


@dataclass(frozen=True, slots=True)
class LeakFindingInput:
    """One already-persisted `leak_finding` row (`cfo.repositories.leak_finding_repo`) — every
    field copied through, never recomputed. `severity` here is already `rank_findings`'s own
    output, persisted at write time by `run_leak_shield_reconciliation`."""

    leak_finding_id: UUID
    leak_category: str
    severity: str  # LOW | MEDIUM | HIGH
    amount_paise: int
    marketplace: str
    engine_result_ref: UUID
    confidence: str


def signals_from_leak_findings(findings: Sequence[LeakFindingInput]) -> list[StrategicSignal]:
    signals: list[StrategicSignal] = []
    for finding in findings:
        signals.append(
            StrategicSignal(
                category="LEAK",
                severity_rank=_SEVERITY_RANK.get(finding.severity, 1),
                severity_label=finding.severity,
                recommended_action_type=_ACTION_TYPE_BY_CATEGORY["LEAK"],
                headline=f"{finding.leak_category} leak on {finding.marketplace}",
                evidence=(
                    SignalEvidence(
                        label=f"{finding.leak_category} amount",
                        value_paise=finding.amount_paise,
                        register=finding.confidence,
                        engine_result_ref=finding.engine_result_ref,
                    ),
                ),
            )
        )
    return signals


@dataclass(frozen=True, slots=True)
class ExpenseBudgetInput:
    """One `ExpenseBudgetCheckResult`-shaped outcome (`backend.services.cfo_actions.
    check_expense_budget`) for one category/period — only an EXCEEDED budget produces a signal
    (an on-track budget is the healthy, silent case, same discipline as
    `signals_from_financial_health` skipping GOOD)."""

    category: str
    exceeded: bool
    remaining_paise: int  # negative when exceeded — the real overage amount, never floored


def signals_from_expense_budgets(inputs: Sequence[ExpenseBudgetInput]) -> list[StrategicSignal]:
    signals: list[StrategicSignal] = []
    for inp in inputs:
        if not inp.exceeded:
            continue
        signals.append(
            StrategicSignal(
                category="EXPENSE_BUDGET",
                severity_rank=_SEVERITY_RANK["WATCH"],
                severity_label="EXCEEDED",
                recommended_action_type=_ACTION_TYPE_BY_CATEGORY["EXPENSE_BUDGET"],
                headline=f"{inp.category} expense budget exceeded",
                evidence=(
                    SignalEvidence(
                        label=f"{inp.category} budget overage",
                        value_paise=inp.remaining_paise,
                        register="MANUAL",
                    ),
                ),
            )
        )
    return signals


@dataclass(frozen=True, slots=True)
class DataRequestInput:
    """One OPEN `agent_data_request` row (`cfo.repositories.agent_data_request_repo`) — the
    CFO's own existing "I need this to compute X" record, reused as a signal source rather than
    a second, competing "what's missing" mechanism."""

    requested_field: str
    reason: str
    blocking_metric: str | None


def signals_from_data_requests(requests: Sequence[DataRequestInput]) -> list[StrategicSignal]:
    signals: list[StrategicSignal] = []
    seen: set[tuple[str, str, str | None]] = set()
    for req in requests:
        # Every failed run raises its own OPEN row, so asking again leaves several rows that say exactly the same thing. One signal per distinct (field, reason, blocking
        # metric): requests that differ in any of the three (another SKU, another metric) are still all shown.
        key = (req.requested_field, req.reason, req.blocking_metric)
        if key in seen:
            continue
        seen.add(key)
        blocking = f" (blocks {req.blocking_metric})" if req.blocking_metric else ""
        signals.append(
            StrategicSignal(
                category="DATA_GAP",
                severity_rank=_SEVERITY_RANK["OPEN"],
                severity_label="OPEN",
                recommended_action_type=_ACTION_TYPE_BY_CATEGORY["DATA_GAP"],
                headline=f"Missing: {req.requested_field}{blocking}",
                evidence=(SignalEvidence(label=req.requested_field, text_value=req.reason, register="MANUAL"),),
            )
        )
    return signals


@dataclass(frozen=True, slots=True)
class PricingCandidateInput:
    """One `compute_pricing_curve` candidate — `margin_pct`/`ref` copied through unchanged."""

    sku: str
    price_paise: int
    margin_pct: Fraction
    engine_result_ref: UUID


@dataclass(frozen=True, slots=True)
class SupplierRankInput:
    """One `rank_suppliers` result — `landed_cost_paise`/`ref` copied through unchanged."""

    sku: str
    supplier_name: str
    landed_cost_paise: int
    engine_result_ref: UUID


def signals_from_pricing_candidates(candidates: Sequence[PricingCandidateInput]) -> list[StrategicSignal]:
    """`compute_pricing_curve` already returns multiple candidates (a band, never a single
    optimum) — this signal exists only when there is genuinely something to compare (2+
    candidates), never invents a "best price," only surfaces the highest-margin one already
    computed as worth a look."""
    if len(candidates) < 2:
        return []
    best = max(candidates, key=lambda c: c.margin_pct)
    sku = candidates[0].sku
    return [
        StrategicSignal(
            category="PRICING",
            severity_rank=_SEVERITY_RANK["WATCH"],
            severity_label="COMPARISON_AVAILABLE",
            recommended_action_type="CONSIDER_PRICE_CHANGE",
            headline=f"{len(candidates)} price candidates compared for {sku}",
            evidence=(
                SignalEvidence(
                    label=f"Highest-margin candidate ({sku})",
                    value_fraction=best.margin_pct,
                    register="DERIVED",
                    engine_result_ref=best.engine_result_ref,
                ),
            ),
        )
    ]


def signals_from_supplier_ranking(ranked: Sequence[SupplierRankInput]) -> list[StrategicSignal]:
    """Only fires with a genuine ranking (2+ quotes) — a single quote is not a comparison
    (§6.11/E15). Cites the cheapest (assumed pre-sorted ascending, `rank_suppliers`'s own
    contract) vs. the most expensive, never inventing a "switch" recommendation itself."""
    if len(ranked) < 2:
        return []
    cheapest, priciest = ranked[0], ranked[-1]
    sku = cheapest.sku
    return [
        StrategicSignal(
            category="SUPPLIER",
            severity_rank=_SEVERITY_RANK["WATCH"],
            severity_label="COMPARISON_AVAILABLE",
            recommended_action_type="CONSIDER_SUPPLIER_SWITCH",
            headline=f"{len(ranked)} supplier quotes ranked for {sku}",
            evidence=(
                SignalEvidence(
                    label=f"Cheapest landed cost ({cheapest.supplier_name})",
                    value_paise=cheapest.landed_cost_paise,
                    register="MANUAL",
                    engine_result_ref=cheapest.engine_result_ref,
                ),
                SignalEvidence(
                    label=f"Most expensive landed cost ({priciest.supplier_name})",
                    value_paise=priciest.landed_cost_paise,
                    register="MANUAL",
                    engine_result_ref=priciest.engine_result_ref,
                ),
            ),
        )
    ]


def compose_strategic_signals(
    *,
    financial_health: Sequence[FinancialHealthMetricInput] = (),
    anomaly_flags: Sequence[AnomalyFlagInput] = (),
    leak_findings: Sequence[LeakFindingInput] = (),
    expense_budgets: Sequence[ExpenseBudgetInput] = (),
    data_requests: Sequence[DataRequestInput] = (),
    pricing_candidates: Sequence[PricingCandidateInput] = (),
    supplier_ranking: Sequence[SupplierRankInput] = (),
) -> list[StrategicSignal]:
    """Combines every source's signals and sorts them: `severity_rank` descending, ties broken
    by `category` then `headline` (both plain strings) for a byte-identical, deterministic
    order across runs — never left to dict/list insertion order, the same discipline
    `rank_findings` already applies via its own `exception_id` tiebreak."""
    signals: list[StrategicSignal] = [
        *signals_from_financial_health(financial_health),
        *signals_from_anomaly_flags(anomaly_flags),
        *signals_from_leak_findings(leak_findings),
        *signals_from_expense_budgets(expense_budgets),
        *signals_from_data_requests(data_requests),
        *signals_from_pricing_candidates(pricing_candidates),
        *signals_from_supplier_ranking(supplier_ranking),
    ]
    return sorted(signals, key=lambda s: (-s.severity_rank, s.category, s.headline))
