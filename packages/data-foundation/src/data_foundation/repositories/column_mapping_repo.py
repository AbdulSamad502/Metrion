"""column_mapping + column_mapping_field repository (cfo-data-intelligence.md §5, §6.4).

A mapping is PROPOSED (by a model, an adapter-derived rule, or the seller), becomes CONFIRMED only when a
seller resolves every field, and is then reused automatically for the same file shape (fingerprint). At most
one CONFIRMED mapping exists per fingerprint (a partial unique index); confirming a new version supersedes the
old one in the same transaction. `verified` is never set here — only a Metrion reviewer, against a real
export, may do that (data-foundation §7), so mapped data stays PROVISIONAL.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from data_foundation.repositories.tenant_context import tenant_scope

_RESOLVED = frozenset({"AUTO_ACCEPTED_BY_RULES", "SELLER_CONFIRMED", "SELLER_OVERRIDDEN"})


class MappingNotResolved(Exception):
    """Confirmation refused: at least one field has no resolved decision (or was rejected)."""

    def __init__(self, unresolved: Sequence[int]) -> None:
        self.unresolved = tuple(unresolved)
        super().__init__(f"fields at column positions {list(unresolved)} are not resolved")


@dataclass(frozen=True, slots=True)
class FieldRow:
    source_column: str
    source_column_index: int
    canonical_field: str
    component_code: str | None
    transform: str
    tax_inclusion: str | None
    sign_convention: str | None
    decision: str  # PENDING at proposal time
    evidence: Mapping[str, Any]


def create_proposal(
    tenant_id: UUID,
    *,
    fingerprint: str,
    report_kind: str,
    marketplace: str | None,
    sheet_name: str | None,
    header_row: int,
    proposed_by: str,
    fields: Sequence[FieldRow],
    evidence: Mapping[str, Any] | None = None,
) -> UUID:
    mapping_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        version = conn.execute(
            text("SELECT COALESCE(MAX(version), 0) + 1 FROM column_mapping WHERE tenant_id = :t AND fingerprint = :f"),
            {"t": str(tenant_id), "f": fingerprint},
        ).scalar_one()
        conn.execute(
            text(
                """INSERT INTO column_mapping (id, tenant_id, fingerprint, version, report_kind, marketplace, sheet_name, header_row, status, proposed_by, evidence)
                   VALUES (:id, :t, :f, :v, :k, :m, :s, :h, 'PROPOSED', :p, CAST(:ev AS jsonb))"""
            ),
            {"id": str(mapping_id), "t": str(tenant_id), "f": fingerprint, "v": version, "k": report_kind, "m": marketplace,
             "s": sheet_name, "h": header_row, "p": proposed_by, "ev": json.dumps(dict(evidence or {}))},
        )
        if fields:
            conn.execute(
                text(
                    """INSERT INTO column_mapping_field
                         (id, tenant_id, mapping_id, source_column, source_column_index, canonical_field, component_code, transform,
                          tax_inclusion, sign_convention, decision, evidence)
                       VALUES (:id, :t, :m, :c, :i, :cf, :cc, :tr, :tx, :sg, :d, CAST(:e AS jsonb))"""
                ),
                [{"id": str(uuid4()), "t": str(tenant_id), "m": str(mapping_id), "c": f.source_column, "i": f.source_column_index,
                  "cf": f.canonical_field, "cc": f.component_code, "tr": f.transform, "tx": f.tax_inclusion, "sg": f.sign_convention,
                  "d": f.decision, "e": json.dumps(dict(f.evidence))} for f in fields],
            )
    return mapping_id


def get_mapping(tenant_id: UUID, mapping_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        m = conn.execute(text("SELECT * FROM column_mapping WHERE tenant_id = :t AND id = :id"), {"t": str(tenant_id), "id": str(mapping_id)}).first()
        if m is None:
            return None
        fields = conn.execute(
            text("SELECT * FROM column_mapping_field WHERE tenant_id = :t AND mapping_id = :id ORDER BY source_column_index"),
            {"t": str(tenant_id), "id": str(mapping_id)},
        )
        out = dict(m._mapping)
        out["fields"] = [dict(f._mapping) for f in fields]
        return out


def find_confirmed(tenant_id: UUID, fingerprint: str) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id FROM column_mapping WHERE tenant_id = :t AND fingerprint = :f AND status = 'CONFIRMED'"),
            {"t": str(tenant_id), "f": fingerprint},
        ).first()
    return get_mapping(tenant_id, UUID(str(row[0]))) if row else None


def confirm(
    tenant_id: UUID,
    mapping_id: UUID,
    *,
    confirmed_by: UUID,
    field_decisions: Mapping[int, str],
    now: datetime,
) -> None:
    """Record the seller's per-field decisions (keyed by column position) and confirm the mapping. Raises
    `MappingNotResolved` — and changes nothing — unless every field ends up with a resolved decision."""
    with tenant_scope(tenant_id) as conn:
        current = conn.execute(
            text("SELECT source_column_index, decision FROM column_mapping_field WHERE tenant_id = :t AND mapping_id = :m"),
            {"t": str(tenant_id), "m": str(mapping_id)},
        ).all()
        final = {int(i): field_decisions.get(int(i), d) for i, d in current}
        unresolved = sorted(i for i, d in final.items() if d not in _RESOLVED)
        if unresolved or not final:
            raise MappingNotResolved(unresolved)
        for idx, decision in final.items():
            conn.execute(
                text("UPDATE column_mapping_field SET decision = :d WHERE tenant_id = :t AND mapping_id = :m AND source_column_index = :i"),
                {"d": decision, "t": str(tenant_id), "m": str(mapping_id), "i": idx},
            )
        fp = conn.execute(text("SELECT fingerprint FROM column_mapping WHERE tenant_id = :t AND id = :id"), {"t": str(tenant_id), "id": str(mapping_id)}).scalar_one()
        conn.execute(
            text("UPDATE column_mapping SET status = 'SUPERSEDED' WHERE tenant_id = :t AND fingerprint = :f AND status = 'CONFIRMED' AND id <> :id"),
            {"t": str(tenant_id), "f": fp, "id": str(mapping_id)},
        )
        conn.execute(
            text("UPDATE column_mapping SET status = 'CONFIRMED', confirmed_by = :u, confirmed_at = :now WHERE tenant_id = :t AND id = :id AND status = 'PROPOSED'"),
            {"u": str(confirmed_by), "now": now, "t": str(tenant_id), "id": str(mapping_id)},
        )


def reject(tenant_id: UUID, mapping_id: UUID) -> bool:
    with tenant_scope(tenant_id) as conn:
        res = conn.execute(
            text("UPDATE column_mapping SET status = 'REJECTED' WHERE tenant_id = :t AND id = :id AND status = 'PROPOSED'"),
            {"t": str(tenant_id), "id": str(mapping_id)},
        )
        return bool(res.rowcount)


def update_field(
    tenant_id: UUID,
    mapping_id: UUID,
    source_column_index: int,
    *,
    canonical_field: str,
    component_code: str | None,
    transform: str,
    tax_inclusion: str | None,
    sign_convention: str | None,
) -> bool:
    """Record the seller's edit of one field of a still-PROPOSED mapping. The caller (the mapping service) has
    already re-validated the edited mapping; a confirmed or rejected mapping is immutable here."""
    with tenant_scope(tenant_id) as conn:
        res = conn.execute(
            text(
                """UPDATE column_mapping_field f SET canonical_field = :cf, component_code = :cc, transform = :tr,
                          tax_inclusion = :tx, sign_convention = :sg
                   FROM column_mapping m
                   WHERE f.tenant_id = :t AND f.mapping_id = :m AND f.source_column_index = :i
                     AND m.id = f.mapping_id AND m.status = 'PROPOSED'"""
            ),
            {"cf": canonical_field, "cc": component_code, "tr": transform, "tx": tax_inclusion, "sg": sign_convention,
             "t": str(tenant_id), "m": str(mapping_id), "i": source_column_index},
        )
        return bool(res.rowcount)
