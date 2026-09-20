"""RLS fail-closed verification — auth.md §7.3. Same four-test shape as calc-engine's and
data-foundation's own test_rls_isolation.py: cross-tenant SELECT isolation, tenant_id=None
fail-closed at the application layer, unset-session-yields-zero-rows, cross-tenant INSERT
rejection.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from competitor_intelligence.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _insert_competitor_url(tenant_id: uuid.UUID, url: str) -> uuid.UUID:
    row_id = uuid.uuid4()
    added_by = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO competitor_url (id, tenant_id, marketplace, url, status, added_by)
                VALUES (:id, :tenant_id, 'AMAZON', :url, 'ACTIVE', :added_by)
                """
            ),
            {"id": str(row_id), "tenant_id": str(tenant_id), "url": url, "added_by": str(added_by)},
        )
    return row_id


def test_tenant_cannot_see_another_tenants_rows(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    _insert_competitor_url(tenant_a, "https://amazon.in/dp/a")
    _insert_competitor_url(tenant_b, "https://amazon.in/dp/b")

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT url FROM competitor_url")).fetchall()
    assert [r[0] for r in rows] == ["https://amazon.in/dp/a"]

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT url FROM competitor_url")).fetchall()
    assert [r[0] for r in rows] == ["https://amazon.in/dp/b"]


def test_tenant_context_none_raises_before_any_query(two_tenants) -> None:
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("tenant_scope(None) must raise before yielding a connection")


def test_unset_session_tenant_context_yields_zero_rows_not_an_error(two_tenants, app_engine) -> None:
    tenant_a, _ = two_tenants
    _insert_competitor_url(tenant_a, "https://amazon.in/dp/a")

    with app_engine.connect() as conn:
        # deliberately no SET LOCAL app.current_tenant_id here
        rows = conn.execute(text("SELECT url FROM competitor_url")).fetchall()
    assert rows == []


def test_tenant_cannot_write_a_row_under_another_tenants_id(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO competitor_url (id, tenant_id, marketplace, url, status, added_by)
                    VALUES (:id, :tenant_id, 'AMAZON', 'https://amazon.in/dp/spoofed', 'ACTIVE', :added_by)
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b), "added_by": str(uuid.uuid4())},
            )
