"""The single dispatch choke point — spec §6.15 R1, R2, R5, R6, R8, R13, R14.

Every specialist or shared-service call the CEO makes goes through `dispatch()`. There is no other path.

* **R1 — real context.** `open_turn`/`dispatch` take the authenticated `AuthContext` produced by `require_auth`.
  They accept no `role`, `permissions`, `tenant_id` or `permission_check` argument, and never construct an
  `AuthContext`. The tenant comes from `ctx.tenant_id` only (fail closed when absent).
* **R2 — full chain per leg.** `agent.ceo` + the agent's own key + the registry extras, then attachment (R13), then the
  owning entitlement resolver, THEN the call. A CEO-selected action can still be denied by its own chain (C8).
* **R5 — one `agent_run` per leg**, a child of the CEO turn row. Where the specialist writes its own row (CMO, PI), the
  choke point writes none for a successful call and the specialist's row inherits the parent through
  `agent_run_repo.parent_run_scope`; where it writes none (CFO, CI price scenario) the choke point writes it. A refused
  leg is always written by the choke point, with the same fidelity as a completed one.
* **R6 — uniform verdicts.** A permission, attachment OR entitlement refusal is `agent_run.status = DENIED` with the
  failing key/meter named (the old hub wrote entitlement refusals as FAILED).
* **R12 — no leakage.** An unexpected handler failure is logged server-side and surfaced as a generic reason.

This module computes nothing and calls no model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_VIEW, has_permission
from backend.ceo import provenance
from backend.ceo.approval_gate import gate_leg
from backend.ceo.contract import (
    ActionSpec,
    ApprovalGrant,
    Denial,
    InvalidSlots,
    LegContext,
    LegResult,
    LegStatus,
    Ref,
    TurnDenied,
)
from backend.ceo.registry import ActionRegistry, get_registry
from backend.entitlement import CEO_TURN_EVENT_KIND, resolve_ceo_entitlement
from backend.repositories import agent_run_repo, investigation_repo

logger = logging.getLogger(__name__)

# Slot names that must never be accepted from a caller, whatever a model declares (spec §6.11, R14).
_RESERVED_SLOT_NAMES = frozenset({"tenant_id", "tenantid", "role", "permissions", "permission_check", "entitlement_check", "requested_by"})

_PARTIAL_KEYS = ("dataRequestId", "partialReason")


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _entitlement_text(result: Any) -> str:
    basis = getattr(result, "evaluation_basis", None)
    if not result.passed:
        return f"DENIED:{getattr(result, 'meter_code', None) or 'entitlement'}"
    return "NO_CAP_CONFIGURED" if basis == "NO_CAP_CONFIGURED" else "PASS"


@dataclass(slots=True)
class CeoTurn:
    """The open CEO turn: its anchor `agent_run` and the identifiers every leg needs. `turn_id` is the
    `investigation_turn` row when the caller (B3/B4) created one; legs then also write findings."""

    ctx: AuthContext
    anchor_run_id: UUID
    started_at: datetime
    trigger_type: str
    investigation_id: UUID | None = None
    turn_id: UUID | None = None
    legs: list[LegResult] = field(default_factory=list)
    # Builds the finding's display snapshot from the (tentative) leg — set by the orchestrator; None for callers that do not present (spec R7 amended).
    presenter: Callable[[LegResult], Mapping[str, Any] | None] | None = None
    _closed: bool = False

    @property
    def tenant_id(self) -> UUID:
        assert self.ctx.tenant_id is not None
        return self.ctx.tenant_id

    def close(self, *, status: str, error_reason: str | None = None, now: datetime | None = None) -> None:
        """Finishes the anchor row. The turn's status is derived from its legs unless stated: all COMPLETE -> COMPLETE,
        any refusal/failure with at least one success -> PARTIAL, nothing succeeded -> the given status."""
        if self._closed:
            return
        self._closed = True
        refs = [r.to_json() for leg in self.legs for r in leg.figure_refs]
        agent_run_repo.finish_run(
            self.tenant_id, self.anchor_run_id, status=status, error_reason=error_reason, finished_at=_now(now),
            output_refs=refs if refs else None,
        )

    def derive_status(self) -> str:
        if not self.legs:
            return "COMPLETE"
        ok = [leg for leg in self.legs if leg.status in (LegStatus.COMPLETE, LegStatus.PARTIAL)]
        if len(ok) == len(self.legs) and all(leg.status is LegStatus.COMPLETE for leg in self.legs):
            return "COMPLETE"
        if ok:
            return "PARTIAL"
        return "DENIED" if all(leg.status in (LegStatus.DENIED, LegStatus.NOT_ENTITLED) for leg in self.legs) else "FAILED"


def open_turn(
    ctx: AuthContext,
    *,
    investigation_id: UUID | None = None,
    trigger_ref: str = "ceo.chat_turn",
    trigger_type: str = "CONVERSATIONAL",
    now: datetime | None = None,
) -> CeoTurn:
    """Opens a CEO turn: checks `agent.ceo` (+ `investigation.view` when attached to an investigation) and the CEO's own
    cap BEFORE anything else (spec §8 rule 3, E7), and writes the anchor `agent_run`. Raises `TurnDenied` (after writing
    a DENIED anchor row) when the turn itself is refused — no specialist is even considered."""
    if ctx.tenant_id is None or ctx.role is None:
        raise ValueError("a CEO turn needs an authenticated tenant context (fail closed)")
    if trigger_type not in ("CONVERSATIONAL", "SYSTEM"):
        raise ValueError("a CEO turn is CONVERSATIONAL or SYSTEM; DIRECT rows never attach to a CEO turn")
    at = _now(now)
    tenant_id = ctx.tenant_id

    needed = (AGENT_CEO, INVESTIGATION_VIEW) if investigation_id is not None else (AGENT_CEO,)
    missing = [k for k in needed if not has_permission(role=ctx.role, permissions=ctx.permissions, key=k)]
    if missing:
        run = agent_run_repo.insert_run(
            tenant_id, agent_id="CEO", trigger_type=trigger_type, trigger_ref=trigger_ref, requested_by=ctx.app_user_id,
            permission_check=f"DENIED:{missing[0]}", entitlement_check="NOT_EVALUATED", status="DENIED",
            started_at=at, finished_at=at, error_reason=f"missing: {', '.join(missing)}",
            investigation_id=investigation_id, inherit_parent=False,
        )
        raise TurnDenied(f"missing permission(s): {', '.join(missing)}", run, kind=Denial.PERMISSION)

    if trigger_type == "CONVERSATIONAL":  # system runs consume no seller conversation unit (CP1-D5)
        cap = resolve_ceo_entitlement(tenant_id, occurred_at=at)
        if not cap.passed:
            run = agent_run_repo.insert_run(
                tenant_id, agent_id="CEO", trigger_type=trigger_type, trigger_ref=trigger_ref, requested_by=ctx.app_user_id,
                permission_check="PASS", entitlement_check=_entitlement_text(cap), status="DENIED", started_at=at,
                finished_at=at, error_reason=f"CEO cap exhausted ({CEO_TURN_EVENT_KIND})", investigation_id=investigation_id,
                inherit_parent=False,
            )
            raise TurnDenied("CEO turn cap reached", run, kind=Denial.ENTITLEMENT)
        ent_text = _entitlement_text(cap)
    else:
        ent_text = "NOT_APPLICABLE"

    run = agent_run_repo.insert_run(
        tenant_id, agent_id="CEO", trigger_type=trigger_type, trigger_ref=trigger_ref, requested_by=ctx.app_user_id,
        permission_check="PASS", entitlement_check=ent_text, status="RUNNING", started_at=at,
        investigation_id=investigation_id, inherit_parent=False,
    )
    return CeoTurn(ctx=ctx, anchor_run_id=run, started_at=at, trigger_type=trigger_type, investigation_id=investigation_id)


# ---------------------------------------------------------------------------------------------- dispatch
def _validate_slots(spec: ActionSpec, raw: Any) -> BaseModel | None:
    """Declared fields only. Unknown fields — and any reserved identity/permission name — are refused outright, so a tenant id,
    a cap, a meter or a permission list cannot be smuggled in through a slot (spec §6.11, R14)."""
    model = spec.slot_model
    if model is None:
        if raw:
            raise InvalidSlots(f"{spec.key} takes no slots")
        return None
    if isinstance(raw, BaseModel):
        if not isinstance(raw, model):
            raise InvalidSlots(f"{spec.key}: wrong slot type {type(raw).__name__}")
        values: Mapping[str, Any] = raw.model_dump(exclude_unset=True)
        instance: BaseModel | None = raw
    else:
        values = raw or {}
        instance = None
    declared = set(model.model_fields) | {f.alias for f in model.model_fields.values() if f.alias}
    unknown = [k for k in values if k not in declared]
    reserved = [k for k in values if str(k).replace("_", "").lower() in {n.replace("_", "") for n in _RESERVED_SLOT_NAMES}]
    if unknown or reserved:
        raise InvalidSlots(f"{spec.key}: undeclared slot(s) {sorted(set(unknown) | set(reserved))}")
    try:
        validated = instance if instance is not None else model.model_validate(values)
    except ValidationError as exc:
        raise InvalidSlots(f"{spec.key}: {exc.error_count()} invalid slot value(s)") from None
    if spec.fixed_params:
        validated = validated.model_copy(update=dict(spec.fixed_params))
    return validated


def _refuse(
    turn: CeoTurn, spec: ActionSpec, *, denial: Denial, status: LegStatus, permission_check: str, entitlement_check: str,
    reason: str, now: datetime, registry_agent_id: str,
) -> LegResult:
    """Writes the DENIED child row and (when a turn row exists) the finding, with the same fidelity as a completed leg."""
    run = agent_run_repo.insert_run(
        turn.tenant_id, agent_id=registry_agent_id, trigger_type=turn.trigger_type, trigger_ref=spec.key,
        requested_by=turn.ctx.app_user_id, permission_check=permission_check, entitlement_check=entitlement_check,
        status="DENIED", started_at=now, finished_at=now, error_reason=reason, parent_run_id=turn.anchor_run_id,
        investigation_id=turn.investigation_id,
    )
    leg = _record(turn, spec, LegResult(action_key=spec.key, status=status, agent_run_id=run, reason=reason, denial=denial), report=None, now=now)
    turn.legs.append(leg)
    return leg


def _record(turn: CeoTurn, spec: ActionSpec, leg: LegResult, *, report: Mapping[str, str] | None, now: datetime) -> LegResult:
    """Writes the finding for a (tentative) leg together with its display snapshot, and returns the leg carrying the finding id. The snapshot
    comes from `turn.presenter`, which resolves every figure through its ref (R3); nothing here formats or computes a value."""
    if turn.investigation_id is None or turn.turn_id is None:
        return leg
    presentation = None
    if turn.presenter is not None:
        try:
            presentation = turn.presenter(leg)
        except Exception:  # noqa: BLE001 — a display snapshot must never break a finding; the API then shows refs only
            logger.exception("could not build a finding presentation for %s", spec.key)
    finding_id = investigation_repo.insert_finding(
        turn.tenant_id, turn.investigation_id, turn_id=turn.turn_id, source=spec.source, action_key=spec.key,
        status=leg.status.value, agent_run_id=leg.agent_run_id, figure_refs=[r.to_json() for r in leg.figure_refs],
        report_ref=dict(report) if report else None, gap_reason=leg.reason, presentation=presentation, now=now,
    )
    return dataclasses.replace(leg, finding_id=finding_id)


def dispatch(
    turn: CeoTurn,
    action_key: str,
    slots: Any = None,
    *,
    registry: ActionRegistry | None = None,
    attached: frozenset[str] | None = None,
    now: datetime | None = None,
    approval: ApprovalGrant | None = None,
) -> LegResult:
    """Runs ONE registered action as a leg of `turn`. Raises `UnregisteredAction` for a key outside the registry (never
    executed) and `InvalidSlots` for slots outside the declared model (before any row is written for the call itself).
    Every refusal is returned as a `LegResult`, never raised, and is logged as a DENIED child row."""
    reg = registry or get_registry()
    spec = reg.get(action_key)  # UnregisteredAction propagates: the closed catalog is the only thing dispatchable
    ctx, at = turn.ctx, _now(now)
    assert ctx.tenant_id is not None and ctx.role is not None
    agent_id = spec.source

    if not spec.wired:
        run = agent_run_repo.insert_run(
            ctx.tenant_id, agent_id=agent_id, trigger_type=turn.trigger_type, trigger_ref=spec.key, requested_by=ctx.app_user_id,
            permission_check="NOT_EVALUATED", entitlement_check="NOT_EVALUATED", status="FAILED", started_at=at, finished_at=at,
            error_reason=f"NOT_WIRED: {spec.not_wired_reason}", parent_run_id=turn.anchor_run_id, investigation_id=turn.investigation_id,
        )
        leg = _record(turn, spec, LegResult(spec.key, LegStatus.UNAVAILABLE, agent_run_id=run, reason="not available yet", denial=Denial.NOT_WIRED), report=None, now=at)
        turn.legs.append(leg)
        return leg

    # Approval backstop (decision D-8; spec C1/C3): an action the registry marks approval-required runs ONLY from a stored, hash-bound approval plan, and that
    # workflow does not exist yet. A confirmation card or a completed input session is an in-conversation answer, which is NOT approval, so nothing that
    # needs approval is dispatched from here. The refusal is a DENIED leg like any other (no invoke, so no usage and no external call). A registry whose
    # specs carry no effects (an ad hoc test registry) is unchanged; the production registry classifies every action (R1 refuses an unclassified one).
    # An APPROVED plan's execution carries an `ApprovalGrant` (same tenant, this key frozen in that plan): the only way past this backstop.
    granted = approval is not None and approval.tenant_id == ctx.tenant_id and spec.key in approval.action_keys
    if spec.effects is not None and not granted and gate_leg(spec.key, effects={spec.key: spec.effects}).requires_approval:
        return _refuse(
            turn, spec, denial=Denial.APPROVAL_REQUIRED, status=LegStatus.DENIED, permission_check="PASS", entitlement_check="NOT_EVALUATED",
            reason="approval required: this action needs an approved plan, which is not available yet", now=at, registry_agent_id=agent_id,
        )
    # R2: permission first — agent.ceo + the agent's key + the registry extras
    missing = [k for k in reg.required_permissions(spec) if not has_permission(role=ctx.role, permissions=ctx.permissions, key=k)]
    if missing:
        return _refuse(
            turn, spec, denial=Denial.PERMISSION, status=LegStatus.DENIED, permission_check=f"DENIED:{missing[0]}",
            entitlement_check="NOT_EVALUATED", reason=f"missing permission: {missing[0]}", now=at, registry_agent_id=agent_id,
        )
    # R13: attachment only ever narrows — fail closed when the set is unknown
    if spec.agent is not None:
        current = attached if attached is not None else (
            investigation_repo.attached_agents(ctx.tenant_id, turn.investigation_id) if turn.investigation_id else frozenset()
        )
        if spec.agent.value not in current:
            return _refuse(
                turn, spec, denial=Denial.NOT_ATTACHED, status=LegStatus.DENIED, permission_check="PASS",
                entitlement_check="NOT_EVALUATED", reason=f"{spec.agent.value} is not attached to this investigation",
                now=at, registry_agent_id=agent_id,
            )
    # R2: the owning entitlement resolver, evaluated before the call (the route re-checks its own gate)
    ent_text = "NOT_APPLICABLE"
    if spec.entitlement is not None:
        verdict = spec.entitlement(ctx.tenant_id, at)
        ent_text = _entitlement_text(verdict)
        if not verdict.passed:
            return _refuse(
                turn, spec, denial=Denial.ENTITLEMENT, status=LegStatus.NOT_ENTITLED, permission_check="PASS",
                entitlement_check=ent_text, reason=f"not entitled: {getattr(verdict, 'reason', None) or 'entitlement'}",
                now=at, registry_agent_id=agent_id,
            )

    model = _validate_slots(spec, slots)  # InvalidSlots: a request error, raised before the call's own row exists

    leg_run: UUID | None = None
    if not spec.writes_own_run:
        leg_run = agent_run_repo.insert_run(
            ctx.tenant_id, agent_id=agent_id, trigger_type=turn.trigger_type, trigger_ref=spec.key, requested_by=ctx.app_user_id,
            permission_check="PASS", entitlement_check=ent_text, status="RUNNING", started_at=at,
            parent_run_id=turn.anchor_run_id, investigation_id=turn.investigation_id,
        )
    leg_ctx = LegContext(
        tenant_id=ctx.tenant_id, requested_by=ctx.app_user_id, investigation_id=turn.investigation_id,
        turn_run_id=turn.anchor_run_id, leg_run_id=leg_run, now=at,
    )

    def finish(status: str, reason: str | None, refs: tuple[Ref, ...] = ()) -> bool:
        """True when this call settled the row (or the leg has no row of its own to settle); False when the row was already terminal."""
        if leg_run is not None:
            # Guarded: a leg that finishes after its row was already settled (a recovery or leg-deadline mark) must not overwrite it.
            if not agent_run_repo.finish_run_if_unfinished(
                ctx.tenant_id, leg_run, status=status, error_reason=reason, finished_at=datetime.now(timezone.utc),  # type: ignore[arg-type]
                output_refs=[r.to_json() for r in refs] if refs else None,
            ):
                logger.warning("CEO leg %s finished after its run %s was already terminal; its row was left as it was", spec.key, leg_run)
                return False
        return True

    def settled_earlier() -> LegResult:
        """The leg's row was already settled (timed out or interrupted) when its late result arrived: that state stands, no new finding is written and nothing is added to the turn."""
        return LegResult(spec.key, LegStatus.FAILED, agent_run_id=leg_run, reason="settled earlier")

    try:
        assert spec.invoke is not None
        with agent_run_repo.parent_run_scope(turn.anchor_run_id):
            payload = spec.invoke(model, ctx, leg_ctx)
    except HTTPException as exc:
        # The specialist's own gate refused (402 entitlement / 403 permission) or rejected the request.
        if exc.status_code in (402, 403):
            kind = Denial.ENTITLEMENT if exc.status_code == 402 else Denial.PERMISSION
            reason = "not entitled" if exc.status_code == 402 else "not permitted"
            finish("DENIED", f"{exc.status_code}")
            if leg_run is None:  # the specialist wrote no row for a refusal — record it
                leg_run = agent_run_repo.insert_run(
                    ctx.tenant_id, agent_id=agent_id, trigger_type=turn.trigger_type, trigger_ref=spec.key,
                    requested_by=ctx.app_user_id, permission_check="DENIED" if kind is Denial.PERMISSION else "PASS",
                    entitlement_check="DENIED" if kind is Denial.ENTITLEMENT else ent_text, status="DENIED", started_at=at,
                    finished_at=datetime.now(timezone.utc), error_reason=f"{exc.status_code}", parent_run_id=turn.anchor_run_id,
                    investigation_id=turn.investigation_id,
                )
            status = LegStatus.NOT_ENTITLED if kind is Denial.ENTITLEMENT else LegStatus.DENIED
            leg = _record(turn, spec, LegResult(spec.key, status, agent_run_id=leg_run, reason=reason, denial=kind), report=None, now=at)
        else:
            reason = "unavailable" if exc.status_code in (404, 409, 503) else "request rejected"
            if not finish("FAILED", f"{exc.status_code}"):
                return settled_earlier()
            leg = _record(turn, spec, LegResult(spec.key, LegStatus.UNAVAILABLE if exc.status_code in (404, 503) else LegStatus.FAILED,
                                                agent_run_id=leg_run, reason=reason), report=None, now=at)
        turn.legs.append(leg)
        return leg
    except Exception:  # noqa: BLE001 — R12: never surface internals; the server log has them
        logger.exception("CEO leg %s failed (tenant=%s)", spec.key, ctx.tenant_id)
        if not finish("FAILED", "dispatch failed"):
            return settled_earlier()
        leg = _record(turn, spec, LegResult(spec.key, LegStatus.FAILED, agent_run_id=leg_run, reason="the action failed"), report=None, now=at)
        turn.legs.append(leg)
        return leg

    try:
        # A specialist's response is data from another module: a malformed one (not a mapping, or refs that cannot be read) is a failed leg, never an exception that
        # escapes with the child run still RUNNING.
        if not isinstance(payload, Mapping):
            raise TypeError(f"{spec.key} returned {type(payload).__name__}, not a mapping")
        extractor = spec.extract_refs or provenance.default_extract_refs
        refs = tuple(extractor(payload))
        partial = any(payload.get(k) for k in _PARTIAL_KEYS)
    except Exception:  # noqa: BLE001 — R12: the server log has the detail; the caller gets a plain failed leg
        logger.exception("CEO leg %s returned a malformed response (tenant=%s)", spec.key, ctx.tenant_id)
        if not finish("FAILED", "malformed specialist response"):
            return settled_earlier()
        leg = _record(turn, spec, LegResult(spec.key, LegStatus.FAILED, agent_run_id=leg_run, reason="the action failed"), report=None, now=at)
        turn.legs.append(leg)
        return leg
    status = LegStatus.PARTIAL if partial else LegStatus.COMPLETE
    if not finish(status.value, None, refs):
        # The row was settled earlier (timeout or recovery): that state stands and NO finding is written, so nothing contradicts it. The caller still sees what its call returned.
        leg = LegResult(spec.key, status, agent_run_id=leg_run, payload=payload, figure_refs=refs)
        turn.legs.append(leg)
        return leg
    leg = _record(turn, spec, LegResult(spec.key, status, agent_run_id=leg_run, payload=payload, figure_refs=refs), report=provenance.report_pointers(payload), now=at)
    turn.legs.append(leg)
    return leg
