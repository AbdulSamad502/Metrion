"""BEGIN / set_config('app.current_tenant_id', ..., true) wrapper — auth.md §7.3.

Identical pattern to packages/calc-engine/src/calc_engine/repositories/tenant_context.py:
same two roles (metrion_app/metrion_migrate), same fail-closed-on-None behavior, same
set_config() choice over a literal SET LOCAL (which can't take a bind parameter). Duplicated
rather than imported from calc-engine because each package should be able to point at a
different DATABASE_URL_APP in principle (e.g. different connection pools per service) even
though today they share one Postgres instance.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

_engine: Engine | None = None


def engine_options() -> dict[str, object]:
    """Connection-pool behaviour, identical in every package of this repository (keep the seven copies in step; `backend/tests/unit/test_engine_options.py` compares them).

    * `pool_pre_ping`: a database restart/failover kills every idle pooled connection; check one before use instead of failing the request that happens to draw it.
    * `connect_timeout` (libpq, seconds; default 10): without it a database that accepts the TCP connection and then stalls (seen with a stopped container behind a port proxy)
      hangs every request, health probes included, until the client gives up. Bounded now: the request fails with a connection error instead.
    * `pool_size` 5, `max_overflow` 10 and `pool_timeout` 30 s are SQLAlchemy's own defaults, unchanged; they are overridable per deployment. A caller that cannot get a
      connection in `pool_timeout` seconds fails (TimeoutError) rather than waiting forever. No sizing is claimed to be right for production: it needs a load test.
    Overrides: DB_CONNECT_TIMEOUT_SECONDS, DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT_SECONDS (positive integers; anything else is an error at first use)."""

    def number(name: str, default: int) -> int:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            return default
        value = int(raw)
        if value < 1:
            raise ValueError(f"{name} must be a positive integer")
        return value

    return {
        "pool_pre_ping": True,
        "pool_size": number("DB_POOL_SIZE", 5),
        "max_overflow": number("DB_MAX_OVERFLOW", 10),
        "pool_timeout": number("DB_POOL_TIMEOUT_SECONDS", 30),
        "connect_args": {"connect_timeout": number("DB_CONNECT_TIMEOUT_SECONDS", 10)},
    }


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL_APP")
        if not url:
            raise RuntimeError(
                "DATABASE_URL_APP is not set. data-foundation repositories must connect as "
                "metrion_app (see .env.example) — there is no default connection string."
            )
        _engine = create_engine(url, **engine_options())
    return _engine


@contextmanager
def tenant_scope(tenant_id: UUID | None) -> Iterator[Connection]:
    """Fail-closed (S8): a None tenant_id raises before any query can run — the
    application-layer half of auth.md §7.3's two-layer guarantee."""
    if tenant_id is None:
        raise ValueError(
            "tenant_scope() called with tenant_id=None — refusing to open a connection "
            "without tenant context (auth.md §7.3, fail-closed)."
        )

    engine = get_engine()
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            yield connection
