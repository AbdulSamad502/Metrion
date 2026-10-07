"""Read-only existence lookups the CEO provenance gate needs where no owning package already exposes a
`get`-by-id (spec §6.15 R3). Each function is tenant-scoped through `tenant_scope()`: a row that belongs to
another tenant is indistinguishable from a missing one (RLS), which is the correct, non-leaking answer.

No calculation, no write. The table names are fixed in the SQL — never interpolated from caller input.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.tenant_context import tenant_scope


def get_manual_adjustment(tenant_id: UUID, adjustment_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT id, target_type, target_ref, field, value, created_at, status FROM manual_adjustment WHERE id = :id"),
            {"id": str(adjustment_id)},
        ).first()
        return dict(row._mapping) if row is not None else None


def get_leak_finding(tenant_id: UUID, finding_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "SELECT id, marketplace, leak_category, severity, amount_paise, status, confidence, first_observed_at "
                "FROM leak_finding WHERE id = :id"
            ),
            {"id": str(finding_id)},
        ).first()
        return dict(row._mapping) if row is not None else None
