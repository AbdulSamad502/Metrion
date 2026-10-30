"""investigation / investigation_message / investigation_turn / investigation_finding /
investigation_agent — ceo-agent-orchestration.md §5, §6.14, §6.22. DDL: `20260917_0002` +
`20261007_0006_ceo_foundation.py`.

Every function runs inside `tenant_scope(tenant_id)` (auth.md §7.3: RLS is the final boundary,
application scoping sits above it). **Defence in depth against cross-tenant foreign keys:** a FK is
checked with the owner's privileges, so Postgres would accept a row whose `investigation_id` belongs
to ANOTHER tenant if the application passed one. Every insert here therefore first confirms that the
parent investigation is visible in the CALLER's tenant (RLS filters it otherwise) and raises
`InvestigationNotFound` — which the API layer maps to 404, indistinguishable from "does not exist"
(spec §8 rule 5, T12).

This module computes nothing about money and decides nothing about routing; it stores what the CEO
layer hands it. `investigation_finding.figure_refs` holds references only (spec R7).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from backend.tenant_context import tenant_scope

INVESTIGATION_STATUSES = ("ACTIVE", "RESOLVED", "ARCHIVED")
ORIGINS = ("USER_CHAT", "WHATSAPP", "SYSTEM")
ATTACHABLE_AGENT_CODES = ("CFO", "CI", "PI", "CMO")


class InvestigationNotFound(LookupError):
    """No such investigation in this tenant (a foreign tenant's id is indistinguishable from a missing one)."""


class InvalidInvestigationTransition(ValueError):
    pass


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _require_investigation(conn: Connection, investigation_id: UUID) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT id, status FROM investigation WHERE id = :id"), {"id": str(investigation_id)}
    ).first()
    if row is None:
        raise InvestigationNotFound(str(investigation_id))
    return dict(row._mapping)


def _require_visible(conn: Connection, table: str, row_id: UUID, *, investigation_id: UUID | None = None) -> None:
    """The row must be visible in the caller's tenant (RLS) — and, for messages, belong to this investigation."""
    assert table in ("agent_run", "investigation_message")  # fixed allowlist: never interpolate caller input
    sql = f"SELECT 1 FROM {table} WHERE id = :id" + (" AND investigation_id = :inv" if table == "investigation_message" else "")
    params: dict[str, Any] = {"id": str(row_id)}
    if table == "investigation_message":
        params["inv"] = str(investigation_id)
    if conn.execute(text(sql), params).first() is None:
        raise InvestigationNotFound(f"{table} {row_id}")


def _jsonb(value: Any) -> str | None:
    return json.dumps(value, default=str) if value is not None else None


# ------------------------------------------------------------------------------ investigation
def create_investigation(
    tenant_id: UUID,
    *,
    created_by: UUID,
    origin: str = "USER_CHAT",
    title: str | None = None,
    attached_agents: Iterable[str] = (),
    detached_agents: Iterable[str] = (),
    now: datetime | None = None,
) -> UUID:
    """Creates an ACTIVE investigation plus its attached-agent set in ONE transaction. The caller decides which
    agents are attached by default (every agent the tenant is entitled to — spec §6.22 rule 1); this function
    never decides it and never grants anything."""
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin {origin!r}")
    attached, detached = list(attached_agents), list(detached_agents)
    bad = [a for a in (*attached, *detached) if a not in ATTACHABLE_AGENT_CODES]
    if bad or set(attached) & set(detached):
        raise ValueError(f"invalid agent set: {bad or sorted(set(attached) & set(detached))}")
    at, investigation_id = _now(now), uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                "INSERT INTO investigation (id, tenant_id, title, status, origin, created_by, created_at, last_message_at) "
                "VALUES (:id, :tenant_id, :title, 'ACTIVE', :origin, :created_by, :at, :at)"
            ),
            {"id": str(investigation_id), "tenant_id": str(tenant_id), "title": title, "origin": origin,
             "created_by": str(created_by), "at": at},
        )
        for code, flag in [(c, True) for c in attached] + [(c, False) for c in detached]:
            _upsert_agent(conn, tenant_id, investigation_id, code, flag, created_by, at)
    return investigation_id


def get_investigation(tenant_id: UUID, investigation_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, title, status, origin, situation_id, created_by, summary, summary_covers_through, "
                "resolution_note, resolved_by, resolved_at, created_at, last_message_at "
                "FROM investigation WHERE id = :id"
            ),
            {"id": str(investigation_id)},
        ).first()
        return dict(row._mapping) if row is not None else None


def list_investigations(tenant_id: UUID, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, title, status, origin, created_by, created_at, last_message_at FROM investigation "
                "WHERE (CAST(:status AS text) IS NULL OR status = :status) "
                "ORDER BY last_message_at DESC, id LIMIT :limit"
            ),
            {"status": status, "limit": limit},
        )
        return [dict(r._mapping) for r in rows]


def resolve_investigation(
    tenant_id: UUID, investigation_id: UUID, *, resolved_by: UUID, resolution_note: str, now: datetime | None = None
) -> None:
    """RESOLVED needs a seller-authored, non-empty note (spec §6.22; also a DB CHECK). Only an ACTIVE
    investigation can be resolved."""
    if not resolution_note or not resolution_note.strip():
        raise ValueError("a resolution note is required")
    with tenant_scope(tenant_id) as conn:
        current = _require_investigation(conn, investigation_id)
        if current["status"] != "ACTIVE":
            raise InvalidInvestigationTransition(f"cannot resolve a {current['status']} investigation")
        conn.execute(
            text(
                "UPDATE investigation SET status = 'RESOLVED', resolution_note = :note, resolved_by = :by, "
                "resolved_at = :at WHERE id = :id"
            ),
            {"id": str(investigation_id), "note": resolution_note.strip(), "by": str(resolved_by), "at": _now(now)},
        )
        _supersede_plans(conn, tenant_id, investigation_id, "INVESTIGATION_RESOLVED", _now(now))  # E3: an open approval plan never outlives the investigation's active state


def reopen_investigation(tenant_id: UUID, investigation_id: UUID) -> None:
    """RESOLVED or ARCHIVED -> ACTIVE. The earlier resolution note/audit stays in `auth_audit`/history; the
    live columns are cleared so a re-opened investigation never claims a conclusion it no longer has."""
    with tenant_scope(tenant_id) as conn:
        current = _require_investigation(conn, investigation_id)
        if current["status"] == "ACTIVE":
            raise InvalidInvestigationTransition("already ACTIVE")
        conn.execute(
            text(
                "UPDATE investigation SET status = 'ACTIVE', resolution_note = NULL, resolved_by = NULL, "
                "resolved_at = NULL WHERE id = :id"
            ),
            {"id": str(investigation_id)},
        )


def reopen_resolved_investigation(tenant_id: UUID, investigation_id: UUID) -> str:
    """RESOLVED -> ACTIVE, and ONLY from RESOLVED (an ARCHIVED investigation is a visibility state, never a conclusion, so it is not
    reopened here). Unlike `reopen_investigation`, the seller's `resolution_note` / `resolved_by` / `resolved_at` are left exactly as
    they were: nothing is deleted or rewritten. Returns the preserved note so the caller can record it in the thread (a later
    re-resolve writes a new note into these columns, so the earlier conclusion must also live in the history)."""
    with tenant_scope(tenant_id) as conn:
        current = _require_investigation(conn, investigation_id)
        if current["status"] != "RESOLVED":
            raise InvalidInvestigationTransition(f"only a RESOLVED investigation can be reopened, not {current['status']}")
        note = conn.execute(text("SELECT resolution_note FROM investigation WHERE id = :id"), {"id": str(investigation_id)}).scalar_one()
        conn.execute(text("UPDATE investigation SET status = 'ACTIVE' WHERE id = :id"), {"id": str(investigation_id)})
        return str(note)


def update_summary(tenant_id: UUID, investigation_id: UUID, summary: str, covers_through: UUID) -> None:
    """Writes the rolling summary and the pointer to the last message folded into it (spec D2). Called only by `ceo.summary`, under the turn lock."""
    with tenant_scope(tenant_id) as conn:
        _require_investigation(conn, investigation_id)
        conn.execute(
            text("UPDATE investigation SET summary = :s, summary_covers_through = :m WHERE id = :id"),
            {"s": summary, "m": str(covers_through), "id": str(investigation_id)},
        )


def archive_investigation(tenant_id: UUID, investigation_id: UUID) -> None:
    with tenant_scope(tenant_id) as conn:
        current = _require_investigation(conn, investigation_id)
        if current["status"] == "ARCHIVED":
            raise InvalidInvestigationTransition("already ARCHIVED")
        conn.execute(
            text(
                "UPDATE investigation SET status = 'ARCHIVED', resolution_note = NULL, resolved_by = NULL, "
                "resolved_at = NULL WHERE id = :id"
            ),
            {"id": str(investigation_id)},
        )
        _supersede_plans(conn, tenant_id, investigation_id, "INVESTIGATION_ARCHIVED", _now(None))


def _supersede_plans(conn: Connection, tenant_id: UUID, investigation_id: UUID, reason_code: str, at: datetime) -> None:
    """Approval workflow E3: resolving or archiving supersedes any plan still AWAITING_APPROVAL, in the SAME transaction as the status change (reopening never revives it)."""
    from backend.repositories import investigation_plan_repo

    investigation_plan_repo.supersede_open(conn, tenant_id, investigation_id, reason_code=reason_code, new_plan_id=None, at=at)


# ------------------------------------------------------------------------------ attachment
def _upsert_agent(
    conn: Connection, tenant_id: UUID, investigation_id: UUID, agent_code: str, attached: bool, changed_by: UUID, at: datetime
) -> None:
    if agent_code not in ATTACHABLE_AGENT_CODES:
        raise ValueError(f"unknown agent {agent_code!r}")
    conn.execute(
        text(
            "INSERT INTO investigation_agent (investigation_id, tenant_id, agent_code, attached, changed_by, changed_at) "
            "VALUES (:inv, :tenant, :code, :attached, :by, :at) "
            "ON CONFLICT (investigation_id, agent_code) DO UPDATE SET attached = EXCLUDED.attached, "
            "changed_by = EXCLUDED.changed_by, changed_at = EXCLUDED.changed_at"
        ),
        {"inv": str(investigation_id), "tenant": str(tenant_id), "code": agent_code, "attached": attached,
         "by": str(changed_by), "at": at},
    )


def set_agent_attachment(
    tenant_id: UUID, investigation_id: UUID, agent_code: str, *, attached: bool, changed_by: UUID, now: datetime | None = None
) -> None:
    """Records the seller's choice. This NARROWS what the CEO may call/read (spec R13); it never grants access,
    and the entitlement/permission checks still run on every dispatch."""
    with tenant_scope(tenant_id) as conn:
        _require_investigation(conn, investigation_id)
        _upsert_agent(conn, tenant_id, investigation_id, agent_code, attached, changed_by, _now(now))


def attached_agents(tenant_id: UUID, investigation_id: UUID) -> frozenset[str]:
    """The agents currently ATTACHED. An agent with no row is NOT attached (fail closed)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT agent_code FROM investigation_agent WHERE investigation_id = :id AND attached"),
            {"id": str(investigation_id)},
        )
        return frozenset(r[0] for r in rows)


def agent_states(tenant_id: UUID, investigation_id: UUID) -> dict[str, bool]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT agent_code, attached FROM investigation_agent WHERE investigation_id = :id"),
            {"id": str(investigation_id)},
        )
        return {r[0]: bool(r[1]) for r in rows}


# ------------------------------------------------------------------------------ messages
def append_message(
    tenant_id: UUID,
    investigation_id: UUID,
    *,
    role: str,
    content: str,
    kind: str = "TEXT",
    created_by: UUID | None = None,
    agent_run_id: UUID | None = None,
    turn_id: UUID | None = None,
    choices: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> UUID:
    at, message_id = _now(now), uuid4()
    with tenant_scope(tenant_id) as conn:
        _require_investigation(conn, investigation_id)
        conn.execute(
            text(
                "INSERT INTO investigation_message (id, investigation_id, tenant_id, role, kind, content, turn_id, "
                "agent_run_id, created_by, created_at, choices) VALUES (:id, :inv, :tenant, :role, :kind, :content, :turn, "
                ":run, :by, :at, CAST(:choices AS jsonb))"
            ),
            {"id": str(message_id), "inv": str(investigation_id), "tenant": str(tenant_id), "role": role, "kind": kind,
             "content": content, "turn": str(turn_id) if turn_id else None,
             "run": str(agent_run_id) if agent_run_id else None, "by": str(created_by) if created_by else None, "at": at,
             "choices": _jsonb(choices)},
        )
        conn.execute(
            text("UPDATE investigation SET last_message_at = :at WHERE id = :id"), {"at": at, "id": str(investigation_id)}
        )
    return message_id


def list_messages(tenant_id: UUID, investigation_id: UUID, *, after_message_id: UUID | None = None) -> list[dict[str, Any]]:
    """Messages in order: `created_at`, then `seq` (the database's insertion order; a seller's message and the CEO's reply to it can share one timestamp, and the random id must never decide).
    `after_message_id` returns only messages created after that one (the rolling-summary
    window: messages since `summary_covers_through`, spec AC9)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT m.id, m.role, m.kind, m.content, m.turn_id, m.agent_run_id, m.created_by, m.created_at, m.choices "
                "FROM investigation_message m WHERE m.investigation_id = :inv "
                "AND (CAST(:after AS uuid) IS NULL OR (m.created_at, m.seq) > "
                "     (SELECT a.created_at, a.seq FROM investigation_message a WHERE a.id = :after)) "
                "ORDER BY m.created_at, m.seq"
            ),
            {"inv": str(investigation_id), "after": str(after_message_id) if after_message_id else None},
        )
        return [dict(r._mapping) for r in rows]


def get_message(tenant_id: UUID, investigation_id: UUID, message_id: UUID) -> dict[str, Any] | None:
    """One message of THIS investigation of THIS tenant (RLS + the investigation id), or None."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, role, kind, content, turn_id, created_at, choices FROM investigation_message "
                "WHERE id = :id AND investigation_id = :inv"
            ),
            {"id": str(message_id), "inv": str(investigation_id)},
        ).mappings().first()
        return dict(row) if row is not None else None


# ------------------------------------------------------------------------------ turns
def create_turn(
    tenant_id: UUID,
    investigation_id: UUID,
    *,
    user_message_id: UUID,
    agent_run_id: UUID,
    route: str,
    route_key: str | None = None,
    route_source: str = "CLASSIFIER",
    slots: Mapping[str, Any] | None = None,
    classifier_result: Mapping[str, Any] | None = None,
    status: str = "RECEIVED",
    now: datetime | None = None,
) -> UUID:
    turn_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        _require_investigation(conn, investigation_id)
        _require_visible(conn, "investigation_message", user_message_id, investigation_id=investigation_id)
        _require_visible(conn, "agent_run", agent_run_id)
        conn.execute(
            text(
                "INSERT INTO investigation_turn (id, tenant_id, investigation_id, user_message_id, agent_run_id, route, "
                "route_key, route_source, slots, classifier_result, status, created_at) VALUES (:id, :tenant, :inv, "
                ":umsg, :run, :route, :key, :source, CAST(:slots AS jsonb), CAST(:cls AS jsonb), :status, :at)"
            ),
            {"id": str(turn_id), "tenant": str(tenant_id), "inv": str(investigation_id), "umsg": str(user_message_id),
             "run": str(agent_run_id), "route": route, "key": route_key, "source": route_source,
             "slots": _jsonb(slots), "cls": _jsonb(classifier_result), "status": status, "at": _now(now)},
        )
        conn.execute(
            text("UPDATE investigation_message SET turn_id = :turn WHERE id = :msg AND investigation_id = :inv"),
            {"turn": str(turn_id), "msg": str(user_message_id), "inv": str(investigation_id)},
        )
    return turn_id


def update_turn(
    tenant_id: UUID,
    turn_id: UUID,
    *,
    status: str,
    ceo_message_id: UUID | None = None,
    composition_mode: str | None = None,
    safety_result: Mapping[str, Any] | None = None,
    stage_timings: Mapping[str, Any] | None = None,
    completed_at: datetime | None = None,
) -> None:
    """Advances a turn. Fields not supplied are left untouched."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE investigation_turn SET status = :status, "
                "ceo_message_id = COALESCE(:ceo_msg, ceo_message_id), "
                "composition_mode = COALESCE(:mode, composition_mode), "
                "safety_result = COALESCE(CAST(:safety AS jsonb), safety_result), "
                "stage_timings = COALESCE(CAST(:timings AS jsonb), stage_timings), "
                "completed_at = COALESCE(:done, completed_at) WHERE id = :id"
            ),
            {"id": str(turn_id), "status": status, "ceo_msg": str(ceo_message_id) if ceo_message_id else None,
             "mode": composition_mode, "safety": _jsonb(safety_result), "timings": _jsonb(stage_timings),
             "done": completed_at},
        )
        if result.rowcount == 0:
            raise InvestigationNotFound(f"turn {turn_id}")


def finalise_turn(
    tenant_id: UUID,
    turn_id: UUID,
    *,
    status: str,
    billing: Mapping[str, Any],
    ceo_message_id: UUID | None = None,
    composition_mode: str | None = None,
    safety_result: Mapping[str, Any] | None = None,
    stage_timings: Mapping[str, Any] | None = None,
    completed_at: datetime | None = None,
) -> bool:
    """Ends a turn AND stores its billing decision, once. The UPDATE applies only to a turn that is not yet complete and has no stored decision, so
    exactly one caller ever finalises a turn: it returns True for that caller and False for any other (a replay, a race, a recovery). Only the
    caller that got True may write the usage event (approval prerequisite R2: the decision is stored once and usage is written once)."""
    with tenant_scope(tenant_id) as conn:
        result = conn.execute(
            text(
                "UPDATE investigation_turn SET status = :status, "
                "ceo_message_id = COALESCE(:ceo_msg, ceo_message_id), "
                "composition_mode = COALESCE(:mode, composition_mode), "
                "safety_result = COALESCE(CAST(:safety AS jsonb), safety_result, CAST('{}' AS jsonb)) || jsonb_build_object('billing', CAST(:billing AS jsonb)), "
                "stage_timings = COALESCE(CAST(:timings AS jsonb), stage_timings), "
                "completed_at = COALESCE(:done, completed_at) "
                "WHERE id = :id AND completed_at IS NULL AND NOT (COALESCE(safety_result, CAST('{}' AS jsonb)) ? 'billing')"
            ),
            {"id": str(turn_id), "status": status, "ceo_msg": str(ceo_message_id) if ceo_message_id else None,
             "mode": composition_mode, "safety": _jsonb(safety_result), "timings": _jsonb(stage_timings),
             "done": completed_at, "billing": _jsonb(billing)},
        )
        return result.rowcount == 1


def list_open_ceo_runs(tenant_id: UUID, investigation_id: UUID) -> list[dict[str, Any]]:
    """RUNNING conversational CEO runs of one investigation (the seller's turns; SYSTEM runs are not this recovery's business)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT id, investigation_id, started_at FROM agent_run WHERE investigation_id = :inv AND agent_id = 'CEO' AND trigger_type = 'CONVERSATIONAL' AND status = 'RUNNING' ORDER BY started_at"),
            {"inv": str(investigation_id)},
        )
        return [dict(r._mapping) for r in rows]


def investigations_with_open_ceo_runs(tenant_id: UUID) -> list[UUID]:
    with tenant_scope(tenant_id) as conn:
        return [r[0] for r in conn.execute(text("SELECT DISTINCT investigation_id FROM agent_run WHERE agent_id = 'CEO' AND trigger_type = 'CONVERSATIONAL' AND status = 'RUNNING' AND investigation_id IS NOT NULL"))]


_LATE_LEGS_FROM = (
    "FROM agent_run c JOIN agent_run p ON p.id = c.parent_run_id "
    "WHERE p.agent_id = 'CEO' AND p.trigger_type = 'CONVERSATIONAL' AND p.status NOT IN ('QUEUED', 'RUNNING') AND c.status IN ('QUEUED', 'RUNNING')"
)


def list_late_legs(tenant_id: UUID, investigation_id: UUID) -> list[dict[str, Any]]:
    """Legs still QUEUED/RUNNING although the CEO turn that started them has ended (the soft leg deadline passed and the turn answered without them)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(f"SELECT c.id, c.agent_id, c.trigger_ref, c.started_at, c.parent_run_id {_LATE_LEGS_FROM} AND p.investigation_id = :inv ORDER BY c.started_at"),
            {"inv": str(investigation_id)},
        )
        return [dict(r._mapping) for r in rows]


def investigations_with_late_legs(tenant_id: UUID) -> list[UUID]:
    with tenant_scope(tenant_id) as conn:
        return [r[0] for r in conn.execute(text(f"SELECT DISTINCT p.investigation_id {_LATE_LEGS_FROM} AND p.investigation_id IS NOT NULL"))]


def get_turn_for_run(tenant_id: UUID, run_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT * FROM investigation_turn WHERE agent_run_id = :r"), {"r": str(run_id)}).first()
        return dict(row._mapping) if row is not None else None


def find_turn_by_request_key(tenant_id: UUID, investigation_id: UUID, request_key: str) -> dict[str, Any] | None:
    """The turn a submission key already produced in THIS investigation, if any (the key lives in the turn's `classifier_result`; no schema is involved).
    The caller holds the investigation's turn lock, which is what makes check-then-act race-free."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT * FROM investigation_turn WHERE investigation_id = :inv AND classifier_result->>'requestKey' = :k ORDER BY created_at LIMIT 1"),
            {"inv": str(investigation_id), "k": request_key},
        ).first()
        return dict(row._mapping) if row is not None else None


def get_turn(tenant_id: UUID, turn_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text("SELECT * FROM investigation_turn WHERE id = :id"), {"id": str(turn_id)}).first()
        return dict(row._mapping) if row is not None else None


def list_turns(tenant_id: UUID, investigation_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT * FROM investigation_turn WHERE investigation_id = :inv ORDER BY created_at, id"),
            {"inv": str(investigation_id)},
        )
        return [dict(r._mapping) for r in rows]


# ------------------------------------------------------------------------------ findings
def insert_finding(
    tenant_id: UUID,
    investigation_id: UUID,
    *,
    turn_id: UUID,
    source: str,
    action_key: str,
    status: str,
    agent_run_id: UUID | None = None,
    figure_refs: Sequence[Mapping[str, Any]] = (),
    report_ref: Mapping[str, Any] | None = None,
    gap_reason: str | None = None,
    presentation: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> UUID:
    """Appends one finding: refs and pointers, plus an optional display snapshot (`presentation`, spec R7 as amended) — formatted copies of values
    that were resolved through their refs, never a value the CEO computed. The table is append-only for the app role (no UPDATE), so the snapshot
    is written once, here, and can never be rewritten. The turn must belong to the SAME investigation in the SAME tenant."""
    finding_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        _require_investigation(conn, investigation_id)
        owner = conn.execute(
            text("SELECT investigation_id FROM investigation_turn WHERE id = :id"), {"id": str(turn_id)}
        ).first()
        if owner is None or str(owner[0]) != str(investigation_id):
            raise InvestigationNotFound(f"turn {turn_id} is not part of investigation {investigation_id}")
        if agent_run_id is not None:
            _require_visible(conn, "agent_run", agent_run_id)
        conn.execute(
            text(
                "INSERT INTO investigation_finding (id, tenant_id, investigation_id, turn_id, agent_run_id, source, "
                "action_key, status, figure_refs, report_ref, gap_reason, presentation, created_at) VALUES (:id, :tenant, :inv, "
                ":turn, :run, :source, :key, :status, CAST(:refs AS jsonb), CAST(:report AS jsonb), :gap, CAST(:presentation AS jsonb), :at)"
            ),
            {"id": str(finding_id), "tenant": str(tenant_id), "inv": str(investigation_id), "turn": str(turn_id),
             "run": str(agent_run_id) if agent_run_id else None, "source": source, "key": action_key, "status": status,
             "refs": json.dumps(list(figure_refs), default=str), "report": _jsonb(report_ref), "gap": gap_reason,
             "presentation": _jsonb(presentation), "at": _now(now)},
        )
    return finding_id


def list_findings(tenant_id: UUID, investigation_id: UUID, *, turn_id: UUID | None = None) -> list[dict[str, Any]]:
    """Findings oldest-first. Includes findings from agents that have since been detached — they are historical
    evidence and are never filtered out by attachment (spec resolved Q23)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                "SELECT id, turn_id, agent_run_id, source, action_key, status, figure_refs, report_ref, gap_reason, "
                "presentation, created_at FROM investigation_finding WHERE investigation_id = :inv "
                "AND (CAST(:turn AS uuid) IS NULL OR turn_id = :turn) ORDER BY created_at, id"
            ),
            {"inv": str(investigation_id), "turn": str(turn_id) if turn_id else None},
        )
        return [dict(r._mapping) for r in rows]


# ------------------------------------------------------------------------------ attachments (spec 6.34)
def insert_attachment(
    tenant_id: UUID, investigation_id: UUID, *, filename: str, detected_type: str, content: bytes, sha256: str, extraction_status: str, extraction_note: str | None,
    extracted_text: str | None, created_by: UUID | None, now: datetime | None = None,
) -> UUID:
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        _require_investigation(conn, investigation_id)  # the parent must be visible in THIS tenant: a foreign investigation id is a plain not-found
        conn.execute(
            text("INSERT INTO investigation_attachment (id, tenant_id, investigation_id, filename, detected_type, byte_size, sha256, content, extraction_status, extraction_note, "
                 "extracted_text, created_by, created_at) VALUES (:id, :t, :inv, :fn, :ty, :sz, :sha, :c, :st, :note, :txt, :by, :at)"),
            {"id": str(new_id), "t": str(tenant_id), "inv": str(investigation_id), "fn": filename[:255], "ty": detected_type, "sz": len(content), "sha": sha256, "c": content,
             "st": extraction_status, "note": extraction_note, "txt": extracted_text, "by": str(created_by) if created_by else None, "at": _now(now)},
        )
    return new_id


def get_attachment_contents(tenant_id: UUID, investigation_id: UUID, ids: Sequence[UUID]) -> list[dict[str, Any]]:
    """The bytes of the named attachments of THIS investigation in THIS tenant (an id that is foreign, from another conversation or unknown is simply absent)."""
    if not ids:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT id, filename, detected_type, sha256, content FROM investigation_attachment WHERE investigation_id = :inv AND id = ANY(CAST(:ids AS uuid[])) ORDER BY created_at"),
            {"inv": str(investigation_id), "ids": [str(i) for i in ids]},
        )
        return [{**dict(r._mapping), "content": bytes(r._mapping["content"])} for r in rows]


def latest_attachments(tenant_id: UUID, investigation_id: UUID, limit: int = 1) -> list[dict[str, Any]]:
    """The most recently stored attachment(s) of THIS investigation in THIS tenant, newest first, without their bytes (attachment continuity across turns)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT id, filename, detected_type, byte_size, sha256, extraction_status, extraction_note, extracted_text, created_at FROM investigation_attachment "
                 "WHERE investigation_id = :inv ORDER BY created_at DESC LIMIT :n"),
            {"inv": str(investigation_id), "n": limit},
        )
        return [dict(r._mapping) for r in rows]


def find_attachment_by_sha(tenant_id: UUID, investigation_id: UUID, sha256: str) -> dict[str, Any] | None:
    """The attachment of THIS investigation (and tenant) with exactly this content, if one is already stored: attaching the same file twice (a double click, a retry after a
    lost response) gives back the first one instead of storing the bytes again."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id, filename, detected_type, byte_size, extraction_status, extraction_note FROM investigation_attachment "
                 "WHERE investigation_id = :inv AND sha256 = :sha ORDER BY created_at LIMIT 1"),
            {"inv": str(investigation_id), "sha": sha256},
        ).first()
    return dict(row._mapping) if row else None


def get_attachments(tenant_id: UUID, investigation_id: UUID, ids: Sequence[UUID]) -> list[dict[str, Any]]:
    """The named attachments of THIS investigation in THIS tenant, without their bytes. An id that is foreign, from another investigation or unknown is simply absent
    (the caller compares counts and refuses): a reference is never trusted for existing."""
    if not ids:
        return []
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text("SELECT id, filename, detected_type, byte_size, sha256, extraction_status, extraction_note, extracted_text, created_at FROM investigation_attachment "
                 "WHERE investigation_id = :inv AND id = ANY(CAST(:ids AS uuid[])) ORDER BY created_at"),
            {"inv": str(investigation_id), "ids": [str(i) for i in ids]},
        )
        return [dict(r._mapping) for r in rows]


def get_attachment_meta(tenant_id: UUID, attachment_id: UUID) -> dict[str, Any] | None:
    """One attachment's metadata (no bytes) by id, under this tenant's RLS - used to re-resolve a stored plan's data basis. Another tenant's id is simply absent."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id, investigation_id, filename, detected_type, sha256, created_at FROM investigation_attachment WHERE id = :id"), {"id": str(attachment_id)},
        ).first()
    return dict(row._mapping) if row else None
