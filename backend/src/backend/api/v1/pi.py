"""PI's direct-execution routes — Phase 2 of the PI build plan's §3, scoped exactly as its
own "Phase 2 (deferred until Phase 1 is approved)" section states: **plain HTTP routes only**
(`pi.discover`/`pi.supplier_lookup`/`pi.report`, plus `niche_brief` CRUD), permission/
entitlement resolution, and `services/pi_actions.py`. **CEO Hub wiring stays explicitly out of
scope** — no `PI_*` constant and no `dispatch_pi_*` function exists in `agents/ceo_hub.py`,
and this file never imports from it. The CFO batch-size handoff and `final_recommendation`
composition (which route through CEO's orchestration) stay deferred with it.

`niche_brief` CRUD (§6.1) is plain authenticated tenant-write — `require_auth()` with no
`agent.*` permission key, since authoring a brief invokes no agent (mirrors this file's own
`pi.discover`/`pi.supplier_lookup`/`pi.report` routes in every OTHER respect, but not this
one). `POST /pi/discover` replicates `api/v1/cfo.py`'s `post_gst_lookup` two-key shape exactly:
`require_auth(permission=AGENT_PI)` as the route dependency, plus an in-handler `has_permission`
check for `RESEARCH_NICHE_RUN`, resolving BOTH `resolve_pi_entitlement` and
`resolve_niche_run_entitlement` — `402` if either denies, `403` if either permission is
missing. `pi.supplier_lookup`/`pi.report` use the single-`AGENT_PI`-key pattern most of
`api/v1/ci.py`'s routes already use — `pi.report`'s own plan table row (§6.8) marks its
entitlement column "None", so it resolves no entitlement at all, matching `GET /ci/summary`'s
own "read-only, no entitlement gate" precedent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from product_intelligence.discovery.discovery_run import DEFAULT_CANDIDATE_CAP

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_PI, RESEARCH_NICHE_RUN, has_permission
from backend.entitlement import resolve_niche_run_entitlement, resolve_pi_entitlement
from backend.repositories import agent_run_repo
from backend.services.pi_actions import (
    archive_niche_brief,
    create_niche_brief_draft,
    get_niche_brief,
    list_niche_briefs,
    load_report,
    mark_niche_brief_draft,
    mark_niche_brief_ready,
    pi_report_to_dict,
    pi_run_result_to_dict,
    run_discovery,
    run_supplier_lookup,
    supplier_lookup_result_to_dict,
    update_niche_brief_draft,
)

router = APIRouter(prefix="/api/v1/pi")

PI_DISCOVER = "pi.discover"
PI_SUPPLIER_LOOKUP = "pi.supplier_lookup"


def _require_pi_entitlement(tenant_id: UUID, *, direct_action_code: str) -> None:
    """Same `402` shape `api/v1/cfo.py`'s `_require_cfo_entitlement` already establishes —
    `resolve_pi_entitlement` is a thin wrapper over the identical F2 mechanism, so this stays
    a thin wrapper too, not a reimplementation."""
    result = resolve_pi_entitlement(tenant_id, direct_action_code=direct_action_code)
    if result.passed:
        return
    raise HTTPException(
        status_code=402,
        detail={
            "reason": result.reason,
            "meterCode": result.meter_code,
            "evaluationBasis": result.evaluation_basis,
        },
    )


def _require_niche_run_entitlement(tenant_id: UUID) -> None:
    result = resolve_niche_run_entitlement(tenant_id)
    if result.passed:
        return
    raise HTTPException(
        status_code=402,
        detail={"reason": result.reason, "service": "research.niche_run", "nicheRunCount": result.niche_run_count},
    )


# --- niche_brief CRUD (§6.1, plain tenant-write, no agent.* key) ---------------------------


class CreateNicheBriefRequest(BaseModel):
    category_text: str | None = None
    budget_paise: int | None = None
    target_price_min_paise: int | None = None
    target_price_max_paise: int | None = None
    marketplaces: list[str] | None = None
    constraints: dict[str, Any] | None = None


@router.post("/niche-briefs")
def post_niche_brief(body: CreateNicheBriefRequest, ctx: AuthContext = require_auth()) -> dict[str, str]:
    assert ctx.tenant_id is not None
    brief_id = create_niche_brief_draft(
        ctx.tenant_id,
        created_by=ctx.app_user_id,
        category_text=body.category_text,
        budget_paise=body.budget_paise,
        target_price_min_paise=body.target_price_min_paise,
        target_price_max_paise=body.target_price_max_paise,
        marketplaces=body.marketplaces,
        constraints=body.constraints,
    )
    return {"nicheBriefId": str(brief_id)}


@router.get("/niche-briefs/{brief_id}")
def get_niche_brief_route(brief_id: UUID, ctx: AuthContext = require_auth()) -> dict[str, Any]:
    assert ctx.tenant_id is not None
    brief = get_niche_brief(ctx.tenant_id, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="niche_brief not found")
    return brief


@router.get("/niche-briefs")
def list_niche_briefs_route(status: str | None = None, ctx: AuthContext = require_auth()) -> list[dict[str, Any]]:
    assert ctx.tenant_id is not None
    return list_niche_briefs(ctx.tenant_id, status=status)


class UpdateNicheBriefRequest(BaseModel):
    category_text: str | None = None
    budget_paise: int | None = None
    target_price_min_paise: int | None = None
    target_price_max_paise: int | None = None
    marketplaces: list[str] | None = None
    constraints: dict[str, Any] | None = None


@router.put("/niche-briefs/{brief_id}")
def put_niche_brief(brief_id: UUID, body: UpdateNicheBriefRequest, ctx: AuthContext = require_auth()) -> dict[str, str]:
    assert ctx.tenant_id is not None
    try:
        update_niche_brief_draft(
            ctx.tenant_id,
            brief_id,
            category_text=body.category_text,
            budget_paise=body.budget_paise,
            target_price_min_paise=body.target_price_min_paise,
            target_price_max_paise=body.target_price_max_paise,
            marketplaces=body.marketplaces,
            constraints=body.constraints,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"nicheBriefId": str(brief_id)}


@router.post("/niche-briefs/{brief_id}/mark-ready")
def post_mark_niche_brief_ready(brief_id: UUID, ctx: AuthContext = require_auth()) -> dict[str, str]:
    assert ctx.tenant_id is not None
    try:
        mark_niche_brief_ready(ctx.tenant_id, brief_id, readied_at=datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"nicheBriefId": str(brief_id), "status": "READY"}


@router.post("/niche-briefs/{brief_id}/mark-draft")
def post_mark_niche_brief_draft(brief_id: UUID, ctx: AuthContext = require_auth()) -> dict[str, str]:
    assert ctx.tenant_id is not None
    try:
        mark_niche_brief_draft(ctx.tenant_id, brief_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"nicheBriefId": str(brief_id), "status": "DRAFT"}


@router.post("/niche-briefs/{brief_id}/archive")
def post_archive_niche_brief(brief_id: UUID, ctx: AuthContext = require_auth()) -> dict[str, str]:
    assert ctx.tenant_id is not None
    try:
        archive_niche_brief(ctx.tenant_id, brief_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"nicheBriefId": str(brief_id), "status": "ARCHIVED"}


# --- pi.discover (two-key: agent.pi + research.niche_run) ----------------------------------


class DiscoverRequest(BaseModel):
    niche_brief_id: UUID
    depth: str = Field(pattern="^(SHALLOW|COMPLETE)$")
    candidate_cap: int | None = None


@router.post("/discover")
def post_discover(body: DiscoverRequest, ctx: AuthContext = require_auth(permission=AGENT_PI)) -> dict[str, object]:
    """Direct-execution path (PI build plan §3, `pi.discover`) for `services.pi_actions.
    run_discovery` — replicates `api/v1/cfo.py`'s `post_gst_lookup` two-gate shape exactly
    (see module docstring). `trigger_type="DIRECT"`, no `parent_run_id` — there is no CEO run
    wrapping this call in Phase 2 (CEO Hub wiring stays deferred)."""
    assert ctx.tenant_id is not None

    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=RESEARCH_NICHE_RUN):
        raise HTTPException(status_code=403, detail="research.niche_run permission required")

    _require_pi_entitlement(ctx.tenant_id, direct_action_code=PI_DISCOVER)
    _require_niche_run_entitlement(ctx.tenant_id)

    now = datetime.now(timezone.utc)
    agent_run_id = agent_run_repo.insert_run(
        ctx.tenant_id,
        agent_id="PI",
        trigger_type="DIRECT",
        trigger_ref=PI_DISCOVER,
        requested_by=ctx.app_user_id,
        permission_check="PASS",
        entitlement_check="PASS",
        status="RUNNING",
        started_at=now,
    )

    try:
        result = run_discovery(
            ctx.tenant_id,
            body.niche_brief_id,
            body.depth,
            requested_by=ctx.app_user_id,
            permission_check="PASS",
            entitlement_check="PASS",
            candidate_cap=body.candidate_cap if body.candidate_cap is not None else DEFAULT_CANDIDATE_CAP,
        )
    except Exception as exc:  # noqa: BLE001 — the agent_run row must reflect a real failure,
        # never be left RUNNING forever; the exception is then re-raised unchanged.
        agent_run_repo.finish_run(
            ctx.tenant_id, agent_run_id, status="FAILED", error_reason=str(exc), finished_at=datetime.now(timezone.utc)
        )
        raise

    agent_run_repo.finish_run(
        ctx.tenant_id,
        agent_run_id,
        status=result.status,
        error_reason=result.failed_reason,
        finished_at=datetime.now(timezone.utc),
    )

    response = pi_run_result_to_dict(result)
    response["agentRunId"] = str(agent_run_id)
    return response


# --- pi.supplier_lookup (single agent.pi key) -----------------------------------------------


class SupplierLookupRequest(BaseModel):
    run_id: UUID
    candidate_ids: list[UUID] = Field(min_length=1, max_length=5)


@router.post("/supplier-lookup")
def post_supplier_lookup(
    body: SupplierLookupRequest, ctx: AuthContext = require_auth(permission=AGENT_PI)
) -> dict[str, object]:
    """`pi.supplier_lookup` — single `agent.pi` key, matching most of `api/v1/ci.py`'s own
    routes. `candidate_ids` is capped at 5 here at the HTTP boundary, matching `pi_supplier_
    lookup.py`'s own "seller's chosen top-5 (or fewer)" contract."""
    assert ctx.tenant_id is not None
    _require_pi_entitlement(ctx.tenant_id, direct_action_code=PI_SUPPLIER_LOOKUP)

    now = datetime.now(timezone.utc)
    agent_run_id = agent_run_repo.insert_run(
        ctx.tenant_id,
        agent_id="PI",
        trigger_type="DIRECT",
        trigger_ref=PI_SUPPLIER_LOOKUP,
        requested_by=ctx.app_user_id,
        permission_check="PASS",
        entitlement_check="PASS",
        status="RUNNING",
        started_at=now,
    )

    try:
        results = run_supplier_lookup(ctx.tenant_id, run_id=body.run_id, candidate_ids=body.candidate_ids)
    except Exception as exc:  # noqa: BLE001 — see post_discover's identical rationale
        agent_run_repo.finish_run(
            ctx.tenant_id, agent_run_id, status="FAILED", error_reason=str(exc), finished_at=datetime.now(timezone.utc)
        )
        raise

    any_degraded = any(r.degraded_reason is not None for r in results)
    agent_run_repo.finish_run(
        ctx.tenant_id,
        agent_run_id,
        status="PARTIAL" if any_degraded else "COMPLETE",
        error_reason=None,
        finished_at=datetime.now(timezone.utc),
    )

    return {
        "agentRunId": str(agent_run_id),
        "results": [supplier_lookup_result_to_dict(r) for r in results],
    }


# --- pi.report (single agent.pi key, no entitlement gate per §6.8) -------------------------


@router.get("/report/{run_id}")
def get_report(run_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_PI)) -> dict[str, object]:
    """`pi.report` — re-renders an already-completed run from persisted data only, no new
    fetch. §6.8's own table marks this trigger's entitlement column "None" (matching `GET
    /ci/summary`'s "read-only, no entitlement gate" precedent), so this route resolves no
    entitlement at all."""
    assert ctx.tenant_id is not None
    try:
        report = load_report(ctx.tenant_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return pi_report_to_dict(report)
