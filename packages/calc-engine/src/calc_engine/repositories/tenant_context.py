"""BEGIN / SET LOCAL app.current_tenant_id / COMMIT wrapper — auth.md §7.3 (D2, S6, S8).

This is the only place in calc-engine that opens a transaction and sets tenant context.
Every other repository in this package receives a `Connection` from `tenant_scope()` and
never opens its own — so there is exactly one path by which a query could run without
tenant context, and it fails closed.

`SET LOCAL` is transaction-scoped: it resets at COMMIT/ROLLBACK, which is what makes it safe
to use over a pooled connection (a connection handed back to the pool carries no residue).
Session-level `SET` is never used here — that is precisely the mechanism auth.md §7.3
prohibits, since it would leak tenant context across requests under transaction pooling.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

_engine: Engine | None = None


def get_engine() -> Engine:
    """Lazily creates the module-level engine from DATABASE_URL_APP — the metrion_app role
    (non-owner, NOBYPASSRLS, auth.md §7.3), never metrion_migrate. Connecting as the table
    owner would make every RLS policy in this package decorative."""
    global _engine
    if _engine is None:
        url = os.environ.get("DATABASE_URL_APP")
        if not url:
            raise RuntimeError(
                "DATABASE_URL_APP is not set. calc-engine repositories must connect as "
                "metrion_app (see .env.example) — there is no default connection string."
            )
        _engine = create_engine(url)
    return _engine


@contextmanager
def tenant_scope(tenant_id: UUID | None) -> Iterator[Connection]:
    """Opens an explicit transaction, sets `app.current_tenant_id` for its duration, and
    commits or rolls back on exit. Every calc-engine repository call goes through this.

    Fail-closed (S8): a `None` tenant_id raises immediately, before any query can run. This
    is the application-layer half of the two-layer guarantee auth.md §7.3 requires — RLS
    alone (an unset `current_setting` returning NULL, yielding zero visible rows) is not
    trusted as the only line of defence, because zero rows is indistinguishable from "no
    data" to a caller that isn't specifically checking for it.
    """
    if tenant_id is None:
        raise ValueError(
            "tenant_scope() called with tenant_id=None — refusing to open a connection "
            "without tenant context (auth.md §7.3, fail-closed). No query in this package "
            "may run outside an explicit tenant scope."
        )

    engine = get_engine()
    with engine.connect() as connection:
        with connection.begin():
            # `SET LOCAL name = value` is a utility statement — PostgreSQL's wire protocol
            # does not accept bind parameters inside it, only literals, which would force
            # unsafe string interpolation. `set_config(name, value, is_local)` is an
            # ordinary function call and takes a bind parameter normally; its third
            # argument (true) gives it the same transaction-scoped reset behaviour as
            # `SET LOCAL` (auth.md §7.3).
            connection.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            yield connection
        # connection.begin()'s context manager commits on clean exit, rolls back on
        # exception; either way SET LOCAL's effect ends here, before the connection
        # returns to the pool (auth.md §7.3: "context discarded automatically").
