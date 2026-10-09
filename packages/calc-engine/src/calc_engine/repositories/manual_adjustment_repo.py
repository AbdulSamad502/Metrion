"""manual_adjustment repository — append-only, deterministic-engine.md §7.1.

Every write is an INSERT. There is no update()/delete() function here at all — not because
application logic declines to call one, but because the migration (20260917_0001) revokes
UPDATE and DELETE on this table from metrion_app at the grant level (auth.md-style
defence-in-depth: enforced by the database, not just trusted application code). A correction
is a new row whose `supersedes_id` points at the row it replaces.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from calc_engine.repositories.tenant_context import tenant_scope

_INSERT_SQL = text(
    """
    INSERT INTO manual_adjustment
        (id, tenant_id, target_type, target_ref, field, value, reason, created_by, created_at, supersedes_id, status)
    VALUES
        (:id, :tenant_id, :target_type, :target_ref, :field, CAST(:value AS jsonb), :reason, :created_by, :created_at, :supersedes_id, 'ACTIVE')
    """
)

# "Active" = status ACTIVE and not superseded by a later row. The table is append-only for the app role (no UPDATE), so a superseded row keeps status ACTIVE
# and is retired by the row that names it in `supersedes_id`; checking only `status` left both rows active (found in the 2026-10-10 security review).
_ACTIVE_FOR_TARGET_SQL = text(
    """
    SELECT id, target_type, target_ref, field, value, reason, created_by, created_at, supersedes_id, status
    FROM manual_adjustment
    WHERE target_type = :target_type AND target_ref = :target_ref AND field = :field AND status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM manual_adjustment newer WHERE newer.supersedes_id = manual_adjustment.id)
    ORDER BY created_at DESC
    """
)

_ACTIVE_FOR_TARGETS_SQL = text(
    """
    SELECT id, target_type, target_ref, field, value, reason, created_by, created_at, supersedes_id, status
    FROM manual_adjustment
    WHERE tenant_id = :tenant_id AND target_type = :target_type
      AND target_ref = ANY(CAST(:target_refs AS text[])) AND field = ANY(CAST(:fields AS text[]))
      AND status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM manual_adjustment newer WHERE newer.supersedes_id = manual_adjustment.id)
    ORDER BY created_at DESC
    """
)

_ACTIVE_BY_EXACT_FIELD_SQL = text(
    """
    SELECT id, target_type, target_ref, field, value, reason, created_by, created_at, supersedes_id, status
    FROM manual_adjustment
    WHERE field = :field AND status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM manual_adjustment newer WHERE newer.supersedes_id = manual_adjustment.id)
    ORDER BY created_at DESC
    """
)

_ACTIVE_BY_FIELD_PREFIX_SQL = text(
    """
    SELECT id, target_type, target_ref, field, value, reason, created_by, created_at, supersedes_id, status
    FROM manual_adjustment
    WHERE field LIKE :field_prefix ESCAPE '\\' AND status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM manual_adjustment newer WHERE newer.supersedes_id = manual_adjustment.id)
    ORDER BY created_at DESC
    """
)


def insert_adjustment(
    tenant_id: UUID,
    *,
    target_type: str,
    target_ref: str,
    field: str,
    value: Any,
    created_by: UUID,
    created_at: datetime,
    reason: str | None = None,
    supersedes_id: UUID | None = None,
) -> UUID:
    """Appends a new manual_adjustment row. `value` must already be JSON-serialisable — this
    repository does not interpret the §7.2.1 field registry's shapes, it only persists them."""
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        if supersedes_id is not None:
            # A row may retire only an earlier row of THIS tenant for the SAME target and field. A foreign or missing id is refused identically (no existence
            # oracle), and no cross-tenant reference is ever written (security review, 2026-10-10).
            found = conn.execute(
                text("SELECT 1 FROM manual_adjustment WHERE id = :id AND tenant_id = :t AND target_type = :tt AND target_ref = :tr AND field = :f"),
                {"id": str(supersedes_id), "t": str(tenant_id), "tt": target_type, "tr": target_ref, "f": field},
            ).first()
            if found is None:
                raise ValueError("supersedes_id does not name an earlier input of yours for this target and field")
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "target_type": target_type,
                "target_ref": target_ref,
                "field": field,
                "value": json.dumps(value),
                "reason": reason,
                "created_by": str(created_by),
                "created_at": created_at,
                "supersedes_id": str(supersedes_id) if supersedes_id else None,
            },
        )
    return new_id


def active_adjustments_for_target(
    tenant_id: UUID, *, target_type: str, target_ref: str, field: str
) -> list[dict[str, Any]]:
    """Returns ACTIVE rows for one (target_type, target_ref, field), newest first. A field
    with more than one ACTIVE row is a data anomaly this repository does not resolve —
    §7.1's "conflict is surfaced, not resolved" is a caller-level (formula/UI) concern."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            _ACTIVE_FOR_TARGET_SQL,
            {"target_type": target_type, "target_ref": target_ref, "field": field},
        )
        return [dict(row._mapping) for row in rows]


_TARGETS_CHUNK = 5000


def active_adjustments_for_targets(
    tenant_id: UUID, *, target_type: str, target_refs: Sequence[str], fields: Sequence[str]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Batch form of `active_adjustments_for_target`: ACTIVE rows for many `target_ref`s and
    several `field`s of ONE `target_type` in one round trip per chunk of refs, instead of one
    query per (target_ref, field). Returns `{(target_ref, field): [rows, newest first]}` — each
    list is exactly what `active_adjustments_for_target` returns for that pair, and a pair with
    no ACTIVE row is simply absent (callers use `.get(key, [])`). Same `manual_adjustment_
    tenant_target_idx` access path; `tenant_id` is also filtered explicitly (RLS still applies)."""
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    refs = list(dict.fromkeys(target_refs))
    field_list = list(dict.fromkeys(fields))
    if not refs or not field_list:
        return result
    with tenant_scope(tenant_id) as conn:
        for i in range(0, len(refs), _TARGETS_CHUNK):
            rows = conn.execute(
                _ACTIVE_FOR_TARGETS_SQL,
                {
                    "tenant_id": str(tenant_id),
                    "target_type": target_type,
                    "target_refs": refs[i : i + _TARGETS_CHUNK],
                    "fields": field_list,
                },
            )
            for row in rows:
                d = dict(row._mapping)
                result.setdefault((d["target_ref"], d["field"]), []).append(d)
    return result


def active_adjustments_by_field(
    tenant_id: UUID, *, field: str | None = None, field_prefix: str | None = None
) -> list[dict[str, Any]]:
    """Returns every ACTIVE row for this tenant matching either an exact `field` (e.g.
    `expense.budget`) or a `field` prefix (e.g. `expense.` to catch every §7.2.1
    `expense.<category>` pool at once), across ALL `target_type`/`target_ref` values — the
    broader query `active_adjustments_for_target` deliberately does not offer, since that
    function is scoped to one known target. Exactly one of `field`/`field_prefix` must be
    given. RLS-scoped via `tenant_scope`, same as every other function here. Newest first,
    same convention as `active_adjustments_for_target`; a caller that needs period filtering
    does it itself (`manual_adjustment` carries no period column of its own — see
    `cfo_actions.list_expenses`'s own docstring for why that filter happens in Python, not
    SQL, given the real stored shape)."""
    if (field is None) == (field_prefix is None):
        raise ValueError("exactly one of field or field_prefix must be given")
    with tenant_scope(tenant_id) as conn:
        if field is not None:
            rows = conn.execute(_ACTIVE_BY_EXACT_FIELD_SQL, {"field": field})
        else:
            escaped = field_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = conn.execute(_ACTIVE_BY_FIELD_PREFIX_SQL, {"field_prefix": f"{escaped}%"})
        return [dict(row._mapping) for row in rows]
