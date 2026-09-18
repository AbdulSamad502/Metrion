"""Direct (non-tenant-scoped) database access — for `tenant` and `app_user`, the two
identity-root tables that carry no `tenant_id` column and get no RLS policy (see
`migrations/versions/20260917_0001_auth_tables.py`). Every other table goes through
`tenant_context.tenant_scope()` instead; using this module for a tenant-owned table would
bypass the fail-closed guarantee that module provides.
"""

from __future__ import annotations

from sqlalchemy import Engine

from backend.tenant_context import get_engine as _get_engine


def engine() -> Engine:
    return _get_engine()
