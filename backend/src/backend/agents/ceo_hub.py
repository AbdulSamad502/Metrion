"""The dummy CEO Hub — the first CEO-to-agent integration pattern in this codebase.

This is deliberately NOT `ceo-agent-orchestration.md`'s real CEO. There is no LLM
classification, no conversational routing, no multi-action turn — three hardcoded actions
(`ci.research_now`, `ci.discover_competitors`, `ci.request_price_scenario`) are accepted and
dispatched, each a thin, fixed route to an existing CI composition function; nothing here
decides *which* action to run. Its purpose is to prove the parent/child `agent_run` linkage
(C7: "every fanned-out sub-agent/Brain-1 call gets parent_run_id set to that row's id") works
end-to-end for CI's real actions, before the real CEO's classifier/routing layer is built.
Every other agent (PI/CFO/CMO) stays unconnected.

Requires `packages/competitor-intelligence` to be installed in this environment
(`pip install -e packages/competitor-intelligence`, before `pip install -e backend[dev]` —
see `backend/README.md`'s "Running locally" and the comment in `backend/pyproject.toml` for
why it isn't declared as a normal dependency there). `.github/workflows/ci.yml` now installs
both, in that order, and runs backend's own test suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import UUID

from competitor_intelligence.direct_path.research_run import ResearchSessionResult, submit_research_session
from competitor_intelligence.discovery.discovery_run import DiscoveryRunOutcome
from competitor_intelligence.evidence.extraction import VisionExtractor
from competitor_intelligence.seller_product.types import SellerProduct

from backend.entitlement import (
    EntitlementDenied,
    cfo_entitlement_check_value,
    entitlement_check_value,
    resolve_cfo_entitlement,
    resolve_ci_entitlement,
)
from backend.repositories import agent_run_repo
from backend.services.cfo_actions import (
    AnomalyCheckOutcome,
    AnomalyCheckRequest,
    BatchSizeOutcome,
    BatchSizeRequest,
    FundingReadinessOutcome,
    FundingReadinessRequest,
    GstLineInput,
    GstLineResult,
    GstPeriodSummaryOutcome,
    GstPeriodSummaryRequest,
    LandedCostOutcome,
    LandedCostRequest,
    LeakShieldOutcome,
    PeriodComparisonOutcome,
    PeriodComparisonRequest,
    PeriodPnlOutcome,
    PeriodPnlRequest,
    PricingCurveOutcome,
    PricingCurveRequest,
    SupplierRankingOutcome,
    SupplierRankingRequest,
    analyze_gst_lines,
    assemble_batch_size_estimate,
    assemble_funding_readiness_reduced,
    compute_landed_cost_for_quote,
    compute_period_pnl,
    compute_pricing_curve,
    enter_expense,
    narrate_period_comparison,
    rank_suppliers,
    render_gst_period_summary,
    run_anomaly_check,
    run_leak_shield_reconciliation,
)
from backend.services.ci_actions import PriceScenarioOutcome, run_discovery, run_price_scenario
from cfo.reasoning.provider import LlmProvider

CI_RESEARCH_NOW = "ci.research_now"
CI_DISCOVER_COMPETITORS = "ci.discover_competitors"
CI_REQUEST_PRICE_SCENARIO = "ci.request_price_scenario"

# cfo-agent.md / twinkly-mapping-canyon.md CP2 (P&L/expense/GST-lines) + CP A1 (pricing) +
# CP A2 (GST period total) + CP A3 (period comparison) + CP A4 (landed cost primitive) — the
# seven real-backed CFO actions this dummy CEO knows.
# `CFO_GST_SUMMARY` is the PERIOD-level GST total — a genuinely separate surface from
# `CFO_ANALYZE_GST_LINES`'s LINE-level analysis; the two are never merged or confused.
# `CFO_LANDED_COST` is the supplier-ranking PRIMITIVE only (cfo-agent.md §6.11) — one quote's
# landed cost, never a comparison/ranking across quotes. `CFO_SUPPLIER_RANKING` (Phase B1,
# twinkly-mapping-canyon.md) is the ranking itself — every ACTIVE supplier.quote row for a SKU,
# sorted ascending by landed cost. `CFO_FUNDING_READINESS` (Phase B2) is the REDUCED §6.13
# slice only — Contribution Profit history/trend/gaps, no score (AC19); margin stability,
# revenue concentration and cash-conversion timing remain deferred to Phase D.
# `CFO_RECONCILE` (D5, `cfo-agent.md` §6.8's own `cfo.reconcile` trigger id, reused verbatim
# here) closes guardrail 4 — a real `reconcile()` now exists (D4) and this action routes to
# `backend.services.cfo_actions.run_leak_shield_reconciliation`, the first CEO/direct-execution
# path that produces real, persisted `leak_finding` rows.
CFO_PNL = "cfo.pnl"
CFO_ENTER_EXPENSE = "cfo.enter_expense"
CFO_ANALYZE_GST_LINES = "cfo.analyze_gst_lines"
CFO_PRICING = "cfo.pricing"
CFO_GST_SUMMARY = "cfo.gst_summary"
CFO_PERIOD_COMPARISON = "cfo.period_comparison"
CFO_LANDED_COST = "cfo.landed_cost"
CFO_SUPPLIER_RANKING = "cfo.supplier_ranking"
CFO_FUNDING_READINESS = "cfo.funding_readiness"
# `CFO_BATCH_SIZE` (Phase B3b) — the full §6.12 estimate: B3a's engine core wired with sales
# velocity, the batch.budget lookup/expiry check, and §6.12's agent_data_request behaviour. This
# exact string is already named in cfo-agent.md §6.12's own text ("the cfo.batch_size direct
# path itself"), so it is reused verbatim here rather than invented anew.
CFO_BATCH_SIZE = "cfo.batch_size"
# `CFO_ANOMALY_CHECK` (E3) — wires Brain 2 (`calc_engine.anomaly`, E2) into CFO for the
# `MARGIN_PCT` series (anomaly-detection.md; cfo-agent.md §6.1 rule 4/§6.5/§7). Not a spec-named
# trigger id (anomaly-detection.md §8 rule 1: "Brain 2 has no endpoint of its own"; this is
# CFO's own new direct-execution path invoking it, not Brain 2 exposing one itself) — named to
# match this file's own `cfo.<verb>` convention.
CFO_ANOMALY_CHECK = "cfo.anomaly_check"
# `CFO_RECONCILE` (D5) — Leak Shield's real reconciliation trigger. This exact string is
# already named in cfo-agent.md §6.8's own table row for `cfo.reconcile` — reused verbatim,
# not invented anew.
CFO_RECONCILE = "cfo.reconcile"


@dataclass(frozen=True, slots=True)
class CeoHubResult:
    ceo_agent_run_id: UUID
    ci_result: ResearchSessionResult


def dispatch_ci_research_now(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    competitor_url_id: UUID,
    image_refs: Sequence[str],
    manual_fields: Mapping[str, Any] | None,
    permission_check: str,
    extractor: VisionExtractor,
    now: datetime | None = None,
) -> CeoHubResult:
    """The one action this dummy CEO knows: route a research request to CI, exactly as a
    real CEO would per the star topology (C1) — CEO is the only router, CI never gets called
    by another agent directly. `entitlement_check` goes through `backend.entitlement.
    resolve_ci_entitlement` — a real chokepoint, not a bare string — which always passes
    today because no entitlement spec exists yet to define a deny threshold
    (competitor-intelligence-agent.md §12 Q2/Q3, `auth.md` line 5); see that module's
    docstring for why. `permission_check`, by contrast, IS real — it's `agent.ci`, verified
    by `auth/context.py`'s six-step chain before this function is ever called (see
    `api/v1/ceo_hub.py`).
    """
    now = now or datetime.now(timezone.utc)
    entitlement_check = entitlement_check_value(resolve_ci_entitlement(tenant_id))

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",  # no LLM classification happened — see agent_run_repo docstring note
        trigger_ref=f"ceo_hub.{CI_RESEARCH_NOW}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    ci_result = submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=competitor_url_id,
        image_refs=image_refs,
        manual_fields=manual_fields,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        extractor=extractor,
        now=now,
        parent_run_id=ceo_agent_run_id,
    )

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status=ci_result.status.value,
        error_reason=None if ci_result.status.value != "FAILED" else "CI research session failed",
        finished_at=now,
    )

    return CeoHubResult(ceo_agent_run_id=ceo_agent_run_id, ci_result=ci_result)


@dataclass(frozen=True, slots=True)
class CeoHubDiscoveryResult:
    ceo_agent_run_id: UUID
    outcome: DiscoveryRunOutcome


def dispatch_ci_discover_competitors(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    seller_product: SellerProduct,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubDiscoveryResult:
    """The CEO Hub's second fixed action (Checkpoint 7): route a discovery request to CI's
    §6.10-§6.15 pipeline exactly as `dispatch_ci_research_now` routes a research request —
    same composition root (`backend.services.ci_actions.run_discovery`, shared with the CI
    direct-execution route per C20 so the two paths can never diverge). Unlike
    `dispatch_ci_research_now`, `start_discovery_run` itself logs no CI-side `agent_run` row
    (neither does the existing `POST /discovery-runs` HTTP route it's shared with) — the
    discovery run's own row (`ci_discovery_run`) is its provenance trail instead, so this CEO
    row is the only `agent_run` this action produces. Documented, not a regression: the same
    is true of the pre-existing direct-execution path."""
    now = now or datetime.now(timezone.utc)
    entitlement_check = entitlement_check_value(resolve_ci_entitlement(tenant_id))

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CI_DISCOVER_COMPETITORS}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = run_discovery(tenant_id, requested_by=requested_by, seller_product=seller_product)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status=outcome.status,
        error_reason=outcome.failed_reason if outcome.status == "FAILED" else None,
        finished_at=now,
    )

    return CeoHubDiscoveryResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubPriceScenarioResult:
    ceo_agent_run_id: UUID
    outcome: PriceScenarioOutcome | None


def dispatch_ci_request_price_scenario(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    competitor_url_id: UUID,
    seller_price_paise: int,
    stance: str | None,
    stance_param_pct: Decimal | None,
    stance_param_paise: int | None,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubPriceScenarioResult:
    """The CEO Hub's third fixed action (Checkpoint 7): route a price-scenario request to
    §5.15's engine wiring via the same `run_price_scenario` composition the CI direct-
    execution route (`POST /competitor-urls/{id}/price-scenario`) uses — C20 requires both
    entry paths enforce identical checks; sharing one function is how that stays true rather
    than merely documented. `outcome is None` means the competitor_url wasn't found/owned by
    this tenant; the `agent_run` is marked FAILED for that case rather than raising, since a
    CEO-routed action never bubbles an HTTP exception to its own caller. As with
    `dispatch_ci_discover_competitors`, `run_price_scenario` logs no separate CI-side
    `agent_run` row — the persisted `metric_result` rows are the provenance trail, matching
    the pre-existing `POST .../price-scenario` route's own behavior."""
    now = now or datetime.now(timezone.utc)
    entitlement_check = entitlement_check_value(resolve_ci_entitlement(tenant_id))

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CI_REQUEST_PRICE_SCENARIO}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = run_price_scenario(
        tenant_id,
        competitor_url_id,
        seller_price_paise=seller_price_paise,
        stance=stance,
        stance_param_pct=stance_param_pct,
        stance_param_paise=stance_param_paise,
        now=now,
    )

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome is not None else "FAILED",
        error_reason=None if outcome is not None else "competitor_url not found, not ACTIVE, or not owned by this tenant",
        finished_at=now,
    )

    return CeoHubPriceScenarioResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoPnlResult:
    ceo_agent_run_id: UUID
    outcome: PeriodPnlOutcome


def dispatch_cfo_pnl(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: PeriodPnlRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoPnlResult:
    """The CEO Hub's first CFO action: route a period P&L request to
    `backend.services.cfo_actions.compute_period_pnl` — the same composition root
    `api/v1/cfo.py`'s direct-execution route uses (C20). `entitlement_check` goes through
    `backend.entitlement.resolve_cfo_entitlement` — a real, comparison-based evaluation (F2)
    that resolves `NO_CAP_CONFIGURED`/always-passes today only because no cap is seeded yet
    (see that module's docstring)."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(tenant_id, direct_action_code=CFO_PNL, occurred_at=now)
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_PNL}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_PNL}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = compute_period_pnl(tenant_id, request)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome.contribution_profit.is_available else "PARTIAL",
        error_reason=None if outcome.contribution_profit.is_available else outcome.contribution_profit.unavailable_reason,
        finished_at=now,
    )

    return CeoHubCfoPnlResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoEnterExpenseResult:
    ceo_agent_run_id: UUID
    manual_adjustment_id: UUID


def dispatch_cfo_enter_expense(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    target_type: str,
    target_ref: str,
    field: str,
    value: Any,
    reason: str | None,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoEnterExpenseResult:
    """The CEO Hub's second CFO action: route a manual expense entry to
    `backend.services.cfo_actions.enter_expense` — same composition root the direct-execution
    `PUT /api/v1/cfo/expenses` route uses. `permission_check` here is `agent.cfo` (checked by
    `require_auth` before this function is reached, same as every other dummy-CEO action); the
    caller is additionally responsible for the second `financials.adjust` check (§8 rule 4 /
    E19), exactly as `api/v1/cfo.py`'s route does in-handler."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_ENTER_EXPENSE, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_ENTER_EXPENSE}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_ENTER_EXPENSE}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    try:
        manual_adjustment_id = enter_expense(
            tenant_id,
            target_type=target_type,
            target_ref=target_ref,
            field=field,
            value=value,
            created_by=requested_by,
            reason=reason,
            now=now,
        )
    except ValueError as exc:
        agent_run_repo.finish_run(
            tenant_id, ceo_agent_run_id, status="FAILED", error_reason=str(exc), finished_at=now
        )
        raise

    agent_run_repo.finish_run(tenant_id, ceo_agent_run_id, status="COMPLETE", error_reason=None, finished_at=now)
    return CeoHubCfoEnterExpenseResult(ceo_agent_run_id=ceo_agent_run_id, manual_adjustment_id=manual_adjustment_id)


@dataclass(frozen=True, slots=True)
class CeoHubCfoGstLinesResult:
    ceo_agent_run_id: UUID
    results: list[GstLineResult]


def dispatch_cfo_analyze_gst_lines(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    lines: Sequence[GstLineInput],
    as_of_date: date,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoGstLinesResult:
    """The CEO Hub's third CFO action: route a line-level GST analysis request to
    `backend.services.cfo_actions.analyze_gst_lines` — line-level only, never a period total
    (cfo-agent.md §6.6, `gst/summary.py` stays a stub)."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_ANALYZE_GST_LINES, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_ANALYZE_GST_LINES}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_ANALYZE_GST_LINES}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    results = analyze_gst_lines(tenant_id, lines, as_of_date=as_of_date)

    agent_run_repo.finish_run(tenant_id, ceo_agent_run_id, status="COMPLETE", error_reason=None, finished_at=now)
    return CeoHubCfoGstLinesResult(ceo_agent_run_id=ceo_agent_run_id, results=results)


@dataclass(frozen=True, slots=True)
class CeoHubCfoPricingResult:
    ceo_agent_run_id: UUID
    outcome: PricingCurveOutcome


def dispatch_cfo_pricing(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: PricingCurveRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoPricingResult:
    """The CEO Hub's fourth CFO action (twinkly-mapping-canyon.md CP A1): route a margin-curve
    request to `backend.services.cfo_actions.compute_pricing_curve` — the same composition
    root `api/v1/cfo.py`'s `POST /cfo/pricing` direct-execution route uses (C20).
    `entitlement_check` goes through `backend.entitlement.resolve_cfo_entitlement`, same
    always-pass-today plumbing as every other CFO dispatch function here. A run is marked
    PARTIAL rather than COMPLETE whenever `compute_pricing_curve` had to raise a data request
    (COGS, RTO, or fee_reference UNAVAILABLE — E14), mirroring `dispatch_cfo_pnl`'s own
    COMPLETE-vs-PARTIAL convention."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(tenant_id, direct_action_code=CFO_PRICING, occurred_at=now)
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_PRICING}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_PRICING}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = compute_pricing_curve(tenant_id, request)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome.data_request_id is None else "PARTIAL",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoPricingResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoGstSummaryResult:
    ceo_agent_run_id: UUID
    outcome: GstPeriodSummaryOutcome


def dispatch_cfo_gst_summary(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: GstPeriodSummaryRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoGstSummaryResult:
    """The CEO Hub's fifth CFO action (twinkly-mapping-canyon.md CP A2): route a PERIOD-level
    GST summary request to `backend.services.cfo_actions.render_gst_period_summary` — the same
    composition root `api/v1/cfo.py`'s `POST /cfo/gst/period-summary` direct-execution route
    uses (C20). This is genuinely distinct from `dispatch_cfo_analyze_gst_lines`'s LINE-level
    action — a period total and a line-level analysis are two separate CFO surfaces that must
    never be merged. `entitlement_check` goes through `backend.entitlement.
    resolve_cfo_entitlement`, same always-pass-today plumbing as every other CFO dispatch
    function here. `render_gst_period_summary` has no `Unavailable`/data-request path (a pure
    summation over already-present canonical tax components never fails for missing data), so
    this run is always marked COMPLETE, never PARTIAL."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_GST_SUMMARY, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_GST_SUMMARY}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_GST_SUMMARY}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = render_gst_period_summary(tenant_id, request)

    agent_run_repo.finish_run(tenant_id, ceo_agent_run_id, status="COMPLETE", error_reason=None, finished_at=now)

    return CeoHubCfoGstSummaryResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoPeriodComparisonResult:
    ceo_agent_run_id: UUID
    outcome: PeriodComparisonOutcome


def dispatch_cfo_period_comparison(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: PeriodComparisonRequest,
    provider: LlmProvider,
    model: str,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoPeriodComparisonResult:
    """The CEO Hub's sixth CFO action (twinkly-mapping-canyon.md CP A3): route a period-
    comparison narration request to `backend.services.cfo_actions.narrate_period_comparison`
    — the same composition root `api/v1/cfo.py`'s `POST /cfo/period-comparison` direct-
    execution route uses (C20). Activates cfo-agent.md §7.4.4's "once built" period-comparison
    narration rule now that the period-over-period metric-delta capability named in §5.1.2 is
    real end-to-end (engine CP3 + this checkpoint's CFO wiring). `entitlement_check` goes
    through `backend.entitlement.resolve_cfo_entitlement`, same always-pass-today plumbing as
    every other CFO dispatch function here. A run is marked PARTIAL rather than COMPLETE
    whenever `narrate_period_comparison` had to raise a data request (either `metric_result`
    id not found for this tenant — E2/E14-style), mirroring `dispatch_cfo_pnl`'s and
    `dispatch_cfo_pricing`'s own COMPLETE-vs-PARTIAL convention."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_PERIOD_COMPARISON, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_PERIOD_COMPARISON}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_PERIOD_COMPARISON}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = narrate_period_comparison(tenant_id, request, provider, model=model)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome.data_request_id is None else "PARTIAL",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoPeriodComparisonResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoLandedCostResult:
    ceo_agent_run_id: UUID
    outcome: LandedCostOutcome


def dispatch_cfo_landed_cost(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: LandedCostRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoLandedCostResult:
    """The CEO Hub's seventh CFO action (twinkly-mapping-canyon.md CP A4): route a per-quote
    landed-cost request to `backend.services.cfo_actions.compute_landed_cost_for_quote` — the
    same composition root `api/v1/cfo.py`'s `POST /cfo/landed-cost` direct-execution route
    uses (C20). This is the supplier-ranking *primitive* only (cfo-agent.md §6.11) — it
    computes exactly one quote's landed cost, never compares or ranks quotes (Phase B1, not
    yet built). `entitlement_check` goes through `backend.entitlement.resolve_cfo_entitlement`,
    same always-pass-today plumbing as every other CFO dispatch function here. A run is marked
    PARTIAL rather than COMPLETE whenever `compute_landed_cost_for_quote` had to raise a data
    request (zero or more-than-one ACTIVE `supplier.quote` rows for the target), mirroring
    `dispatch_cfo_pricing`'s own COMPLETE-vs-PARTIAL convention."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_LANDED_COST, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_LANDED_COST}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_LANDED_COST}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = compute_landed_cost_for_quote(tenant_id, request)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome.data_request_id is None else "PARTIAL",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoLandedCostResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoSupplierRankingResult:
    ceo_agent_run_id: UUID
    outcome: SupplierRankingOutcome


def dispatch_cfo_supplier_ranking(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: SupplierRankingRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoSupplierRankingResult:
    """The CEO Hub's eighth CFO action (twinkly-mapping-canyon.md CP B1): route a supplier-
    ranking request to `backend.services.cfo_actions.rank_suppliers` — the same composition
    root `api/v1/cfo.py`'s `POST /cfo/suppliers/rank` direct-execution route uses (C20). This
    is the ranking itself (cfo-agent.md §6.11) — every ACTIVE `supplier.quote` row for a SKU,
    sorted ascending by landed cost — genuinely distinct from `dispatch_cfo_landed_cost`'s
    single-quote primitive. `entitlement_check` goes through `backend.entitlement.
    resolve_cfo_entitlement`, same always-pass-today plumbing as every other CFO dispatch
    function here. A run is marked PARTIAL rather than COMPLETE whenever `rank_suppliers` had
    to raise a data request (zero ACTIVE rows, or every ACTIVE row failed to parse), mirroring
    `dispatch_cfo_landed_cost`'s own COMPLETE-vs-PARTIAL convention."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_SUPPLIER_RANKING, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_SUPPLIER_RANKING}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_SUPPLIER_RANKING}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = rank_suppliers(tenant_id, request)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome.data_request_id is None else "PARTIAL",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoSupplierRankingResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoFundingReadinessResult:
    ceo_agent_run_id: UUID
    outcome: FundingReadinessOutcome


def dispatch_cfo_funding_readiness(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: FundingReadinessRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoFundingReadinessResult:
    """The CEO Hub's ninth CFO action (twinkly-mapping-canyon.md CP B2): route a funding-
    readiness request to `backend.services.cfo_actions.assemble_funding_readiness_reduced` —
    the same composition root `api/v1/cfo.py`'s `POST /cfo/funding-readiness` direct-execution
    route uses (C20). This is the REDUCED §6.13 slice (cfo-agent.md §6.13/D7) — Contribution
    Profit history, trend and named gaps, no score/valuation/lending judgement (AC19); margin
    stability, revenue concentration and cash-conversion timing remain deferred to Phase D and
    are stated as such on the outcome itself (`FundingReadinessOutcome.deferred_sections`),
    never silently absent. `entitlement_check` goes through `backend.entitlement.
    resolve_cfo_entitlement`, same always-pass-today plumbing as every other CFO dispatch
    function here. A run is marked PARTIAL rather than COMPLETE whenever the assembly named at
    least one gap (missing period or UNAVAILABLE result), mirroring `dispatch_cfo_landed_cost`'s
    own COMPLETE-vs-PARTIAL convention — the full assembly (history/trend/gaps) is always
    returned either way (E21: thin data still produces a completeness report, never a refusal)."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_FUNDING_READINESS, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_FUNDING_READINESS}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_FUNDING_READINESS}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = assemble_funding_readiness_reduced(tenant_id, request)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome.data_request_id is None else "PARTIAL",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoFundingReadinessResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoBatchSizeResult:
    ceo_agent_run_id: UUID
    outcome: BatchSizeOutcome


def dispatch_cfo_batch_size(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: BatchSizeRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoBatchSizeResult:
    """The CEO Hub's tenth CFO action (twinkly-mapping-canyon.md CP B3b): route a batch-size
    request to `backend.services.cfo_actions.assemble_batch_size_estimate` — the same
    composition root `api/v1/cfo.py`'s `POST /cfo/batch-size` direct-execution route uses (C20).
    This is the full §6.12 estimate (engine core, B3a, plus this checkpoint's velocity/budget
    wiring) — a budget-constrained order-quantity range, never a demand forecast or guaranteed
    sell-through (D9). `entitlement_check` goes through `backend.entitlement.
    resolve_cfo_entitlement`, same always-pass-today plumbing as every other CFO dispatch
    function here. A run is marked PARTIAL rather than COMPLETE whenever `assemble_batch_size_
    estimate` had to raise a data request (missing/ambiguous/expired supplier.quote or
    batch.budget, or velocity+lead-time+MOQ all missing at once), mirroring every other CFO
    dispatch function's own COMPLETE-vs-PARTIAL convention."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_BATCH_SIZE, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_BATCH_SIZE}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_BATCH_SIZE}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = assemble_batch_size_estimate(tenant_id, request)

    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="COMPLETE" if outcome.data_request_id is None else "PARTIAL",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoBatchSizeResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoReconcileResult:
    ceo_agent_run_id: UUID
    outcome: LeakShieldOutcome


def dispatch_cfo_reconcile(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    marketplace: str,
    period_start: date,
    period_end: date,
    as_of_date: date,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoReconcileResult:
    """The CEO Hub's eleventh CFO action (D5, cfo-agent.md §6.2/§6.8 `cfo.reconcile`): route a
    Leak Shield reconciliation request to `backend.services.cfo_actions.
    run_leak_shield_reconciliation` — the same composition root `api/v1/cfo.py`'s
    `POST /cfo/reconcile` direct-execution route uses (C20). This is the first CFO dispatch
    action that produces real, persisted `leak_finding` rows — guardrail 4 ("no seller-facing
    Leak Shield findings until a real `reconcile()` exists") is closed as of this action, not
    before. `entitlement_check` goes through `backend.entitlement.resolve_cfo_entitlement`,
    same always-pass-today plumbing as every other CFO dispatch function here. A run is marked
    PARTIAL rather than COMPLETE whenever the reconciliation surfaced at least one
    `AMBIGUOUS_MATCH`/dates-missing exception it could not turn into a `leak_finding`
    (`ambiguous_match_count > 0` or `dates_missing_count > 0`) — the run itself always
    completes either way (this reconciliation never refuses outright), mirroring every other
    CFO dispatch function's own COMPLETE-vs-PARTIAL convention."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_RECONCILE, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_RECONCILE}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_RECONCILE}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = run_leak_shield_reconciliation(
        tenant_id,
        marketplace=marketplace,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
    )

    is_partial = outcome.ambiguous_match_count > 0 or outcome.dates_missing_count > 0
    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="PARTIAL" if is_partial else "COMPLETE",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoReconcileResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)


@dataclass(frozen=True, slots=True)
class CeoHubCfoAnomalyCheckResult:
    ceo_agent_run_id: UUID
    outcome: AnomalyCheckOutcome


def dispatch_cfo_anomaly_check(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    request: AnomalyCheckRequest,
    permission_check: str,
    now: datetime | None = None,
) -> CeoHubCfoAnomalyCheckResult:
    """E3: route a `MARGIN_PCT` anomaly-check request to `backend.services.cfo_actions.
    run_anomaly_check` — the same composition root `api/v1/cfo.py`'s `POST /cfo/anomaly-check`
    direct-execution route uses (C20). Wires Brain 2 (`calc_engine.anomaly`, E2) into CFO for
    the one named series this checkpoint has a real, spec-grounded formula for (anomaly-
    detection.md §6.1 `MARGIN_PCT`) — `FEE_RATIO_PCT`, `SETTLEMENT_LAG_DAYS` and
    `RETURN_RATE_PCT` remain out of scope. `entitlement_check` goes through `backend.
    entitlement.resolve_cfo_entitlement`, same always-pass-today plumbing as every other CFO
    dispatch function here — **mandatory, unlike `cfo.preview`'s documented, deliberate
    exemption** (§6.8's own table: anomaly-check is not that case). A run is marked PARTIAL
    rather than COMPLETE whenever at least one of the three methods came back a
    `AnomalyConfigurationGap` (no `anomaly_detection_config` row for `(MARGIN_PCT, <method>)`,
    real and expected in V1 since this spec deliberately ships with no seeded config rows) —
    mirroring every other CFO dispatch function's own COMPLETE-vs-PARTIAL convention; the full
    three-method outcome is always returned regardless."""
    now = now or datetime.now(timezone.utc)
    entitlement_result = resolve_cfo_entitlement(
        tenant_id, direct_action_code=CFO_ANOMALY_CHECK, occurred_at=now
    )
    entitlement_check = cfo_entitlement_check_value(entitlement_result)

    if not entitlement_result.passed:
        ceo_agent_run_id = agent_run_repo.insert_run(
            tenant_id,
            agent_id="CEO",
            trigger_type="DIRECT",
            trigger_ref=f"ceo_hub.{CFO_ANOMALY_CHECK}",
            requested_by=requested_by,
            permission_check=permission_check,
            entitlement_check=entitlement_check,
            status="RUNNING",
            started_at=now,
        )
        agent_run_repo.finish_run(
            tenant_id,
            ceo_agent_run_id,
            status="FAILED",
            error_reason=entitlement_result.reason or "entitlement denied",
            finished_at=now,
        )
        raise EntitlementDenied(entitlement_result)

    ceo_agent_run_id = agent_run_repo.insert_run(
        tenant_id,
        agent_id="CEO",
        trigger_type="DIRECT",
        trigger_ref=f"ceo_hub.{CFO_ANOMALY_CHECK}",
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        status="RUNNING",
        started_at=now,
    )

    outcome = run_anomaly_check(tenant_id, request)

    has_configuration_gap = any(m.configuration_gap is not None for m in outcome.methods)
    agent_run_repo.finish_run(
        tenant_id,
        ceo_agent_run_id,
        status="PARTIAL" if has_configuration_gap else "COMPLETE",
        error_reason=None,
        finished_at=now,
    )

    return CeoHubCfoAnomalyCheckResult(ceo_agent_run_id=ceo_agent_run_id, outcome=outcome)
