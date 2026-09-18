"""membership repository — auth.md §5.1, §5.2. Tenant-owned, RLS-protected, so every call
here goes through `tenant_context.tenant_scope()` — never the plain engine.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.auth.permissions import DENY_ALL_GRID, OWNER_ROLE
from backend.tenant_context import tenant_scope

_GET_BY_TENANT_AND_USER_SQL = text(
    "SELECT id, tenant_id, app_user_id, role, status, permissions "
    "FROM membership WHERE tenant_id = :tenant_id AND app_user_id = :app_user_id"
)

_INSERT_SQL = text(
    """
    INSERT INTO membership (id, tenant_id, app_user_id, role, status, permissions, joined_at)
    VALUES (:id, :tenant_id, :app_user_id, :role, :status, CAST(:permissions AS jsonb), now())
    """
)

_UPDATE_ROLE_STATUS_SQL = text(
    "UPDATE membership SET role = :role, status = :status WHERE tenant_id = :tenant_id AND app_user_id = :app_user_id"
)

_UPDATE_PERMISSIONS_SQL = text(
    "UPDATE membership SET permissions = CAST(:permissions AS jsonb) "
    "WHERE tenant_id = :tenant_id AND app_user_id = :app_user_id"
)


def get_by_tenant_and_user(tenant_id: UUID, app_user_id: UUID) -> dict[str, object] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _GET_BY_TENANT_AND_USER_SQL,
            {"tenant_id": str(tenant_id), "app_user_id": str(app_user_id)},
        ).first()
        return dict(row._mapping) if row is not None else None


def create_owner(tenant_id: UUID, app_user_id: UUID) -> UUID:
    """§6.2: the user who completes onboarding becomes OWNER/ACTIVE. OWNER's `permissions`
    grid is stored but never consulted (§5.2: OWNER holds every permission implicitly)."""
    membership_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(membership_id),
                "tenant_id": str(tenant_id),
                "app_user_id": str(app_user_id),
                "role": OWNER_ROLE,
                "status": "ACTIVE",
                "permissions": json.dumps(DENY_ALL_GRID),
            },
        )
    return membership_id


def upsert_partner(tenant_id: UUID, app_user_id: UUID, *, role: str, status: str) -> None:
    """D6/D4: reconciles a partner's role/status from Clerk (invitation acceptance,
    removal). A brand-new partner gets deny-all permissions (D4) — the OWNER grants
    explicitly afterward via `set_permissions`."""
    existing = get_by_tenant_and_user(tenant_id, app_user_id)
    with tenant_scope(tenant_id) as conn:
        if existing is None:
            conn.execute(
                _INSERT_SQL,
                {
                    "id": str(uuid4()),
                    "tenant_id": str(tenant_id),
                    "app_user_id": str(app_user_id),
                    "role": role,
                    "status": status,
                    "permissions": json.dumps(DENY_ALL_GRID),
                },
            )
        else:
            conn.execute(
                _UPDATE_ROLE_STATUS_SQL,
                {"tenant_id": str(tenant_id), "app_user_id": str(app_user_id), "role": role, "status": status},
            )


def set_permissions(tenant_id: UUID, app_user_id: UUID, permissions: dict[str, object]) -> None:
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _UPDATE_PERMISSIONS_SQL,
            {"tenant_id": str(tenant_id), "app_user_id": str(app_user_id), "permissions": json.dumps(permissions)},
        )
