"""`cmo_platform_config` reads (spec §6.8.5, C16). Read-only: the application role cannot write it.

Resolution (the `reconciliation_tolerance_config` pattern): for each key, a TENANT row beats the
platform default (`tenant_id IS NULL`); within a scope the latest `effective_from <= as_of` wins.
A key with no row is simply absent from the result - the loaders turn absence into CONFIG_MISSING;
this module never supplies a default.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, bindparam, text

_SQL = text(
    """
    SELECT tenant_id, key, value, effective_from
    FROM cmo_platform_config
    WHERE key IN :keys
      AND effective_from <= :as_of
      AND (tenant_id IS NULL OR tenant_id = :tenant_id)
    """
).bindparams(bindparam("keys", expanding=True))


def load_config_values(conn: Connection, tenant_id: UUID, keys: Sequence[str], as_of: date) -> dict[str, Any]:
    rows = conn.execute(_SQL, {"keys": list(keys), "as_of": as_of, "tenant_id": tenant_id}).all()
    best: dict[str, tuple[int, date, Any]] = {}
    for row_tenant, key, value, effective_from in rows:
        rank = (1 if row_tenant is not None else 0, effective_from)
        current = best.get(key)
        if current is None or rank > (current[0], current[1]):
            best[key] = (rank[0], effective_from, value)
    return {k: v[2] for k, v in best.items()}
