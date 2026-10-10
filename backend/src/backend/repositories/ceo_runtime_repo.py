"""Database primitives the CEO runtime needs and must not write itself (`backend/ceo` contains no SQL, spec AC22/OP10): a per-investigation advisory lock for
turn serialization (E24) and a read-only data fingerprint for the Business State cache (L7). Neither touches business data; neither grants anything."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from backend.tenant_context import get_engine, tenant_scope

# Table names are interpolated into SQL, so only names from this fixed list may ever be fingerprinted (never a value from a request).
FINGERPRINT_TABLES: frozenset[str] = frozenset({
    "metric_result", "financial_health_config", "leak_finding", "agent_data_request", "manual_adjustment", "report_file", "ingestion_run",
    "competitor_url", "competitor_snapshot", "pi_research_run", "cmo_generation", "agent_memory",
})


def data_fingerprint(tenant_id: UUID, tables: Sequence[str]) -> str:
    """For each table: the row count and the sum of every row's `xmin` (the transaction that last wrote it), through the caller's own tenant scope.
    Any insert, update or delete by any writer changes it; RLS means it can only ever see this tenant's rows."""
    unknown = [t for t in tables if t not in FINGERPRINT_TABLES]
    if unknown:
        raise ValueError(f"not a fingerprintable table: {unknown}")
    parts: list[str] = []
    with tenant_scope(tenant_id) as conn:
        for t in tables:
            row = conn.execute(text(f"SELECT count(*), COALESCE(sum(xmin::text::bigint), 0) FROM {t}")).one()  # noqa: S608 - whitelisted above
            parts.append(f"{t}:{row[0]}:{row[1]}")
    return "|".join(parts)


class AdvisoryLock:
    """A Postgres session-level advisory lock on a dedicated autocommit connection. Closing the connection (also on process death) releases it."""

    def __init__(self, key: str) -> None:
        self._key = key
        self._conn: Connection = get_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
        self._held = False

    def try_acquire(self) -> bool:
        got = bool(self._conn.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))"), {"k": self._key}).scalar())
        self._held = self._held or got
        return got

    def release(self) -> None:
        if self._held:
            self._conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": self._key})
            self._held = False

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AdvisoryLock":
        return self

    def __exit__(self, *_: Any) -> None:
        try:
            self.release()
        finally:
            self.close()
