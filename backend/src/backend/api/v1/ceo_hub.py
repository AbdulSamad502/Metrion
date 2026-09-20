"""The CEO Hub's own API surface — Step 4's dummy CEO. See `backend/agents/ceo_hub.py` for
what "dummy" means here: one hardcoded action, no LLM, no conversational routing.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from backend.agents import ceo_hub
from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CI
from backend.repositories import agent_run_repo
from backend.tenant_context import tenant_scope
from competitor_intelligence.evidence.extraction import UnimplementedVisionExtractor

router = APIRouter(prefix="/api/v1/ceo-hub")

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
            extractor=UnimplementedVisionExtractor(),
        )
    except NotImplementedError as exc:
        # No real vision model exists yet (spec §1a item 4 / Q7) — this is the honest,
        # expected outcome of submitting image_refs today. Submitting manual_fields only
        # (image_refs=[]) never reaches the extractor at all and works end-to-end.
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
