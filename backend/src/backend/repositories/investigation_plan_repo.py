"""investigation_plan / investigation_plan_event - ceo-approval-workflow.md section 5. DDL: `20261012_0019_ceo_approval_workflow.py`.

THE one place a plan changes state. Every status change and its event are written in ONE transaction by a function in this module (spec 5.2, AC-A10); the database backs
that up with a guard trigger (terminal states are final, the frozen plan is immutable) and a deferred constraint trigger (a commit that changes a status without exactly the
matching event, or creates a plan without its CREATED event, fails). Nothing else in the code base updates `investigation_plan`.

Every function runs inside `tenant_scope(tenant_id)`: RLS (FORCE) is the final boundary and every query is also scoped by the investigation id the caller names, so a foreign
tenant's plan id is indistinguishable from a missing one. This module decides nothing about authorization, hashing, expiry policy or execution: it stores what
`ceo/approval.py` hands it and reports whether THIS call won each compare-and-set.

The plan JSON, its hash and its expiry are written once and never updated (column privileges + trigger). No money is computed here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from backend.repositories.investigation_repo import InvestigationNotFound, _require_investigation
from backend.tenant_context import tenant_scope

PLAN_STATUSES = ("AWAITING_APPROVAL", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED")
EVENTS = ("CREATED", "APPROVAL_REFUSED", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED", "EXECUTION_STARTED", "EXECUTION_FINISHED", "EXECUTION_FAILED",
          "EXECUTION_NOT_STARTED", "OUTCOME_UNKNOWN")
_COLUMNS = ("id, tenant_id, investigation_id, planned_turn_id, execution_turn_id, plan, plan_hash, status, requested_by, created_at, expires_at, "
            "decided_by, decided_at, decision_reason")


class PlanNotFound(LookupError):
    """No such plan in this tenant and investigation (a foreign tenant's id is indistinguishable from a missing one)."""


class _LostRace(Exception):
    """Raised inside a transaction so everything written so far in it is rolled back: another caller changed the plan first."""


@dataclass(frozen=True, slots=True)
class Approved:
    execution_turn_id: UUID
    note_message_id: UUID


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _jsonb(value: Any) -> str | None:
    return json.dumps(value, default=str) if value is not None else None


def _event(
    conn: Connection, tenant_id: UUID, plan_id: UUID, plan_hash: str, *, event: str, from_status: str | None, to_status: str | None, actor_user_id: UUID | None,
    reason_code: str | None, metadata: Mapping[str, Any] | None, at: datetime,
) -> None:
    assert event in EVENTS
    conn.execute(
        text(
            "INSERT INTO investigation_plan_event (tenant_id, plan_id, event, from_status, to_status, actor_user_id, actor_kind, occurred_at, plan_hash, reason_code, metadata) "
            "VALUES (:t, :p, :e, :f, :to, :actor, :kind, :at, :h, :reason, CAST(:meta AS jsonb))"
        ),
        {"t": str(tenant_id), "p": str(plan_id), "e": event, "f": from_status, "to": to_status, "actor": str(actor_user_id) if actor_user_id else None,
         "kind": "USER" if actor_user_id else "SYSTEM", "at": at, "h": plan_hash, "reason": reason_code, "meta": _jsonb(metadata)},
    )


# ------------------------------------------------------------------------------ reads
def get(tenant_id: UUID, investigation_id: UUID, plan_id: UUID) -> dict[str, Any] | None:
    """The plan, only if it belongs to THIS investigation of THIS tenant."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(f"SELECT {_COLUMNS} FROM investigation_plan WHERE id = :id AND investigation_id = :inv"), {"id": str(plan_id), "inv": str(investigation_id)}
        ).mappings().first()
        return dict(row) if row is not None else None


def get_by_planned_turn(tenant_id: UUID, planned_turn_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text(f"SELECT {_COLUMNS} FROM investigation_plan WHERE planned_turn_id = :t"), {"t": str(planned_turn_id)}).mappings().first()
        return dict(row) if row is not None else None


def list_for_investigation(tenant_id: UUID, investigation_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(f"SELECT {_COLUMNS} FROM investigation_plan WHERE investigation_id = :inv ORDER BY created_at, id"), {"inv": str(investigation_id)}
        ).mappings()
        return [dict(r) for r in rows]


def events(tenant_id: UUID, plan_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, plan_id, event, from_status, to_status, actor_user_id, actor_kind, occurred_at, plan_hash, reason_code, metadata "
                "FROM investigation_plan_event WHERE plan_id = :p ORDER BY occurred_at, id"
            ),
            {"p": str(plan_id)},
        ).mappings()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------------------ supersession (shared by creation and by resolve / archive)
def supersede_open(
    conn: Connection, tenant_id: UUID, investigation_id: UUID, *, reason_code: str, new_plan_id: UUID | None, at: datetime,
) -> list[UUID]:
    """AWAITING_APPROVAL -> SUPERSEDED for every open plan of the investigation, with one SUPERSEDED event each (actor: the system), inside the CALLER's transaction. A plan
    that was decided by someone else first is simply skipped (its CAS matches no row)."""
    done: list[UUID] = []
    open_rows = conn.execute(
        text("SELECT id, plan_hash FROM investigation_plan WHERE investigation_id = :inv AND status = 'AWAITING_APPROVAL' ORDER BY created_at FOR UPDATE"),
        {"inv": str(investigation_id)},
    ).all()
    for pid, phash in open_rows:
        res = conn.execute(
            text("UPDATE investigation_plan SET status = 'SUPERSEDED', decided_at = :at, decision_reason = :reason WHERE id = :id AND status = 'AWAITING_APPROVAL'"),
            {"id": str(pid), "at": at, "reason": reason_code},
        )
        if res.rowcount == 1:
            _event(conn, tenant_id, pid, phash, event="SUPERSEDED", from_status="AWAITING_APPROVAL", to_status="SUPERSEDED", actor_user_id=None, reason_code=reason_code,
                   metadata={"newPlanId": str(new_plan_id)} if new_plan_id else None, at=at)
            done.append(pid)
    return done


# ------------------------------------------------------------------------------ creation
def create(
    tenant_id: UUID, *, plan_id: UUID, investigation_id: UUID, planned_turn_id: UUID, anchor_run_id: UUID, requested_by: UUID, plan: Mapping[str, Any], plan_hash: str,
    created_at: datetime, expires_at: datetime, message_text: str,
) -> UUID:
    """ONE transaction: any older open plan of the investigation becomes SUPERSEDED (with its event), the new plan is inserted AWAITING_APPROVAL, its CREATED event and the
    `PLAN` chat message are written. Returns the message id. The caller has already computed the hash over exactly these values (`ceo/approval.py`)."""
    message_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        _require_investigation(conn, investigation_id)
        owner = conn.execute(text("SELECT investigation_id FROM investigation_turn WHERE id = :t"), {"t": str(planned_turn_id)}).first()
        if owner is None or str(owner[0]) != str(investigation_id):
            raise InvestigationNotFound(f"turn {planned_turn_id} is not part of investigation {investigation_id}")
        supersede_open(conn, tenant_id, investigation_id, reason_code="NEWER_PLAN", new_plan_id=plan_id, at=created_at)
        conn.execute(
            text(
                "INSERT INTO investigation_plan (id, tenant_id, investigation_id, planned_turn_id, plan, plan_hash, status, requested_by, created_at, expires_at) "
                "VALUES (:id, :t, :inv, :turn, CAST(:plan AS jsonb), :h, 'AWAITING_APPROVAL', :by, :created, :expires)"
            ),
            {"id": str(plan_id), "t": str(tenant_id), "inv": str(investigation_id), "turn": str(planned_turn_id), "plan": json.dumps(plan), "h": plan_hash,
             "by": str(requested_by), "created": created_at, "expires": expires_at},
        )
        _event(conn, tenant_id, plan_id, plan_hash, event="CREATED", from_status=None, to_status="AWAITING_APPROVAL", actor_user_id=requested_by, reason_code=None,
               metadata={"plannedTurnId": str(planned_turn_id)}, at=created_at)
        conn.execute(
            text(
                "INSERT INTO investigation_message (id, investigation_id, tenant_id, role, kind, content, turn_id, agent_run_id, created_by, created_at) "
                "VALUES (:id, :inv, :t, 'CEO', 'PLAN', :content, :turn, :run, NULL, :at)"
            ),
            {"id": str(message_id), "inv": str(investigation_id), "t": str(tenant_id), "content": message_text, "turn": str(planned_turn_id), "run": str(anchor_run_id), "at": created_at},
        )
        conn.execute(text("UPDATE investigation SET last_message_at = :at WHERE id = :id"), {"at": created_at, "id": str(investigation_id)})
    return message_id


# ------------------------------------------------------------------------------ transitions (each: CAS + event, one transaction)
def expire_if_due(tenant_id: UUID, plan_id: UUID, *, now: datetime) -> bool:
    """AWAITING_APPROVAL -> EXPIRED once `expires_at` has passed (persisted lazily on read / approve). True when THIS call expired it."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("UPDATE investigation_plan SET status = 'EXPIRED', decided_at = :now, decision_reason = 'EXPIRED' WHERE id = :id AND status = 'AWAITING_APPROVAL' "
                 "AND expires_at <= :now RETURNING plan_hash"),
            {"id": str(plan_id), "now": now},
        ).first()
        if row is None:
            return False
        _event(conn, tenant_id, plan_id, row[0], event="EXPIRED", from_status="AWAITING_APPROVAL", to_status="EXPIRED", actor_user_id=None, reason_code="TTL", metadata=None, at=now)
        return True


def decline(tenant_id: UUID, *, plan_id: UUID, investigation_id: UUID, user_id: UUID, reason: str | None, note_content: str, now: datetime) -> bool:
    """AWAITING_APPROVAL -> DECLINED by the requester, with the DECLINED event and a SYSTEM_NOTE message. True when THIS call declined it (False: someone else decided first).
    No model call, no CEO unit (a declined plan costs nothing)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("UPDATE investigation_plan SET status = 'DECLINED', decided_by = :by, decided_at = :now, decision_reason = :reason "
                 "WHERE id = :id AND investigation_id = :inv AND status = 'AWAITING_APPROVAL' AND requested_by = :by RETURNING plan_hash"),
            {"id": str(plan_id), "inv": str(investigation_id), "by": str(user_id), "now": now, "reason": (reason or "")[:200] or None},
        ).first()
        if row is None:
            return False
        _event(conn, tenant_id, plan_id, row[0], event="DECLINED", from_status="AWAITING_APPROVAL", to_status="DECLINED", actor_user_id=user_id, reason_code="USER_DECLINED",
               metadata=None, at=now)
        conn.execute(
            text("INSERT INTO investigation_message (id, investigation_id, tenant_id, role, kind, content, created_by, created_at) VALUES (:id, :inv, :t, 'SYSTEM', 'SYSTEM_NOTE', :c, :by, :at)"),
            {"id": str(uuid4()), "inv": str(investigation_id), "t": str(tenant_id), "c": note_content, "by": str(user_id), "at": now},
        )
        conn.execute(text("UPDATE investigation SET last_message_at = :at WHERE id = :id"), {"at": now, "id": str(investigation_id)})
        return True


def approve(
    tenant_id: UUID, *, plan_id: UUID, investigation_id: UUID, user_id: UUID, anchor_run_id: UUID, route: str, route_key: str | None, slots: Mapping[str, Any],
    note_content: str, now: datetime,
) -> Approved | None:
    """The approval transaction (spec 6.6, last paragraph): the approval SYSTEM_NOTE message (D8), the execution turn (`route_source = 'APPROVAL'`, `plan_id`), the
    compare-and-set AWAITING_APPROVAL -> APPROVED (only while unexpired, only for the requester) and the APPROVED event, ALL in one transaction. If the compare-and-set
    matches no row (declined / expired / superseded / approved by another request first) the whole transaction is rolled back and None is returned: no message, no turn."""
    note_id, turn_id = uuid4(), uuid4()
    try:
        with tenant_scope(tenant_id) as conn:
            _require_investigation(conn, investigation_id)
            conn.execute(
                text("INSERT INTO investigation_message (id, investigation_id, tenant_id, role, kind, content, created_by, created_at) VALUES (:id, :inv, :t, 'SYSTEM', 'SYSTEM_NOTE', :c, :by, :at)"),
                {"id": str(note_id), "inv": str(investigation_id), "t": str(tenant_id), "c": note_content, "by": str(user_id), "at": now},
            )
            conn.execute(
                text(
                    "INSERT INTO investigation_turn (id, tenant_id, investigation_id, user_message_id, agent_run_id, route, route_key, route_source, slots, classifier_result, status, "
                    "plan_id, created_at) VALUES (:id, :t, :inv, :umsg, :run, :route, :key, 'APPROVAL', CAST(:slots AS jsonb), CAST(:cls AS jsonb), 'PLAN_VALIDATED', :plan, :at)"
                ),
                {"id": str(turn_id), "t": str(tenant_id), "inv": str(investigation_id), "umsg": str(note_id), "run": str(anchor_run_id), "route": route, "key": route_key,
                 "slots": _jsonb(dict(slots)), "cls": _jsonb({"approvedPlanId": str(plan_id), "model": "none (approved plan)"}), "plan": str(plan_id), "at": now},
            )
            conn.execute(text("UPDATE investigation_message SET turn_id = :turn WHERE id = :msg"), {"turn": str(turn_id), "msg": str(note_id)})
            row = conn.execute(
                text("UPDATE investigation_plan SET status = 'APPROVED', execution_turn_id = :turn, decided_by = :by, decided_at = :now, decision_reason = 'APPROVED' "
                     "WHERE id = :id AND investigation_id = :inv AND status = 'AWAITING_APPROVAL' AND expires_at > :now AND requested_by = :by RETURNING plan_hash"),
                {"id": str(plan_id), "inv": str(investigation_id), "turn": str(turn_id), "by": str(user_id), "now": now},
            ).first()
            if row is None:
                raise _LostRace
            _event(conn, tenant_id, plan_id, row[0], event="APPROVED", from_status="AWAITING_APPROVAL", to_status="APPROVED", actor_user_id=user_id, reason_code="USER_APPROVED",
                   metadata={"executionTurnId": str(turn_id), "anchorRunId": str(anchor_run_id)}, at=now)
            conn.execute(text("UPDATE investigation SET last_message_at = :at WHERE id = :id"), {"at": now, "id": str(investigation_id)})
    except _LostRace:
        return None
    return Approved(turn_id, note_id)


def record_event(
    tenant_id: UUID, plan_id: UUID, *, event: str, actor_user_id: UUID | None, reason_code: str | None = None, metadata: Mapping[str, Any] | None = None, now: datetime | None = None,
) -> None:
    """An event that is not a status change (APPROVAL_REFUSED, EXECUTION_*, OUTCOME_UNKNOWN). Refuses a status-changing event name: those exist only inside the
    transitions above. `metadata` carries references only (ids, a reason code), never figures or seller text."""
    if event in ("CREATED", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED"):
        raise ValueError(f"{event} is written only by the transition that changes the status")
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT plan_hash FROM investigation_plan WHERE id = :id"), {"id": str(plan_id)}).first()
        if row is None:
            raise PlanNotFound(str(plan_id))
        _event(conn, tenant_id, plan_id, row[0], event=event, from_status=None, to_status=None, actor_user_id=actor_user_id, reason_code=reason_code, metadata=metadata, at=_now(now))
