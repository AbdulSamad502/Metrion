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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import UUID

from competitor_intelligence.direct_path.research_run import ResearchSessionResult, submit_research_session
from competitor_intelligence.discovery.discovery_run import DiscoveryRunOutcome
from competitor_intelligence.evidence.extraction import VisionExtractor
from competitor_intelligence.seller_product.types import SellerProduct

from backend.entitlement import entitlement_check_value, resolve_ci_entitlement
from backend.repositories import agent_run_repo
from backend.services.ci_actions import PriceScenarioOutcome, run_discovery, run_price_scenario

CI_RESEARCH_NOW = "ci.research_now"
CI_DISCOVER_COMPETITORS = "ci.discover_competitors"
CI_REQUEST_PRICE_SCENARIO = "ci.request_price_scenario"


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
