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


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL_APP")
        if not url:
            raise RuntimeError(
                "DATABASE_URL_APP is not set. data-foundation repositories must connect as "
                "metrion_app (see .env.example) — there is no default connection string."
            )
        _engine = create_engine(url)
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
