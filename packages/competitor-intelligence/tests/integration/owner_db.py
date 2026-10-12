"""Test setup that must write what the application role may not (backend migration 20261012_0018): configuration rows. In production an operator loads these with the OWNER role
(`backend/scripts/config_admin.py`); tests seed them the same way, still under a tenant context so FORCE RLS applies to the write."""

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
