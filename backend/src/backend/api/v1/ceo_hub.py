"""The CEO Hub's own API surface — Step 4's dummy CEO. See `backend/agents/ceo_hub.py` for
what "dummy" means here: one hardcoded action, no LLM, no conversational routing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.agents import ceo_hub
from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CI
from backend.config import (
    ci_evidence_storage_dir,
    ci_vision_model,
    ollama_host,
    ollama_keep_alive,
    ollama_vision_timeout_seconds,
)
from backend.repositories import agent_run_repo
from backend.services.ci_actions import load_seller_product
from backend.tenant_context import tenant_scope
from competitor_intelligence.evidence.image_store import LocalDiskImageStore
from competitor_intelligence.evidence.ollama_client import HttpOllamaClient
from competitor_intelligence.evidence.vision_extractor import OllamaVisionExtractor

router = APIRouter(prefix="/api/v1/ceo-hub")


def _vision_extractor() -> OllamaVisionExtractor:
    """Composition root for the real vision extractor (§1a item 4 is no longer fully open —
    a model is now wired; Q7's *quality* question remains genuinely open and unaffected by
    this). A stateless dataclass, cheap to build per request; no caching needed."""
    return OllamaVisionExtractor(
        image_store=LocalDiskImageStore(ci_evidence_storage_dir()),
        ollama=HttpOllamaClient(
            host=ollama_host(), timeout_seconds=ollama_vision_timeout_seconds(), keep_alive=ollama_keep_alive()
        ),
        model=ci_vision_model(),
    )

# Static for Step 4 — PI/CFO/CMO have no implementation to report a real status for yet.
# This list itself is the "Agent Status" the dashboard renders; it becomes a real registry
# once more agents exist.
_AGENT_STATUSES: list[dict[str, str]] = [
    {"id": "CI", "name": "Competitor Intelligence", "status": "CONNECTED"},
    {"id": "PI", "name": "Product Intelligence", "status": "NOT_CONNECTED"},
    {"id": "CFO", "name": "CFO", "status": "NOT_CONNECTED"},
    {"id": "CMO", "name": "CMO", "status": "NOT_CONNECTED"},
]


@router.get("/agents")
def list_agents() -> list[dict[str, str]]:
    return _AGENT_STATUSES


class ResearchNowRequest(BaseModel):
    competitor_url_id: UUID
    image_refs: list[str] = []
    manual_fields: dict[str, Any] = {}


@router.post("/research-now")
def research_now(
    body: ResearchNowRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    assert ctx.tenant_id is not None
    try:
        result = ceo_hub.dispatch_ci_research_now(
            ctx.tenant_id,
            requested_by=ctx.app_user_id,
            competitor_url_id=body.competitor_url_id,
            image_refs=body.image_refs,
            manual_fields=body.manual_fields,
            permission_check="PASS",  # real — require_auth(permission=AGENT_CI) already enforced this
            extractor=_vision_extractor(),
        )
    except NotImplementedError as exc:
        # Defensive only — the real extractor never raises this; kept in case a future
        # composition-root change reverts to UnimplementedVisionExtractor. A genuinely
        # unreachable Ollama host degrades each screenshot to ExtractionFailed instead,
        # which flows into PENDING_MANUAL_ENTRY/PARTIAL (the intended fallback), not a 501.
        raise HTTPException(
            status_code=501,
            detail=f"Automatic screenshot extraction isn't available yet: {exc} "
            "Submit manualFields instead, or leave imageRefs empty.",
        ) from None

    ci = result.ci_result
    return {
        "ceoAgentRunId": str(result.ceo_agent_run_id),
        "ci": {
            "agentRunId": str(ci.agent_run_id),
            "ciCaptureRunId": str(ci.ci_capture_run_id),
            "researchSessionId": str(ci.research_session_id),
            "status": ci.status.value,
            "snapshotId": str(ci.snapshot_id) if ci.snapshot_id else None,
            "captureStatus": ci.capture_status.value if ci.capture_status else None,
            "priceEventId": str(ci.price_event_id) if ci.price_event_id else None,
        },
    }


class DiscoverCompetitorsRequest(BaseModel):
    product_id: str


@router.post("/discover-competitors")
def discover_competitors(
    body: DiscoverCompetitorsRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """Checkpoint 7's second fixed CEO Hub action (`ci.discover_competitors`) — routes to the
    same §6.10-§6.15 discovery pipeline the direct-execution `POST /api/v1/ci/discovery-runs`
    route uses, via the shared `backend.services.ci_actions.run_discovery` composition."""
    assert ctx.tenant_id is not None
    seller_product = load_seller_product(ctx.tenant_id, body.product_id)
    if seller_product is None:
        raise HTTPException(
            status_code=404,
            detail=f"No SellerProduct for '{body.product_id}' — fill in the seller product profile first.",
        )

    result = ceo_hub.dispatch_ci_discover_competitors(
        ctx.tenant_id,
        requested_by=ctx.app_user_id,
        seller_product=seller_product,
        permission_check="PASS",  # real — require_auth(permission=AGENT_CI) already enforced this
    )
    outcome = result.outcome
    return {
        "ceoAgentRunId": str(result.ceo_agent_run_id),
        "discoveryRunId": str(outcome.discovery_run_id),
        "status": outcome.status,
        "rawCandidateCount": outcome.raw_candidate_count,
        "analyzedCandidateCount": outcome.analyzed_candidate_count,
        "recommendedCandidateIds": [str(c) for c in outcome.recommended_candidate_ids],
        "uncertainCandidateIds": [str(c) for c in outcome.uncertain_candidate_ids],
        "partialReason": outcome.partial_reason,
        "failedReason": outcome.failed_reason,
    }


class RequestPriceScenarioRequest(BaseModel):
    competitor_url_id: UUID
    seller_price_paise: int = Field(gt=0)
    stance: str | None = Field(
        default=None,
        pattern="^(MATCH_LOWEST|BEAT_LOWEST_BY_PCT|BEAT_LOWEST_BY_PAISE|MATCH_AVERAGE|MATCH_HIGHEST)$",
    )
    stance_param_pct: Decimal | None = None
    stance_param_paise: int | None = None


@router.post("/request-price-scenario")
def request_price_scenario(
    body: RequestPriceScenarioRequest, ctx: AuthContext = require_auth(permission=AGENT_CI)
) -> dict[str, object]:
    """Checkpoint 7's third fixed CEO Hub action (`ci.request_price_scenario`) — routes to
    §5.15's engine wiring via the same `backend.services.ci_actions.run_price_scenario`
    composition the direct-execution `POST .../price-scenario` route uses. No arithmetic on
    money happens in this route or in `ceo_hub.py` — everything past input assembly is
    calc-engine's, unchanged from what the direct-execution route already does."""
    assert ctx.tenant_id is not None
    result = ceo_hub.dispatch_ci_request_price_scenario(
        ctx.tenant_id,
        requested_by=ctx.app_user_id,
        competitor_url_id=body.competitor_url_id,
        seller_price_paise=body.seller_price_paise,
        stance=body.stance,
        stance_param_pct=body.stance_param_pct,
        stance_param_paise=body.stance_param_paise,
        permission_check="PASS",  # real — require_auth(permission=AGENT_CI) already enforced this
    )
    if result.outcome is None:
        raise HTTPException(status_code=404, detail="competitor_url not found, not ACTIVE, or not owned by this tenant")

    return {
        "ceoAgentRunId": str(result.ceo_agent_run_id),
        "pricePositioning": result.outcome.price_positioning,
        "repricingScenario": result.outcome.repricing_scenario,
    }


@router.get("/runs/{ceo_agent_run_id}")
def get_run_linkage(ceo_agent_run_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CI)) -> dict[str, object]:
    """Verifies and displays the parent/child `agent_run` linkage (C7) — the CEO's own row
    plus every child row it fanned out to, so the CEO Hub UI can show "CEO -> CI" as a real,
    queryable fact rather than an assumption."""
    assert ctx.tenant_id is not None
    parent = agent_run_repo.get_run(ctx.tenant_id, ceo_agent_run_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="No such agent_run")

    with tenant_scope(ctx.tenant_id) as conn:
        children = conn.execute(
            text(
                "SELECT id, agent_id, trigger_type, trigger_ref, status, started_at, finished_at "
                "FROM agent_run WHERE parent_run_id = :parent_id ORDER BY started_at"
            ),
            {"parent_id": str(ceo_agent_run_id)},
        ).mappings()
        child_rows = [dict(r) for r in children]

    return {
        "parent": {
            "id": str(parent["id"]),
            "agentId": parent["agent_id"],
            "triggerType": parent["trigger_type"],
            "triggerRef": parent["trigger_ref"],
            "parentRunId": str(parent["parent_run_id"]) if parent["parent_run_id"] else None,
            "status": parent["status"],
        },
        "children": [
            {
                "id": str(c["id"]),
                "agentId": c["agent_id"],
                "triggerType": c["trigger_type"],
                "triggerRef": c["trigger_ref"],
                "status": c["status"],
            }
            for c in child_rows
        ],
    }
