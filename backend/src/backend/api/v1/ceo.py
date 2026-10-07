"""CEO conversation API (B3) — the minimum backend surface that runs the real CEO turn.

    POST /api/v1/ceo/investigations                    start an investigation (an explicit seller action, C6)
    GET  /api/v1/ceo/investigations                    list this tenant's investigations (tenant-wide visibility, D8)
    GET  /api/v1/ceo/investigations/{id}               messages, turns, findings, attached agents
    POST /api/v1/ceo/investigations/{id}/turns         run one CEO turn (classify -> plan -> parallel legs -> compose -> gate)
    GET  /api/v1/ceo/investigations/{id}/findings      findings so far (the polling seam for progressive delivery; SSE is B4)
    POST /api/v1/ceo/investigations/{id}/resolve       RESOLVED with a seller-authored note

Tenant comes ONLY from the authenticated context (never a request field); every query is tenant-scoped and FORCE-RLS backs it, so another
tenant's investigation id is a plain 404. Permission, attachment and entitlement are enforced per leg by the dispatch choke point, not
here. The old dummy hub (`/api/v1/ceo-hub/*`) is untouched and is not the CEO.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_CREATE, INVESTIGATION_VIEW
from backend.ceo import orchestrator
from backend.ceo.runtime import CeoRuntime
from backend.config import MissingConfig
from backend.repositories import investigation_repo as repo
from backend.services import ceo_runtime

router = APIRouter(prefix="/api/v1/ceo")


def get_runtime() -> CeoRuntime:
    """Dependency: the configured CEO runtime. Tests override it; production builds it from configuration."""
    try:
        return ceo_runtime.build_runtime()
    except MissingConfig:
        raise HTTPException(status_code=503, detail={"code": "CEO_NOT_CONFIGURED"}) from None


class StartInvestigationBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class TurnBody(BaseModel):
    message: str = Field(min_length=1, max_length=orchestrator.MAX_MESSAGE_CHARS)


class ResolveBody(BaseModel):
    resolution_note: str = Field(min_length=1, max_length=2000)


def _j(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _j(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_j(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _tenant(ctx: AuthContext) -> UUID:
    assert ctx.tenant_id is not None  # require_auth fails closed without a tenant
    return ctx.tenant_id


@router.post("/investigations", status_code=201)
def start_investigation(
    body: StartInvestigationBody, ctx: AuthContext = require_auth(permission=INVESTIGATION_CREATE), runtime: CeoRuntime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        inv = orchestrator.start_investigation(ctx, runtime, title=body.title)
    except PermissionError:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN"}) from None
    return {"investigationId": str(inv)}


@router.get("/investigations")
def list_investigations(status: str | None = None, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> list[dict[str, Any]]:
    return [_j(r) for r in repo.list_investigations(_tenant(ctx), status=status)]


def _require_visible(ctx: AuthContext, investigation_id: UUID) -> dict[str, Any]:
    inv = repo.get_investigation(_tenant(ctx), investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return inv


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, Any]:
    inv = _require_visible(ctx, investigation_id)
    tenant = _tenant(ctx)
    return _j({
        "investigation": inv, "agents": repo.agent_states(tenant, investigation_id), "messages": repo.list_messages(tenant, investigation_id),
        "turns": repo.list_turns(tenant, investigation_id), "findings": repo.list_findings(tenant, investigation_id),
    })


@router.get("/investigations/{investigation_id}/findings")
def get_findings(investigation_id: UUID, turn_id: UUID | None = None, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> list[dict[str, Any]]:
    _require_visible(ctx, investigation_id)
    return [_j(f) for f in repo.list_findings(_tenant(ctx), investigation_id, turn_id=turn_id)]


@router.post("/investigations/{investigation_id}/turns")
def post_turn(
    investigation_id: UUID, body: TurnBody, ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime)
) -> dict[str, Any]:
    try:
        result = orchestrator.run_turn(ctx, runtime, investigation_id, body.message)
    except repo.InvestigationNotFound:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"}) from None
    except orchestrator.InvestigationNotActive as exc:
        raise HTTPException(status_code=409, detail={"code": "INVESTIGATION_NOT_ACTIVE", "status": exc.status}) from None
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "INVALID_MESSAGE"}) from None
    return _j({
        "turnId": result.turn_id, "status": result.status, "route": result.route, "routeKey": result.route_key, "answer": result.answer,
        "messageId": result.message_id, "compositionMode": result.composition_mode, "clarifyFor": result.clarify_for, "notes": result.notes,
        "findings": result.findings, "timings": result.timings,
        "events": [{"kind": e.kind, "atMs": e.at_ms, "data": e.data} for e in result.events],
    })


@router.post("/investigations/{investigation_id}/resolve")
def resolve(investigation_id: UUID, body: ResolveBody, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, str]:
    _require_visible(ctx, investigation_id)
    try:
        repo.resolve_investigation(_tenant(ctx), investigation_id, resolved_by=ctx.app_user_id, resolution_note=body.resolution_note)
    except (repo.InvalidInvestigationTransition, ValueError):
        raise HTTPException(status_code=409, detail={"code": "CANNOT_RESOLVE"}) from None
    return {"status": "RESOLVED"}
