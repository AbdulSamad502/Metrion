"""app_user repository — auth.md §5.1. `app_user` is an identity root (no `tenant_id`, no
RLS), same reasoning as `tenant_repo.py`."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from backend.db import engine

_GET_BY_CLERK_USER_ID_SQL = text(
    "SELECT id, clerk_user_id, email, email_verified, auth_provider, display_name, created_at "
    "FROM app_user WHERE clerk_user_id = :clerk_user_id"
)

_INSERT_SQL = text(
    """
    INSERT INTO app_user (id, clerk_user_id, email, email_verified, auth_provider, display_name, created_at)
    VALUES (:id, :clerk_user_id, :email, :email_verified, :auth_provider, :display_name, now())
    """
)

_UPDATE_SQL = text(
    """
    UPDATE app_user
    SET email = :email, email_verified = :email_verified, auth_provider = :auth_provider,
        display_name = :display_name
    WHERE clerk_user_id = :clerk_user_id
    """
)


def get_by_clerk_user_id(clerk_user_id: str) -> dict[str, object] | None:
    with engine().connect() as conn:
        row = conn.execute(_GET_BY_CLERK_USER_ID_SQL, {"clerk_user_id": clerk_user_id}).first()
        return dict(row._mapping) if row is not None else None


def upsert(
    *,
    clerk_user_id: str,
    email: str,
    email_verified: bool,
    auth_provider: str,
    display_name: str | None,
) -> UUID:
    """Idempotent by `clerk_user_id` (D6: webhook handlers and login-time reconciliation
    both call this, and delivery may be out of order or duplicated — A3)."""
    existing = get_by_clerk_user_id(clerk_user_id)
    with engine().begin() as conn:
        if existing is None:
            user_id = uuid4()
            conn.execute(
                _INSERT_SQL,
                {
                    "id": str(user_id),
                    "clerk_user_id": clerk_user_id,
                    "email": email,
                    "email_verified": email_verified,
                    "auth_provider": auth_provider,
                    "display_name": display_name,
                },
            )
            return user_id
        conn.execute(
            _UPDATE_SQL,
            {
                "clerk_user_id": clerk_user_id,
                "email": email,
                "email_verified": email_verified,
                "auth_provider": auth_provider,
                "display_name": display_name,
            },
        )
        return UUID(str(existing["id"]))
