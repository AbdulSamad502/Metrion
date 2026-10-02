"""Tenant-scoped test cleanup.

Why this exists: every tenant-owned table is `FORCE ROW LEVEL SECURITY` with the policy
`tenant_id = current_setting('app.current_tenant_id', true)::uuid`. FORCE applies to the table
owner (`metrion_migrate`) too, so a `DELETE FROM <table>` with no tenant context evaluates the
policy to NULL for every row and silently deletes ZERO rows. The test fixtures that did that
(65 such statements) therefore never cleaned anything, and test data piled up in the shared dev
database. The one fixture that did work around it (backend) finished with global
`DELETE FROM tenant` / `DELETE FROM app_user`, which wipes every real tenant and user in the dev
database whenever the suite runs.

The approach here deletes exactly what a test created, through RLS:

1. `TenantTracker` listens (SQLAlchemy `Engine`-class `before_cursor_execute`) for the
   `set_config('app.current_tenant_id', <uuid>, ...)` statement every package's `tenant_scope()`
   issues, and records the tenant ids the code under test actually touched. Tenants nobody
   touched are never recorded, so a real tenant can never be purged.
2. `purge_tenants()` opens, per recorded tenant, a transaction with THAT tenant's context set
   and runs `DELETE FROM <t> WHERE tenant_id = :tenant` for every tenant-owned table, children
   before parents (FK order read from the catalog) — RLS stays enforced, no role bypasses it,
   and the explicit `WHERE tenant_id` makes the intent independent of the policy.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Iterable

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.pool import NullPool

_TENANT_SETTING = "app.current_tenant_id"


class TenantTracker:
    """Records every tenant id passed to `set_config('app.current_tenant_id', ...)`."""

    def __init__(self) -> None:
        self.tenants: set[uuid.UUID] = set()
        self.app_users: set[uuid.UUID] = set()
        self._installed = False

    def install(self) -> None:
        if not self._installed:
            event.listen(Engine, "before_cursor_execute", self._on_execute)
            self._installed = True

    def uninstall(self) -> None:
        if self._installed:
            event.remove(Engine, "before_cursor_execute", self._on_execute)
            self._installed = False

    def reset(self) -> None:
        self.tenants.clear()
        self.app_users.clear()

    def purge(self, engine: Engine) -> None:
        """Purges everything recorded so far (see `purge_tenants`/`purge_app_users`) and resets,
        so a second call — e.g. a package-level and a directory-level fixture both tearing down
        after the same test — finds nothing left to do."""
        tenants, users = list(self.tenants), list(self.app_users)
        self.reset()
        purge_tenants(engine, tenants)
        purge_app_users(engine, users)

    # -- listener ------------------------------------------------------------------------
    def _on_execute(self, conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        head = statement.lstrip().upper()
        is_set_tenant = _TENANT_SETTING in statement
        is_user_insert = head.startswith("INSERT INTO APP_USER")
        is_tenant_insert = head.startswith("INSERT INTO TENANT ") or head.startswith("INSERT INTO TENANT(")
        if not (is_set_tenant or is_user_insert or is_tenant_insert):
            return
        for params in parameters if executemany and parameters else [parameters]:
            values = params.items() if isinstance(params, dict) else enumerate(params or ())
            for key, value in values:
                try:
                    parsed = uuid.UUID(str(value))
                except (ValueError, AttributeError):
                    continue
                if is_set_tenant:
                    self.tenants.add(parsed)
                elif key == "id":  # the inserted row's own primary key
                    (self.app_users if is_user_insert else self.tenants).add(parsed)


# One process-wide tracker, shared by every conftest that wants one.
TRACKER = TenantTracker()


@contextmanager
def _isolated(engine: Engine) -> Iterator[Engine]:
    """A private, NON-pooled engine to the same database. `set_config(..., true)` leaves the
    setting as an empty string (not unset) on the connection after the transaction, so running
    the purge on the caller's pooled connection would make a later unscoped statement on that
    connection fail with `invalid input syntax for type uuid: ""`. Throwaway connections can
    never leave that residue behind."""
    private = create_engine(engine.url, poolclass=NullPool)
    try:
        yield private
    finally:
        private.dispose()


_TABLE_ORDER_CACHE: dict[str, list[str]] = {}


def _tenant_tables_children_first(engine: Engine) -> list[str]:
    """Public tables carrying a `tenant_id` column, ordered so a table that references another
    (FK) comes before the one it references."""
    key = engine.url.render_as_string(hide_password=True)
    if key in _TABLE_ORDER_CACHE:
        return _TABLE_ORDER_CACHE[key]
    with engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT c.table_name FROM information_schema.columns c "
                    "JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                    "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE'"
                )
            )
        }
        edges = conn.execute(
            text(
                "SELECT cl.relname AS child, pl.relname AS parent FROM pg_constraint k "
                "JOIN pg_class cl ON cl.oid = k.conrelid JOIN pg_class pl ON pl.oid = k.confrelid "
                "JOIN pg_namespace n ON n.oid = cl.relnamespace WHERE k.contype = 'f' AND n.nspname = 'public'"
            )
        ).all()
    referenced_by: dict[str, set[str]] = defaultdict(set)  # parent -> children (both within `tables`)
    for child, parent in edges:
        if child in tables and parent in tables and child != parent:
            referenced_by[parent].add(child)
    ordered: list[str] = []
    remaining = set(tables)
    while remaining:
        # a table is safe to delete once nothing remaining still references it
        ready = sorted(t for t in remaining if not (referenced_by[t] & remaining))
        if not ready:  # an FK cycle — delete the rest in a stable order rather than loop forever
            ready = sorted(remaining)
        ordered.extend(ready)
        remaining -= set(ready)
    _TABLE_ORDER_CACHE[key] = ordered
    return ordered


def purge_tenants(engine: Engine, tenants: Iterable[uuid.UUID]) -> dict[str, int]:
    """Deletes every tenant-owned row of the given tenants (and nothing else), under each
    tenant's own RLS context. Returns rows deleted per table (for assertions/diagnostics)."""
    deleted: dict[str, int] = defaultdict(int)
    tables = _tenant_tables_children_first(engine)
    for tenant in sorted(set(tenants), key=str):
        with _isolated(engine) as private, private.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            for table in tables:
                result = conn.execute(text(f'DELETE FROM "{table}" WHERE tenant_id = :t'), {"t": str(tenant)})
                deleted[table] += result.rowcount or 0
            if _has_table(conn, "tenant"):  # backend's own tenant row (keyed by id, no RLS)
                deleted["tenant"] += conn.execute(text("DELETE FROM tenant WHERE id = :t"), {"t": str(tenant)}).rowcount or 0
    return dict(deleted)


def purge_app_users(engine: Engine, app_user_ids: Iterable[uuid.UUID]) -> int:
    """Deletes exactly the `app_user` rows a test inserted (by id) — never a pattern or a table-wide delete."""
    ids = [str(i) for i in set(app_user_ids)]
    if not ids:
        return 0
    with _isolated(engine) as private, private.begin() as conn:
        if not _has_table(conn, "app_user"):
            return 0
        return conn.execute(text("DELETE FROM app_user WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids}).rowcount or 0


def _has_table(conn: Any, name: str) -> bool:
    return bool(conn.execute(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"public.{name}"}).scalar())


def count_rows_for_tenants(engine: Engine, tenants: Iterable[uuid.UUID]) -> dict[str, int]:
    """Rows still present for the given tenants, per table (RLS-scoped reads) — for tests/diagnostics."""
    left: dict[str, int] = defaultdict(int)
    tables = _tenant_tables_children_first(engine)
    for tenant in set(tenants):
        with _isolated(engine) as private, private.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            for table in tables:
                n = conn.execute(text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :t'), {"t": str(tenant)}).scalar_one()
                if n:
                    left[table] += n
    return dict(left)
