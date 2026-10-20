"""business_profile persistence — docs/specs/business-profile.md §5. One row per tenant, upserted; FORCE RLS beneath the application filter. The database CHECKs re-enforce
every rule the service validates, so a row can never exist with a missing or blank field."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.tenant_context import tenant_scope

_COLS = "business_name, description, categories, marketplaces, price_segment, target_customer, business_stage, state, created_at, updated_at"


def get(tenant_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text(f"SELECT {_COLS} FROM business_profile WHERE tenant_id = :t"), {"t": str(tenant_id)}).mappings().first()
        return dict(row) if row is not None else None


def upsert(tenant_id: UUID, p: dict[str, Any], user_id: UUID | None) -> dict[str, Any]:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text(
                "INSERT INTO business_profile (tenant_id, business_name, description, categories, marketplaces, price_segment, target_customer, business_stage, state, updated_by) "
                "VALUES (:t, :business_name, :description, :categories, :marketplaces, :price_segment, :target_customer, :business_stage, :state, :by) "
                "ON CONFLICT (tenant_id) DO UPDATE SET business_name = EXCLUDED.business_name, description = EXCLUDED.description, categories = EXCLUDED.categories, "
                "marketplaces = EXCLUDED.marketplaces, price_segment = EXCLUDED.price_segment, target_customer = EXCLUDED.target_customer, "
                "business_stage = EXCLUDED.business_stage, state = EXCLUDED.state, updated_by = EXCLUDED.updated_by, updated_at = now() "
                f"RETURNING {_COLS}"
            ),
            {"t": str(tenant_id), "by": str(user_id) if user_id else None, **p},
        ).mappings().first()
        assert row is not None
        return dict(row)
