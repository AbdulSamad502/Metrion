"""CEO conversation API (B3) — the minimum backend surface that runs the real CEO turn.

    POST /api/v1/ceo/investigations                    start an investigation (an explicit seller action, C6)
    GET  /api/v1/ceo/investigations                    list this tenant's investigations (tenant-wide visibility, D8)
    GET  /api/v1/ceo/investigations/{id}               messages, turns, findings, attached agents
    POST /api/v1/ceo/investigations/{id}/turns         run one CEO turn (classify -> plan -> parallel legs -> compose -> gate)
    GET  /api/v1/ceo/investigations/{id}/findings      findings so far (the polling seam for progressive delivery; SSE is B4)
    POST /api/v1/ceo/investigations/{id}/resolve       RESOLVED with a seller-authored note
    POST /api/v1/ceo/investigations/{id}/archive       ARCHIVED (hides; never a conclusion)
    PUT  /api/v1/ceo/investigations/{id}/agents/{code} attach / detach a specialist for FUTURE work (history is never touched)
    GET  /api/v1/ceo/agents/availability               per-agent availability for THIS member (PRESENT / NOT_PERMITTED / NOT_ENTITLED) and how many chat actions it has

Tenant comes ONLY from the authenticated context (never a request field); every query is tenant-scoped and FORCE-RLS backs it, so another
tenant's investigation id is a plain 404. Permission, attachment and entitlement are enforced per leg by the dispatch choke point, not
here. The old dummy hub (`/api/v1/ceo-hub/*`) is untouched and is not the CEO.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_CREATE, INVESTIGATION_VIEW
from backend.ceo import orchestrator
from backend.ceo.capabilities import NOT_ENTITLED, compute_capabilities
from backend.ceo.contract import AgentCode
from backend.ceo.periods import PeriodUnresolvable, resolve_period
from backend.ceo.plans import ACTIONS
from backend.ceo.registry import get_registry
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
    # An explicit date range chosen with the UI's date picker. Both or neither. When present it is THE period for the turn: the model
    # neither chooses nor withholds it, and the same deterministic resolver validates it (a future or inverted range is a 422).
    period_start: date | None = None
    period_end: date | None = None


class AttachBody(BaseModel):
    attached: bool


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
    explicit: tuple[date, date] | None = None
    if (body.period_start is None) != (body.period_end is None):
        raise HTTPException(status_code=422, detail={"code": "INVALID_PERIOD"})
    if body.period_start is not None and body.period_end is not None:
        try:
            resolve_period(f"{body.period_start.isoformat()} to {body.period_end.isoformat()}", today=runtime.clock().date())
        except PeriodUnresolvable:
            raise HTTPException(status_code=422, detail={"code": "INVALID_PERIOD"}) from None
        explicit = (body.period_start, body.period_end)
    try:
        result = orchestrator.run_turn(ctx, runtime, investigation_id, body.message, period=explicit)
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


@router.post("/investigations/{investigation_id}/archive")
def archive(investigation_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, str]:
    _require_visible(ctx, investigation_id)
    try:
        repo.archive_investigation(_tenant(ctx), investigation_id)
    except repo.InvalidInvestigationTransition:
        raise HTTPException(status_code=409, detail={"code": "ALREADY_ARCHIVED"}) from None
    return {"status": "ARCHIVED"}


@router.get("/agents/availability")
def agent_availability(ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW), runtime: CeoRuntime = Depends(get_runtime)) -> dict[str, Any]:
    """What this member can use right now, independent of any investigation: `status` is PRESENT, NOT_PERMITTED or NOT_ENTITLED (the
    UI shows the last two as locked, never as attached); `chatActions` is how many of the agent's actions the CEO can run from chat today."""
    caps = compute_capabilities(ctx, runtime.registry, frozenset(a.value for a in AgentCode), now=runtime.clock())
    reg = get_registry()
    chat_actions = {a.value: sum(1 for k in ACTIONS if reg.get(k).agent is a) for a in AgentCode}
    return {code: {"status": status, "chatActions": chat_actions.get(code, 0)} for code, status in caps.agent_status.items()}


@router.put("/investigations/{investigation_id}/agents/{agent_code}")
def set_agent(
    investigation_id: UUID, agent_code: str, body: AttachBody, ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime)
) -> dict[str, Any]:
    """Attach or detach one specialist for FUTURE work (spec §6.22, R13). Attachment only ever narrows: it grants nothing, an agent the tenant
    is not entitled to cannot be attached, and detaching never touches earlier findings. A change writes a SYSTEM_NOTE into the thread."""
    code = agent_code.upper()
    if code not in repo.ATTACHABLE_AGENT_CODES:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    inv = _require_visible(ctx, investigation_id)
    if inv["status"] != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "INVESTIGATION_NOT_ACTIVE", "status": inv["status"]})
    tenant = _tenant(ctx)
    current = repo.agent_states(tenant, investigation_id).get(code, False)
    if body.attached and not current:
        caps = compute_capabilities(ctx, runtime.registry, frozenset(a.value for a in AgentCode), now=runtime.clock())
        if caps.agent_status.get(code) == NOT_ENTITLED:
            raise HTTPException(status_code=409, detail={"code": "AGENT_NOT_ENTITLED"})  # cannot attach what the tenant is not entitled to
    if body.attached != current:
        repo.set_agent_attachment(tenant, investigation_id, code, attached=body.attached, changed_by=ctx.app_user_id, now=runtime.clock())
        note = (f"{code} was attached to this investigation." if body.attached
                else f"{code} was detached from this investigation. Its earlier findings remain as historical evidence; it will not be used for new work.")
        repo.append_message(tenant, investigation_id, role="SYSTEM", kind="SYSTEM_NOTE", content=note, created_by=ctx.app_user_id, now=runtime.clock())
    return {"agent": code, "attached": body.attached}
