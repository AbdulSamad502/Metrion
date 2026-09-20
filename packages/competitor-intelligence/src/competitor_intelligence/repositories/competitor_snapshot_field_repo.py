"""competitor_snapshot_field — §5 (NEW). Per-field provenance and merge-conflict tracking;
one row per field per snapshot (unique on snapshot_id, field_name). Depends on Step 3's
migration creating this table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import text

from competitor_intelligence.evidence.merge import MergedField
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.types import Confidence


def replace_fields(tenant_id: UUID, snapshot_id: UUID, fields: Sequence[MergedField]) -> None:
    """Upserts on `(snapshot_id, field_name)` — this is called both at initial snapshot
    creation (no existing rows) and again, with the full corrected field set, from
    `research_run.submit_manual_correction` (rows already exist and must be updated in
    place, never duplicated — that's what the `unique(snapshot_id, field_name)` constraint
    is there to catch)."""
    now = datetime.now(timezone.utc)
    with tenant_scope(tenant_id) as conn:
        for f in fields:
            conn.execute(
                text(
                    """
                    INSERT INTO competitor_snapshot_field (
                      tenant_id, snapshot_id, field_name, value, source, confidence,
                      evidence_id, conflict, conflict_values, set_at
                    ) VALUES (
                      :tenant_id, :snapshot_id, :field_name, CAST(:value AS jsonb), :source, :confidence,
                      :evidence_id, :conflict, CAST(:conflict_values AS jsonb), :set_at
                    )
                    ON CONFLICT (snapshot_id, field_name) DO UPDATE SET
                      value = EXCLUDED.value, source = EXCLUDED.source, confidence = EXCLUDED.confidence,
                      evidence_id = EXCLUDED.evidence_id, conflict = EXCLUDED.conflict,
                      conflict_values = EXCLUDED.conflict_values, set_at = EXCLUDED.set_at
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "snapshot_id": str(snapshot_id),
                    "field_name": f.field_name,
                    "value": json.dumps(f.value),
                    "source": f.source.value if f.source else None,
                    "confidence": f.confidence.value,
                    "evidence_id": str(f.evidence_id) if f.evidence_id else None,
                    "conflict": f.conflict,
                    "conflict_values": json.dumps(list(f.conflict_values)) if f.conflict_values else None,
                    "set_at": now,
                },
            )


def update_field(
    tenant_id: UUID,
    snapshot_id: UUID,
    field_name: str,
    *,
    value: Any,
    source: Confidence,
    confidence: Confidence,
) -> None:
    """A manual correction (§5.3 rule 4) — always supersedes, in place, per the `unique
    (snapshot_id, field_name)` constraint. Never a new row for the same field."""
    now = datetime.now(timezone.utc)
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO competitor_snapshot_field (
                  tenant_id, snapshot_id, field_name, value, source, confidence,
                  evidence_id, conflict, conflict_values, set_at
                ) VALUES (
                  :tenant_id, :snapshot_id, :field_name, CAST(:value AS jsonb), :source, :confidence,
                  NULL, false, NULL, :set_at
                )
                ON CONFLICT (snapshot_id, field_name) DO UPDATE SET
                  value = EXCLUDED.value, source = EXCLUDED.source, confidence = EXCLUDED.confidence,
                  evidence_id = NULL, conflict = false, conflict_values = NULL, set_at = EXCLUDED.set_at
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "snapshot_id": str(snapshot_id),
                "field_name": field_name,
                "value": json.dumps(value),
                "source": source.value,
                "confidence": confidence.value,
                "set_at": now,
            },
        )


def get_fields(tenant_id: UUID, snapshot_id: UUID) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                """
                SELECT field_name, value, source, confidence, evidence_id, conflict, conflict_values, set_at
                FROM competitor_snapshot_field
                WHERE tenant_id = :tenant_id AND snapshot_id = :snapshot_id
                """
            ),
            {"tenant_id": str(tenant_id), "snapshot_id": str(snapshot_id)},
        ).mappings()
        return [dict(r) for r in rows]


def get_fields_as_merged(tenant_id: UUID, snapshot_id: UUID) -> tuple[MergedField, ...]:
    """Rebuilds `MergedField` objects from persisted rows — the reverse of `replace_fields` —
    so a follow-up manual correction can be layered on with the exact same
    `evidence.merge.apply_manual_entries` function used at initial submission time.

    `evidence_id` comes back from psycopg already as a `uuid.UUID` (or `None`), not a string —
    it must NOT be re-wrapped in `UUID(...)`, which raises on a non-string/bytes/int argument.
    """
    from competitor_intelligence.types import Confidence as _Confidence

    rows = get_fields(tenant_id, snapshot_id)
    return tuple(
        MergedField(
            field_name=r["field_name"],
            value=r["value"],
            source=_Confidence(r["source"]) if r["source"] else None,
            confidence=_Confidence(r["confidence"]),
            evidence_id=r["evidence_id"],
            conflict=r["conflict"],
            conflict_values=tuple(r["conflict_values"]) if r["conflict_values"] else None,
        )
        for r in rows
    )
