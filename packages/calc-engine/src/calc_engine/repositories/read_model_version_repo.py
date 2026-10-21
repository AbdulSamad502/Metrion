"""cfo_read_model_version — the cache-invalidation signal (cfo-query-planner.md D2, §6.4).

One monotone counter per tenant. Any write that changes canonical financial data bumps it **in the same
transaction** as the write (so a reader can never see new data under an old version, or the reverse); a
cached evidence packet is keyed by this number, so a bump makes every earlier key unreachable without an
explicit purge. A tenant with no row has version 0.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

from calc_engine.repositories.tenant_context import tenant_scope

_BUMP_SQL = text(
    """
    INSERT INTO cfo_read_model_version (tenant_id, data_version, updated_at)
    VALUES (:tenant_id, 1, now())
    ON CONFLICT (tenant_id) DO UPDATE
      SET data_version = cfo_read_model_version.data_version + 1, updated_at = now()
    RETURNING data_version
    """
)
_GET_SQL = text("SELECT data_version FROM cfo_read_model_version WHERE tenant_id = :tenant_id")


def bump_on(conn: Connection, tenant_id: UUID) -> int:
    """Increment on an ALREADY-OPEN `tenant_scope()` connection; returns the new version."""
    return int(conn.execute(_BUMP_SQL, {"tenant_id": str(tenant_id)}).scalar_one())


def bump(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return bump_on(conn, tenant_id)


def get(tenant_id: UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        v = conn.execute(_GET_SQL, {"tenant_id": str(tenant_id)}).scalar_one_or_none()
    return int(v) if v is not None else 0
