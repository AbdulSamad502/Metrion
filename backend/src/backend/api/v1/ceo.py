"""CEO conversation API (B3) — the minimum backend surface that runs the real CEO turn.

    POST /api/v1/ceo/investigations                    start an investigation (an explicit seller action, C6)
    GET  /api/v1/ceo/investigations                    list this tenant's investigations (tenant-wide visibility, D8)
    GET  /api/v1/ceo/investigations/{id}               messages, turns, findings, attached agents
    POST /api/v1/ceo/investigations/{id}/turns         run one CEO turn (classify -> plan -> parallel legs -> compose -> gate)
    GET  /api/v1/ceo/investigations/{id}/findings      findings so far (the polling seam for progressive delivery; SSE is B4)
    POST /api/v1/ceo/investigations/{id}/resolve       RESOLVED with a seller-authored note
    POST /api/v1/ceo/investigations/{id}/archive       ARCHIVED (hides; never a conclusion)
    POST /api/v1/ceo/investigations/{id}/reopen        RESOLVED -> ACTIVE (only from RESOLVED; the seller's note and all history are kept)
    PUT  /api/v1/ceo/investigations/{id}/agents/{code} attach / detach a specialist for FUTURE work (history is never touched)
    GET  /api/v1/ceo/agents/availability               per-agent availability for THIS member (PRESENT / NOT_PERMITTED / NOT_ENTITLED) and how many chat actions it has
    GET  /api/v1/ceo/state/health                      the Hub's health strip: CFO bands + the latest saved P&L, as verified display snapshots (nothing is computed)
    GET  /api/v1/ceo/investigations/{id}/turns/{tid}/flow   "Show flow": the CEO turn row and the child runs it fanned out to (spec 6.27)

A turn may carry an optional `action` (a quick action the seller chose with a deterministic control, spec 6.26 L2): it skips the classifier and
nothing else. Every finding carries a `presentation` display snapshot (spec R7 as amended).

Tenant comes ONLY from the authenticated context (never a request field); every query is tenant-scoped and FORCE-RLS backs it, so another
tenant's investigation id is a plain 404. Permission, attachment and entitlement are enforced per leg by the dispatch choke point, not
here. The old dummy hub (`/api/v1/ceo-hub/*`) is untouched and is not the CEO.
"""

from __future__ import annotations

import json
import queue
from collections.abc import Iterator
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID

import hashlib

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CEO, AGENT_CFO, AGENT_CI, INVESTIGATION_CREATE, INVESTIGATION_VIEW, has_permission
from backend.ceo.approval_gate import plan_required
from backend.ceo import cmo_delegation
from backend.ceo import approval, approval_run, business_state, findings as ceo_findings, memory as agent_memory, orchestrator, summary
from backend.ceo.capabilities import NOT_ENTITLED, compute_capabilities
from backend.ceo.contract import AgentCode
from backend.ceo.periods import PeriodUnresolvable, resolve_period
from backend.ceo.plans import ACTIONS, PLAYBOOKS, SLOT_VOCAB, VIRTUAL_ROUTES
from backend.ceo import playbook_inputs
from backend.ceo.figure_format import format_paise
from backend.ceo.presentation import present_entry
from backend.ceo import event_bus
from backend.ceo.turn_lock import TurnInProgress
from backend.ceo.registry import get_registry
from backend.ceo.runtime import CeoRuntime
from backend import config
from backend.config import MissingConfig
from backend.repositories import agent_run_repo, investigation_plan_repo, investigation_repo as repo
from backend.services import ceo_attachment_analysis, ceo_attachments, ceo_reads, ceo_runtime

router = APIRouter(prefix="/api/v1/ceo")


def get_runtime() -> CeoRuntime:
    """Dependency: the configured CEO runtime. Tests override it; production builds it from configuration."""
    try:
        return ceo_runtime.build_runtime()
    except MissingConfig:
        raise HTTPException(status_code=503, detail={"code": "CEO_NOT_CONFIGURED"}) from None


class StartInvestigationBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class UiActionBody(BaseModel):
    """A quick action chosen with a deterministic UI control. `kind` is one of the executing routes; `key` is a catalog key (BUSINESS_STATE / ACTION /
    PLAYBOOK) and absent for SYNTHESIZE; `slots` may only use the declared slot vocabulary, as short text the backend then resolves deterministically.
    Whether the member may actually run it is decided server-side, per leg, exactly as for a classified message."""

    kind: Literal["BUSINESS_STATE", "ACTION", "PLAYBOOK", "SYNTHESIZE"]
    key: str | None = Field(default=None, max_length=64)
    slots: dict[str, str] = Field(default_factory=dict)
    refs: dict[str, UUID] = Field(default_factory=dict)  # references chosen through a control; each is validated against the caller's own tenant
    # A decision playbook's structured form inputs (spec 6.33). Shape-checked here; money is integer paise and every cost carries an explicit state.
    inputs: dict[str, Any] | None = None

    @field_validator("slots")
    @classmethod
    def _slots_are_declared(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > len(SLOT_VOCAB) or any(k not in SLOT_VOCAB or len(val) > 64 for k, val in v.items()):
            raise ValueError("undeclared or oversized slot")
        return v

    @field_validator("refs")
    @classmethod
    def _refs_are_declared(cls, v: dict[str, UUID]) -> dict[str, UUID]:
        if any(k not in orchestrator.REF_VOCAB for k in v):
            raise ValueError("undeclared reference")
        return v

    @model_validator(mode="after")
    def _key_matches_kind(self) -> "UiActionBody":
        if (self.kind == "SYNTHESIZE") != (self.key is None):
            raise ValueError("a key is required for every kind except SYNTHESIZE, which takes none")
        if self.inputs is not None:
            if self.kind != "PLAYBOOK" or self.key is None or self.key not in PLAYBOOKS or not PLAYBOOKS[self.key].needs_form:
                raise ValueError("form inputs belong only to a decision playbook")
            try:
                playbook_inputs.validate_inputs(self.key, self.inputs)  # shape only: the configured candidate-price bound is applied where the runtime is known
            except playbook_inputs.InvalidInputs as exc:
                raise ValueError("; ".join(exc.problems)) from None
        return self


class ClarificationReplyBody(BaseModel):
    """The seller answering a decision card: the card's message id and the chosen option key (null = the free-text "Other", which is the message text)."""

    id: UUID
    option: str | None = Field(default=None, max_length=96)


class TurnBody(BaseModel):
    message: str = Field(min_length=1, max_length=orchestrator.MAX_MESSAGE_CHARS)
    # Optional quick action: when present the classifier is NOT called (spec 6.26 L2) and `message` is the label shown in the thread.
    action: UiActionBody | None = None
    clarification: ClarificationReplyBody | None = None  # answers a decision card; resumes ITS pending intent with no model call (spec 6.32)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=20)  # files uploaded to this investigation; checked against it and the configured count
    # The CI dashboard's "Ask CEO" on one stored finding (CI spec C33, C46): an id only, never content. The CEO re-reads the finding and its evidence from the database, tenant-scoped; an id that is not this
    # tenant's is simply "not found".
    ci_finding_id: UUID | None = Field(default=None, alias="ciFindingId")
    # An explicit date range chosen with the UI's date picker. Both or neither. When present it is THE period for the turn: the model
    # neither chooses nor withholds it, and the same deterministic resolver validates it (a future or inverted range is a 422).
    period_start: date | None = None
    period_end: date | None = None
    # Optional idempotency identifier: ONE logical submission = one UUID, reused by a retry of the same submission and fresh for a new one (even with identical text). It is scoped to
    # this investigation inside the tenant, never trusted as an identity, and absent = the documented no-key behaviour (a resend is a new turn).
    client_request_id: UUID | None = Field(default=None, alias="clientRequestId")


class AttachBody(BaseModel):
    attached: bool


class ResolveBody(BaseModel):
    resolution_note: str = Field(min_length=1, max_length=2000)


def _jd(value: Any) -> dict[str, Any]:
    """`_j` for a JSON object response (typed so the route's declared return type holds)."""
    out = _j(value)
    assert isinstance(out, dict)
    return out


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


def _also(ctx: AuthContext, key: str) -> None:
    """Spec D8 / §8 rule 2: seeing or continuing an investigation needs `agent.ceo` AND `investigation.view` (starting one: `agent.ceo` AND
    `investigation.create`). `require_auth` checks one key; this is the second, in-handler gate (the `financials.adjust` precedent in the CFO
    routes) so that neither key alone is enough. The failure shape matches `require_auth`'s own 403."""
    assert ctx.role is not None
    if not has_permission(role=ctx.role, permissions=ctx.permissions, key=key):
        raise HTTPException(status_code=403, detail=f"Missing permission: {key}")


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
    _also(ctx, AGENT_CEO)
    return [_j(r) for r in repo.list_investigations(_tenant(ctx), status=status)]


def _require_visible(ctx: AuthContext, investigation_id: UUID) -> dict[str, Any]:
    inv = repo.get_investigation(_tenant(ctx), investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return inv


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, Any]:
    _also(ctx, AGENT_CEO)
    inv = _require_visible(ctx, investigation_id)
    tenant = _tenant(ctx)
    return _jd({
        "investigation": inv, "agents": repo.agent_states(tenant, investigation_id), "messages": repo.list_messages(tenant, investigation_id),
        "turns": [{**t, "outcome": ((t.get("safety_result") or {}).get("billing") or {}).get("outcome")} for t in repo.list_turns(tenant, investigation_id)],
        "findings": repo.list_findings(tenant, investigation_id),
        "plans": [_plan_json(ctx, r, with_events=False) for r in investigation_plan_repo.list_for_investigation(tenant, investigation_id)],
    })


@router.get("/investigations/{investigation_id}/findings")
def get_findings(investigation_id: UUID, turn_id: UUID | None = None, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> list[dict[str, Any]]:
    _also(ctx, AGENT_CEO)
    _require_visible(ctx, investigation_id)
    return [_j(f) for f in repo.list_findings(_tenant(ctx), investigation_id, turn_id=turn_id)]


@router.get("/investigations/{investigation_id}/needs")
def get_needs(investigation_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, Any]:
    """The CEO's follow-up lookups for one investigation (spec agent-needs 9.1 / 13): who asked whom for what and how it ended. No money, no text."""
    from backend.repositories import ceo_need_repo

    _also(ctx, AGENT_CEO)
    _require_visible(ctx, investigation_id)
    rows = ceo_need_repo.list_for_investigation(_tenant(ctx), investigation_id)
    return {"items": [_jd({"id": r["id"], "needKey": r["need_key"], "requesterAgent": r["requester_agent"], "providerKey": r["provider_key"], "status": r["status"],
                           "createdAt": r["created_at"], "turnMessageId": r["turn_message_id"]}) for r in rows]}


@router.post("/investigations/{investigation_id}/turns")
def post_turn(
    investigation_id: UUID, body: TurnBody, background: BackgroundTasks, ctx: AuthContext = require_auth(permission=AGENT_CEO),
    runtime: CeoRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    # No second-key check here on purpose: a member with agent.ceo but without investigation.view is refused INSIDE the turn (`open_turn`),
    # which writes the DENIED audit row (spec AC11) and puts nothing into the investigation. A 403 here would drop that audit row.
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
        ui = (
            orchestrator.UiAction(body.action.kind, body.action.key, dict(body.action.slots), {k: str(v) for k, v in body.action.refs.items()}, body.action.inputs)
            if body.action is not None else None
        )
        reply = orchestrator.ClarificationReply(body.clarification.id, body.clarification.option) if body.clarification is not None else None
        max_files = config.ceo_attachment_max_files()
        if body.attachment_ids and (max_files is None or len(body.attachment_ids) > max_files):
            raise HTTPException(status_code=422, detail={"code": "TOO_MANY_ATTACHMENTS", "max": max_files})
        bus = event_bus.get_bus()
        result = orchestrator.run_turn(
            ctx, runtime, investigation_id, body.message, period=explicit, ui_action=ui, clarification=reply, attachment_ids=tuple(body.attachment_ids),
            sink=bus.sink_for(_tenant(ctx), investigation_id), request_key=str(body.client_request_id) if body.client_request_id is not None else None,
            ci_finding_id=body.ci_finding_id,
        )
        if not result.replayed:
            bus.done(_tenant(ctx), investigation_id, status=result.status)  # only a turn that actually ran ends a stream: a refused (409) or replayed one must not end another's
    except repo.InvestigationNotFound:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"}) from None
    except orchestrator.InvestigationNotActive as exc:
        raise HTTPException(status_code=409, detail={"code": "INVESTIGATION_NOT_ACTIVE", "status": exc.status}) from None
    except TurnInProgress:
        raise HTTPException(status_code=409, detail={"code": "TURN_IN_PROGRESS"}) from None
    except orchestrator.InvalidClarification:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CLARIFICATION"}) from None
    except orchestrator.InvalidAttachments:
        raise HTTPException(status_code=422, detail={"code": "INVALID_ATTACHMENTS"}) from None
    except playbook_inputs.InvalidInputs as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUTS", "problems": exc.problems}) from None
    except orchestrator.InvalidMessage:
        raise HTTPException(status_code=422, detail={"code": "INVALID_MESSAGE"}) from None
    except orchestrator.IdempotencyConflict:
        raise HTTPException(status_code=409, detail={"code": "CLIENT_REQUEST_ID_REUSED"}) from None
    if result.turn_id is not None and result.status != "DENIED" and not result.replayed:  # spec D2: due-ness is checked after the answer is sent, so the seller never waits for it
        background.add_task(summary.regenerate_if_due_locked, _tenant(ctx), investigation_id, runtime)
    return _turn_payload(ctx, runtime, result, "UI_ACTION" if (body.action is not None or body.clarification is not None) else "CLASSIFIER")


def _turn_payload(ctx: AuthContext, runtime: CeoRuntime, result: orchestrator.TurnResult, route_source: str) -> dict[str, Any]:
    """The one response shape of a turn (a chat turn and the execution turn of an approved plan). A PLANNED turn also carries its stored plan."""
    payload = {
        "turnId": result.turn_id, "status": result.status, "route": result.route, "routeKey": result.route_key,
        "routeSource": route_source, "answer": result.answer,
        "choices": result.choices, "clarificationId": str(result.message_id) if result.choices and result.message_id else None,
        "messageId": result.message_id, "compositionMode": result.composition_mode, "clarifyFor": result.clarify_for, "notes": result.notes,
        "findings": result.findings, "timings": result.timings, "outcome": result.outcome, "replayed": result.replayed,
        "events": [{"kind": e.kind, "atMs": e.at_ms, "data": e.data} for e in result.events],
    }
    if result.plan_id is not None and result.turn_id is not None:
        inv = (repo.get_turn(_tenant(ctx), result.turn_id) or {}).get("investigation_id")
        row = investigation_plan_repo.get(_tenant(ctx), inv, result.plan_id) if inv is not None else None
        payload["planId"] = result.plan_id
        payload["plan"] = _plan_json(ctx, row, with_events=False) if row is not None else None
    return _jd(payload)


# ------------------------------------------------------------------------------------------------ approval plans (ceo-approval-workflow.md 6.5)
class ApproveBody(BaseModel):
    """Approval is bound to the plan id (the path) AND the hash the seller was shown. The server recomputes the hash; this value is only compared, never used as content."""

    plan_hash: str = Field(validation_alias=AliasChoices("plan_hash", "planHash"), min_length=1, max_length=200)


class DeclineBody(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


def _plan_json(ctx: AuthContext, row: dict[str, Any], *, with_events: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"], "investigationId": row["investigation_id"], "status": row["status"], "planHash": row["plan_hash"], "plan": row["plan"],
        "createdAt": row["created_at"], "expiresAt": row["expires_at"], "plannedTurnId": row["planned_turn_id"], "executionTurnId": row["execution_turn_id"],
        "requestedBy": row["requested_by"], "viewerIsRequester": row["requested_by"] == ctx.app_user_id,  # the card shows Approve / Decline only to the requester (AC-A17)
        "decidedAt": row["decided_at"], "decisionReason": row["decision_reason"],
    }
    if with_events:
        out["events"] = [
            {"event": e["event"], "fromStatus": e["from_status"], "toStatus": e["to_status"], "actorKind": e["actor_kind"], "occurredAt": e["occurred_at"],
             "reasonCode": e["reason_code"], "metadata": e["metadata"]}
            for e in investigation_plan_repo.events(_tenant(ctx), row["id"])
        ]
    return _jd(out)


def _refused(exc: approval.ApprovalRefused) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, **exc.extra})


@router.get("/investigations/{investigation_id}/plans")
def list_plans(investigation_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW), runtime: CeoRuntime = Depends(get_runtime)) -> dict[str, Any]:
    _also(ctx, AGENT_CEO)
    _require_visible(ctx, investigation_id)
    return {"items": [_plan_json(ctx, r, with_events=True) for r in approval.read_plans(_tenant(ctx), investigation_id, now=runtime.clock())]}


@router.get("/investigations/{investigation_id}/plans/{plan_id}")
def get_plan(investigation_id: UUID, plan_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW), runtime: CeoRuntime = Depends(get_runtime)) -> dict[str, Any]:
    _also(ctx, AGENT_CEO)
    _require_visible(ctx, investigation_id)
    row = approval.read_plan(_tenant(ctx), investigation_id, plan_id, now=runtime.clock())
    if row is None:  # a foreign tenant's plan, another investigation's plan and an unknown id are all the same 404
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _plan_json(ctx, row, with_events=True)


@router.post("/investigations/{investigation_id}/plans/{plan_id}/approve")
def approve_plan(
    investigation_id: UUID, plan_id: UUID, body: ApproveBody, ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    """The ONLY way a plan is approved: an explicit call bound to the plan id and the plan hash, by the person who asked. Typed chat text never reaches this."""
    bus = event_bus.get_bus()
    try:
        outcome = approval_run.approve_plan(ctx, runtime, investigation_id, plan_id, body.plan_hash, sink=bus.sink_for(_tenant(ctx), investigation_id))
    except approval.ApprovalRefused as exc:
        raise _refused(exc) from None
    if outcome.result is None:  # the idempotent replay: the same execution turn, reported as it stands (RUNNING until it finishes); nothing new was started
        return _jd({"replayed": True, "turnId": outcome.turn_id, "status": outcome.turn_status, "plan": _plan_json(ctx, outcome.plan, with_events=False)})
    bus.done(_tenant(ctx), investigation_id, status=outcome.result.status)
    return {**_turn_payload(ctx, runtime, outcome.result, "APPROVAL"), "plan": _plan_json(ctx, outcome.plan, with_events=False)}


@router.post("/investigations/{investigation_id}/plans/{plan_id}/decline")
def decline_plan(
    investigation_id: UUID, plan_id: UUID, body: DeclineBody, ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    """AWAITING_APPROVAL -> DECLINED by the requester. No model call, no CEO unit, nothing run."""
    _also(ctx, INVESTIGATION_VIEW)
    try:
        row = approval.decline_plan(ctx, runtime, investigation_id, plan_id, body.reason, now=runtime.clock())
    except approval.ApprovalRefused as exc:
        raise _refused(exc) from None
    return _plan_json(ctx, row, with_events=False)


_IMAGE_MEDIA = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


@router.get("/investigations/{investigation_id}/attachments/{attachment_id}/image")
def attachment_image(investigation_id: UUID, attachment_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> Response:
    """The seller's own uploaded PICTURE from this conversation, for the listing preview (CMO 3.0 M4). Only a PNG / JPEG / WEBP detected from the content is ever served, with that
    type and `nosniff`; any other file, another conversation's file or another tenant's file is the same 404. Read-only; nothing is generated or changed."""
    _also(ctx, INVESTIGATION_VIEW)
    _require_visible(ctx, investigation_id)
    rows = repo.get_attachment_contents(_tenant(ctx), investigation_id, [attachment_id])
    if len(rows) != 1 or rows[0]["detected_type"] not in _IMAGE_MEDIA:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return Response(content=rows[0]["content"], media_type=_IMAGE_MEDIA[rows[0]["detected_type"]],
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300", "Content-Disposition": "inline"})


@router.post("/investigations/{investigation_id}/attachments", status_code=201)
async def upload_attachment(investigation_id: UUID, file: UploadFile, ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> dict[str, Any]:
    """Store one file the seller attaches to this conversation (spec 6.34). The type is decided from the CONTENT; the name and declared type are never trusted. Limits
    are configuration with no default: unset refuses. The file is stored tenant-scoped and read for bounded, untrusted text; nothing is imported or acted on."""
    _also(ctx, INVESTIGATION_VIEW)
    if _require_visible(ctx, investigation_id)["status"] != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "INVESTIGATION_NOT_ACTIVE"})
    max_bytes, max_files, max_pages = config.ceo_attachment_max_bytes(), config.ceo_attachment_max_files(), config.ceo_attachment_max_pages()
    if max_bytes is None or max_files is None or max_pages is None:
        raise HTTPException(status_code=503, detail={"code": "ATTACHMENTS_NOT_CONFIGURED"})
    data = await file.read(max_bytes + 1)  # never reads more than one byte past the limit into memory
    try:
        kind = ceo_attachments.check(data, max_bytes=max_bytes)
    except ValueError as exc:
        if str(exc) == "too large":
            raise HTTPException(status_code=413, detail={"code": "ATTACHMENT_TOO_LARGE", "maxBytes": max_bytes}) from None
        raise HTTPException(status_code=415, detail={"code": "ATTACHMENT_TYPE_NOT_SUPPORTED", "problem": str(exc)}) from None
    digest = hashlib.sha256(data).hexdigest()
    try:
        existing = repo.find_attachment_by_sha(_tenant(ctx), investigation_id, digest)
    except repo.InvestigationNotFound:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"}) from None
    if existing is not None:  # the same bytes already attached to this conversation: nothing is stored or read a second time
        return {"id": str(existing["id"]), "filename": existing["filename"], "type": existing["detected_type"], "byteSize": existing["byte_size"],
                "status": existing["extraction_status"], "note": existing["extraction_note"], "duplicate": True}
    ex = ceo_attachments.extract(data, kind, max_pages=max_pages)
    try:
        new_id = repo.insert_attachment(
            _tenant(ctx), investigation_id, filename=(file.filename or "file").replace("\\", "/").split("/")[-1], detected_type=kind, content=data,
            sha256=digest, extraction_status=ex.status, extraction_note=ex.note, extracted_text=ex.text, created_by=ctx.app_user_id,
        )
    except repo.InvestigationNotFound:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"}) from None
    return {"id": str(new_id), "filename": file.filename, "type": kind, "byteSize": len(data), "status": ex.status, "note": ex.note,
            "table": ceo_attachment_analysis.upload_summary(data, kind, file.filename or "file")}


@router.post("/investigations/{investigation_id}/resolve")
def resolve(investigation_id: UUID, body: ResolveBody, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, str]:
    _also(ctx, AGENT_CEO)
    _require_visible(ctx, investigation_id)
    try:
        repo.resolve_investigation(_tenant(ctx), investigation_id, resolved_by=ctx.app_user_id, resolution_note=body.resolution_note)
    except (repo.InvalidInvestigationTransition, ValueError):
        raise HTTPException(status_code=409, detail={"code": "CANNOT_RESOLVE"}) from None
    return {"status": "RESOLVED"}


@router.post("/investigations/{investigation_id}/archive")
def archive(investigation_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, str]:
    _also(ctx, AGENT_CEO)
    _require_visible(ctx, investigation_id)
    try:
        repo.archive_investigation(_tenant(ctx), investigation_id)
    except repo.InvalidInvestigationTransition:
        raise HTTPException(status_code=409, detail={"code": "ALREADY_ARCHIVED"}) from None
    return {"status": "ARCHIVED"}


@router.post("/investigations/{investigation_id}/reopen")
def reopen(investigation_id: UUID, ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW)) -> dict[str, str]:
    """Only a RESOLVED investigation can be reopened. An ARCHIVED one is hidden, not concluded, so it answers 409 `NOT_RESOLVED`. Messages,
    turns, findings, provenance and the seller's resolution note are untouched; the earlier conclusion is also written into the thread as a
    SYSTEM_NOTE so it survives a later re-resolve (which overwrites the note columns with the new conclusion)."""
    _also(ctx, AGENT_CEO)
    _require_visible(ctx, investigation_id)
    tenant = _tenant(ctx)
    try:
        note = repo.reopen_resolved_investigation(tenant, investigation_id)
    except repo.InvalidInvestigationTransition:
        raise HTTPException(status_code=409, detail={"code": "NOT_RESOLVED"}) from None
    repo.append_message(tenant, investigation_id, role="SYSTEM", kind="SYSTEM_NOTE", created_by=ctx.app_user_id,
                        content=f"This investigation was reopened. Your earlier conclusion was: {note}")
    return {"status": "ACTIVE"}


SSE_KEEPALIVE_SECONDS = 15  # transport constants, not business thresholds: a comment line keeps proxies from closing an idle stream
SSE_MAX_IDLE_KEEPALIVES = 8  # ~2 minutes with no turn: the stream ends and the client falls back to polling


@router.get("/investigations/{investigation_id}/events")
def stream_turn_events(investigation_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> StreamingResponse:
    """Server-sent progress of the next/current turn in this investigation (spec L11, L8): CLASSIFIED, LEG_STARTED/LEG_FINISHED (with the finding id),
    STATE_READ, ANSWER_READY, then TURN_DONE, after which the stream ends. Open it BEFORE posting the turn. Events carry labels only (route, key, status,
    finding id), never a figure or an answer: the findings and the answer are read through the normal, gated endpoints. The subscription is keyed by
    the caller's OWN tenant, so another tenant's investigation id is a plain 404 and can never receive these events. If no event arrives (a different
    API worker ran the turn, or the proxy buffers), the client keeps polling findings: polling remains the fallback transport."""
    _also(ctx, INVESTIGATION_VIEW)
    _require_visible(ctx, investigation_id)
    tenant = _tenant(ctx)
    bus = event_bus.get_bus()
    q = bus.subscribe(tenant, investigation_id)

    def frames() -> Iterator[str]:
        idle = 0
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    item = q.get(timeout=SSE_KEEPALIVE_SECONDS)
                except queue.Empty:
                    idle += 1
                    if idle >= SSE_MAX_IDLE_KEEPALIVES:
                        return
                    yield ": keepalive\n\n"
                    continue
                idle = 0
                if item is None:
                    return
                yield f"event: {item['kind']}\ndata: {json.dumps(item)}\n\n"
                if item["kind"] == event_bus.DONE:
                    return
        finally:
            bus.unsubscribe(tenant, investigation_id, q)

    return StreamingResponse(frames(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/state/health")
def state_health(ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> dict[str, Any]:
    """The Hub's health strip: CFO's GOOD / WATCH / AT_RISK bands and the latest saved P&L, each as a verified display snapshot. These are Business
    State reads of PERSISTED results: nothing is computed, no composite score and no projection exists (CP1-U1). Per-entry gating is the entry's
    own (agent.cfo + CFO entitlement; a refusal comes back as a status with a plain gap, never a figure). No investigation is involved, so every agent
    counts as attached for this tenant-level strip."""
    _also(ctx, INVESTIGATION_VIEW)
    attached = frozenset(a.value for a in AgentCode)
    now = datetime.now(timezone.utc)
    out = []
    for key in ("BS_HEALTH_BANDS", "BS_PNL_LATEST"):
        entry = business_state.read_entry(ctx, key, attached=attached, now=now)
        out.append({
            "key": entry.key, "status": entry.status.value, "period": entry.period, "asOf": entry.as_of.isoformat() if entry.as_of else None,
            "previewHint": entry.preview_hint, "presentation": present_entry(_tenant(ctx), entry),
        })
    return {"entries": out}


def _form_support_gate(ctx: AuthContext) -> None:
    """The run-forms read the seller's STORED cost inputs, which are CFO data: they need the CEO key, the investigation key and the CFO key (spec 6.33)."""
    _also(ctx, INVESTIGATION_VIEW)
    _also(ctx, AGENT_CFO)


@router.get("/forms/price-impact")
def form_price_impact(sku: str | None = Query(default=None, max_length=120), ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime)) -> dict[str, Any]:
    """What the price-impact run-form needs to offer REAL choices and to show the seller the stored value it will use: tracked competitors, the (marketplace,
    category, fee type) combinations that have a fee reference, the saved cost per unit for the SKU with its effective date, and the configured price bound.
    Reads only; nothing is computed or defaulted."""
    _form_support_gate(ctx)
    tenant, today = _tenant(ctx), runtime.clock().date()
    competitors = (
        [{"id": str(r["id"]), "label": r.get("label")} for r in ceo_reads.list_active_competitors(tenant, limit=50) if r.get("label")]
        if has_permission(role=ctx.role, permissions=ctx.permissions, key=AGENT_CI) else []  # type: ignore[arg-type]
    )
    stored = ceo_reads.stored_cogs(tenant, sku.strip(), today) if sku and sku.strip() else None
    return _jd({
        "competitors": competitors,
        "feeOptions": [{"marketplace": o["marketplace"], "category": o["category"], "feeType": o["fee_type"]} for o in ceo_reads.fee_reference_options(tenant, as_of=today)],
        "storedCost": ({"amountPaise": stored.amount_paise, "formatted": format_paise(stored.amount_paise) if stored.amount_paise is not None else None,
                        "effectiveFrom": stored.effective_from, "reason": stored.reason} if stored is not None else None),
        "maxCandidatePrices": runtime.max_candidate_prices,
    })


@router.get("/memory")
def get_memory(ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> dict[str, Any]:
    """What the agents remember for this business (spec agent-memory.md): the shared profile and each agent's own notes, as the seller gave them. Tenant from the session only."""
    return _jd({"items": agent_memory.list_for_seller(_tenant(ctx))})


@router.post("/memory/{memory_id}/forget")
def forget_memory(memory_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> dict[str, Any]:
    """Forget one remembered item. A foreign, unknown or already-forgotten id is a plain not-found."""
    if not agent_memory.forget(_tenant(ctx), memory_id, ctx.app_user_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"forgotten": str(memory_id)}


@router.get("/findings")
def get_findings(limit: int = Query(default=100, ge=1, le=200), ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime)) -> dict[str, Any]:
    """What the agents have reported (spec agent-needs-and-shared-knowledge.md 6.3): active shared findings with their trust label, limited to the agents this member could
    use directly (permission and entitlement, D6); the rest are only counted. Tenant from the session only."""
    visible = ceo_findings.visible_agents(ctx, runtime.registry, now=runtime.clock())
    return _jd(ceo_findings.list_visible(_tenant(ctx), visible, limit=limit).as_dict())


@router.post("/findings/{finding_id}/forget")
def forget_finding(finding_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime)) -> dict[str, Any]:
    """Forget one finding; its source is not recorded again. A foreign, unknown, already-forgotten or hidden-agent id is a plain not-found."""
    visible = ceo_findings.visible_agents(ctx, runtime.registry, now=runtime.clock())
    if not ceo_findings.forget(_tenant(ctx), finding_id, visible_agents=visible, created_by=ctx.app_user_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"forgotten": str(finding_id)}


@router.get("/forms/new-product")
def form_new_product(sku: str | None = Query(default=None, max_length=120), ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> dict[str, Any]:
    """The stored inputs the new-product run reads, shown so the seller sees exactly what will be used: every active supplier quote at the SKU and the active
    batch budget, each with its id and date (a second active quote or budget makes the engine ask which to use, never pick)."""
    _form_support_gate(ctx)
    tenant = _tenant(ctx)

    def row(r: dict[str, Any]) -> dict[str, Any]:
        v = r["value"] or {}
        text = (f"{v.get('supplier_name')}: {format_paise(v['unit_cost_paise'])} per unit" if isinstance(v.get("unit_cost_paise"), int)
                else f"Budget {format_paise(v['amount_paise'])}" if isinstance(v.get("amount_paise"), int) else "A saved input")
        return {"id": r["id"], "createdAt": r["created_at"], "value": v, "reason": r.get("reason"), "summary": text}  # `summary` is the stored value, formatted by the backend

    quotes = [row(r) for r in ceo_reads.stored_quotes(tenant, sku.strip())] if sku and sku.strip() else []
    return _jd({"quotes": quotes, "budget": [row(r) for r in ceo_reads.stored_budget(tenant)], "budgetTargetRef": str(tenant)})  # the target the budget is saved at (ACCOUNT, tenant)


@router.get("/investigations/{investigation_id}/turns/{turn_id}/flow")
def get_turn_flow(investigation_id: UUID, turn_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CEO)) -> dict[str, Any]:
    """"Show flow" (spec 6.27): how a turn was answered, read from the audit rows only: the CEO turn, whether it used the classifier, and every run it
    fanned out to (agent, action, status, the permission/entitlement verdicts, timing). Tenant-scoped; another tenant's ids are a plain 404."""
    _also(ctx, INVESTIGATION_VIEW)
    _require_visible(ctx, investigation_id)
    tenant = _tenant(ctx)
    turn = repo.get_turn(tenant, turn_id)
    if turn is None or turn["investigation_id"] != investigation_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    anchor = agent_run_repo.get_run(tenant, turn["agent_run_id"])
    children = agent_run_repo.list_children(tenant, turn["agent_run_id"])

    def run(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": r["id"], "agentId": r["agent_id"], "triggerRef": r["trigger_ref"], "status": r["status"], "permissionCheck": r["permission_check"],
            "entitlementCheck": r["entitlement_check"], "startedAt": r["started_at"], "finishedAt": r["finished_at"],
            "reason": r["error_reason"] if r["status"] in ("DENIED", "FAILED") else None,
        }

    return _jd({
        "turnId": turn["id"], "route": turn["route"], "routeKey": turn["route_key"], "routeSource": turn["route_source"], "status": turn["status"],
        "compositionMode": turn["composition_mode"], "timings": turn["stage_timings"], "ceo": run(anchor) if anchor else None,
        "legs": [run(c) for c in children],
    })


@router.get("/agents/availability")
def agent_availability(ctx: AuthContext = require_auth(permission=INVESTIGATION_VIEW), runtime: CeoRuntime = Depends(get_runtime)) -> dict[str, Any]:
    """What this member can use right now, independent of any investigation: `status` is PRESENT, NOT_PERMITTED or NOT_ENTITLED (the
    UI shows the last two as locked, never as attached); `chatActions` is how many of the agent's actions the CEO can run from chat today: an approval-required action (decision D-8) is refused from chat until a stored approval plan exists, so it is NOT counted, except the CMO actions, which the CEO takes to a plan card."""
    _also(ctx, AGENT_CEO)
    caps = compute_capabilities(ctx, runtime.registry, frozenset(a.value for a in AgentCode), now=runtime.clock())
    reg = get_registry()
    # The GST lookup is one action to the model; it is counted under the agent of its first route (CFO's Route A). Route B (no agent) stays available to a
    # member without CFO, but it is not an action of any specialist.
    chat_actions = {a.value: sum(1 for k in ACTIONS if (not plan_required([k]) or k in cmo_delegation.DELEGATED_ACTIONS) and reg.get(VIRTUAL_ROUTES.get(k, (k,))[0]).agent is a) for a in AgentCode}
    return {code: {"status": status, "chatActions": chat_actions.get(code, 0)} for code, status in caps.agent_status.items()}


@router.put("/investigations/{investigation_id}/agents/{agent_code}")
def set_agent(
    investigation_id: UUID, agent_code: str, body: AttachBody, ctx: AuthContext = require_auth(permission=AGENT_CEO), runtime: CeoRuntime = Depends(get_runtime)
) -> dict[str, Any]:
    """Attach or detach one specialist for FUTURE work (spec §6.22, R13). Attachment only ever narrows: it grants nothing, an agent the tenant
    is not entitled to cannot be attached, and detaching never touches earlier findings. A change writes a SYSTEM_NOTE into the thread."""
    _also(ctx, INVESTIGATION_VIEW)
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
