"""RLS fail-closed verification for the backend-owned tables migrated in
20260917_0001/0002/0003 — auth.md §7.3, S1-S9. Mirrors
`packages/calc-engine/tests/integration/test_rls_isolation.py`: verified against a real
Postgres, connected as `metrion_app` (the actual runtime role), not `metrion_migrate`.

Covers `membership` (has FKs to tenant/app_user — the table most requests actually touch)
and `auth_audit` (a second, independently-migrated table) so the policy is checked on more
than one table rather than assumed to generalise from one.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend.tenant_context import tenant_scope


def _insert_membership(tenant_id: uuid.UUID, app_user_id: uuid.UUID) -> uuid.UUID:
    row_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO membership (id, tenant_id, app_user_id, role, status, permissions)
                VALUES (:id, :tenant_id, :app_user_id, 'OWNER', 'ACTIVE', '{}'::jsonb)
                """
            ),
            {"id": str(row_id), "tenant_id": str(tenant_id), "app_user_id": str(app_user_id)},
        )
    return row_id


def test_tenant_cannot_see_another_tenants_membership(two_tenants, app_user):
    tenant_a, tenant_b = two_tenants
    _insert_membership(tenant_a, app_user)
    _insert_membership(tenant_b, app_user)

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT tenant_id FROM membership")).fetchall()
    assert [r[0] for r in rows] == [tenant_a]

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT tenant_id FROM membership")).fetchall()
    assert [r[0] for r in rows] == [tenant_b]


def test_tenant_cannot_write_a_membership_row_under_another_tenants_id(two_tenants, app_user):
    """WITH CHECK (§7.3): a session scoped to tenant A cannot insert a row claiming to
    belong to tenant B."""
    tenant_a, tenant_b = two_tenants
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO membership (id, tenant_id, app_user_id, role, status, permissions)
                    VALUES (:id, :tenant_id, :app_user_id, 'OWNER', 'ACTIVE', '{}'::jsonb)
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b), "app_user_id": str(app_user)},
            )


def test_tenant_context_none_raises_before_any_query(two_tenants):
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("tenant_scope(None) must raise before yielding a connection")


def test_unset_session_tenant_context_yields_zero_rows_not_an_error(two_tenants, app_user, app_engine):
    """The RLS half of the two-layer guarantee: a connection that never called SET LOCAL at
    all sees zero rows rather than every tenant's data."""
    tenant_a, _ = two_tenants
    _insert_membership(tenant_a, app_user)

    with app_engine.connect() as conn:
        # deliberately no SET LOCAL app.current_tenant_id here
        rows = conn.execute(text("SELECT tenant_id FROM membership")).fetchall()
    assert rows == []


def test_tenant_cannot_see_another_tenants_auth_audit_row(two_tenants):
    """A second, independently-migrated table (20260917_0001), so the policy is verified on
    more than one table rather than assumed to generalise from `membership` alone."""
    tenant_a, tenant_b = two_tenants
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text("INSERT INTO auth_audit (id, tenant_id, event) VALUES (:id, :tenant_id, 'SIGN_IN')"),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_a)},
        )
    with tenant_scope(tenant_b) as conn:
        conn.execute(
            text("INSERT INTO auth_audit (id, tenant_id, event) VALUES (:id, :tenant_id, 'SIGN_IN')"),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b)},
        )

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT tenant_id FROM auth_audit")).fetchall()
    assert [r[0] for r in rows] == [tenant_a]
