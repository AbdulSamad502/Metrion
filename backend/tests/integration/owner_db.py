"""Test setup that must write what the application role may not (migration 20261012_0018): configuration, reference data, entitlement rows and billing-ledger clean-up.

In production these are changed by an operator with the OWNER role (`scripts/config_admin.py`), never by the running application, so a test that needs such a row seeds it the
same way: with the owner connection (`DATABASE_URL`), still under a tenant context so FORCE RLS applies to it exactly as it does to everything else. Never use this to read
or write what the application itself reads or writes: those paths must keep going through the application role."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, create_engine, make_url, text
from sqlalchemy.pool import NullPool


@contextmanager
def owner_tenant_scope(tenant_id: UUID | None) -> Iterator[Connection]:
    url = os.environ["DATABASE_URL"]
    assert make_url(url).port == 5544, "owner-role test setup runs against the scratch database only"
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant_id) if tenant_id else ""})
            yield conn
    finally:
        engine.dispose()
