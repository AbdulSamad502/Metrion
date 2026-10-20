"""tenant repository — auth.md §5.1. `tenant` carries no `tenant_id` column and no RLS
policy (it IS the tenant identity root), so this goes through the plain engine, never
`tenant_scope()`."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from backend.db import engine

_GET_BY_CLERK_ORG_ID_SQL = text(
    "SELECT id, clerk_org_id, business_name, country, currency, timezone, status, created_at "
    "FROM tenant WHERE clerk_org_id = :clerk_org_id"
)

_INSERT_SQL = text(
    """
    INSERT INTO tenant (id, clerk_org_id, business_name, status, created_at)
    VALUES (:id, :clerk_org_id, :business_name, 'ACTIVE', now())
    """
)

_DELETE_SQL = text("DELETE FROM tenant WHERE id = :id")


def get_by_clerk_org_id(clerk_org_id: str) -> dict[str, object] | None:
    with engine().connect() as conn:
        row = conn.execute(_GET_BY_CLERK_ORG_ID_SQL, {"clerk_org_id": clerk_org_id}).first()
        return dict(row._mapping) if row is not None else None


def create(*, clerk_org_id: str, business_name: str) -> UUID:
    """§6.2: business name is mandatory (O1) and is the only field this accepts — GSTIN and
    marketplace fields are never collected at signup (O3)."""
    tenant_id = uuid4()
    with engine().begin() as conn:
        conn.execute(
            _INSERT_SQL,
            {"id": str(tenant_id), "clerk_org_id": clerk_org_id, "business_name": business_name},
        )
    return tenant_id


def delete(tenant_id: UUID) -> None:
    """Used only for the §6.2 atomic-rollback path when tenant creation succeeds but the
    caller determines the overall onboarding transaction must be undone."""
    with engine().begin() as conn:
        conn.execute(_DELETE_SQL, {"id": str(tenant_id)})


def get_business_name(tenant_id: UUID) -> str | None:
    """The workspace name given at account creation (used only to pre-fill the business-profile step)."""
    with engine().connect() as conn:
        row = conn.execute(text("SELECT business_name FROM tenant WHERE id = :id"), {"id": str(tenant_id)}).first()
        return str(row[0]) if row is not None and row[0] else None
