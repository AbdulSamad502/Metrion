"""Held duplicate rows (docs/specs/cfo-data-intelligence.md §6.3a): kept verbatim so the seller can decide; never part of a figure.

Append-only (SELECT and INSERT for the application role). A held row is resolved by one `held_row_resolution` row; the unique index allows exactly one decision per
held row. KEEP_EARLIER and DISCARD change no figure — the earlier data already stands and the held row was never posted — so neither bumps the read-model version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from data_foundation.repositories.tenant_context import tenant_scope

ACTIONS = ("KEEP_EARLIER", "DISCARD")
DEFERRED_ACTIONS = ("SUPERSEDE_WITH_THIS", "KEEP_BOTH_WITH_REFERENCE")


class HeldRowError(ValueError):
    """A request the held-row rules refuse; the message is safe to show the seller."""


@dataclass(frozen=True, slots=True)
class NewHeldRow:
    row_number: int
    kind: str  # CONFLICT | AMBIGUOUS
    rule: str
    reason: str
    earlier_row: int | None
    row_values: dict[str, Any]


def insert_many_on(conn: Connection, tenant_id: UUID, *, ingestion_run_id: UUID, report_file_id: UUID, marketplace: str, rows: list[NewHeldRow]) -> None:
    for r in rows:
        conn.execute(
            text("INSERT INTO held_row (id, tenant_id, ingestion_run_id, report_file_id, marketplace, row_number, kind, rule, reason, earlier_row, row_values) "
                 "VALUES (:id, :t, :run, :rf, :m, :n, :k, :rule, :reason, :er, CAST(:vals AS jsonb))"),
            {"id": str(uuid4()), "t": str(tenant_id), "run": str(ingestion_run_id), "rf": str(report_file_id), "m": marketplace, "n": r.row_number, "k": r.kind,
             "rule": r.rule, "reason": r.reason, "er": r.earlier_row, "vals": json.dumps(r.row_values, default=str)},
        )


def list_for_file(tenant_id: UUID, report_file_id: UUID, *, status: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int, int]:
    """(rows, total, held_total_unresolved) newest run first, then row number. status: HELD | RESOLVED | ALL."""
    where = "h.tenant_id = :t AND h.report_file_id = :rf"
    if status == "HELD":
        where += " AND r.id IS NULL"
    elif status == "RESOLVED":
        where += " AND r.id IS NOT NULL"
    base = "FROM held_row h LEFT JOIN held_row_resolution r ON r.tenant_id = h.tenant_id AND r.held_row_id = h.id WHERE " + where
    args = {"t": str(tenant_id), "rf": str(report_file_id)}
    with tenant_scope(tenant_id) as conn:
        total = int(conn.execute(text("SELECT count(*) " + base), args).scalar_one())
        unresolved = int(conn.execute(text("SELECT count(*) FROM held_row h LEFT JOIN held_row_resolution r ON r.tenant_id = h.tenant_id AND r.held_row_id = h.id "
                                           "WHERE h.tenant_id = :t AND h.report_file_id = :rf AND r.id IS NULL"), args).scalar_one())
        rows = conn.execute(
            text("SELECT h.id, h.row_number, h.kind, h.rule, h.reason, h.earlier_row, h.row_values, r.action, r.note, r.created_at " + base
                 + " ORDER BY h.created_at DESC, h.row_number LIMIT :lim OFFSET :off"),
            {**args, "lim": page_size, "off": (page - 1) * page_size}).all()
    out = [{"id": str(i), "rowNumber": n, "kind": k, "rule": rule, "reason": reason, "earlierRow": er, "values": vals, "resolution": a, "resolutionNote": note,
            "resolvedAt": ra.isoformat() if ra else None} for i, n, k, rule, reason, er, vals, a, note, ra in rows]
    return out, total, unresolved


def resolve(tenant_id: UUID, held_row_id: UUID, action: str, resolved_by: UUID, note: str | None = None) -> UUID:
    if action in DEFERRED_ACTIONS:
        raise HeldRowError("replacing earlier data, or keeping both rows with a reference, is not available yet; for now keep the earlier row or discard this one")
    if action not in ACTIONS:
        raise HeldRowError(f"action must be one of {list(ACTIONS)}")
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        found = conn.execute(text("SELECT 1 FROM held_row WHERE tenant_id = :t AND id = :id"), {"t": str(tenant_id), "id": str(held_row_id)}).first()
        if found is None:
            raise HeldRowError("held row not found")
        done = conn.execute(text("SELECT 1 FROM held_row_resolution WHERE tenant_id = :t AND held_row_id = :id"), {"t": str(tenant_id), "id": str(held_row_id)}).first()
        if done is not None:
            raise HeldRowError("this held row has already been decided")
        conn.execute(text("INSERT INTO held_row_resolution (id, tenant_id, held_row_id, action, note, resolved_by) VALUES (:id, :t, :h, :a, :n, :by)"),
                     {"id": str(new_id), "t": str(tenant_id), "h": str(held_row_id), "a": action, "n": note, "by": str(resolved_by)})
    return new_id
