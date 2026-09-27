"""RLS fail-closed verification — auth.md §7.3. Mirrors
`competitor-intelligence/tests/integration/test_rls_isolation.py`'s exact four-test shape,
against BOTH CFO-owned tables (`leak_finding`, `agent_data_request`): cross-tenant SELECT
isolation, `tenant_scope(None)` fail-closed at the application layer before any query runs,
unset-session-yields-zero-rows, cross-tenant INSERT rejection.

Requires a real Postgres reachable as the actual `metrion_app` runtime role (never
`metrion_migrate`) — see `tests/integration/conftest.py` for the skip condition when no
DATABASE_URL_APP/DATABASE_URL is set in this session.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from cfo.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_cfo_tables")


def _insert_leak_finding(tenant_id: uuid.UUID, *, marketplace: str = "AMAZON") -> uuid.UUID:
    row_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO leak_finding (
                  id, tenant_id, reconciliation_exception_id, engine_result_ref, marketplace,
                  leak_category, severity, amount_paise, affected_line_count,
                  first_observed_at, age_days, status, confidence, formula_version
                )
                VALUES (
                  :id, :tenant_id, :exc_id, :ref, :marketplace,
                  'MISSING_SETTLEMENT', 'HIGH', 5000, 1,
                  :observed_at, 10, 'NEW', 'DERIVED', 'LEAK_CLASSIFICATION.v1'
                )
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "exc_id": str(uuid.uuid4()),
                "ref": str(uuid.uuid4()),
                "marketplace": marketplace,
                "observed_at": datetime.now(timezone.utc),
            },
        )
    return row_id


def _insert_agent_data_request(tenant_id: uuid.UUID, *, requested_field: str = "cogs_per_unit") -> uuid.UUID:
    row_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO agent_data_request (id, tenant_id, requested_field, reason, status)
                VALUES (:id, :tenant_id, :requested_field, 'test fixture', 'OPEN')
                """
            ),
            {"id": str(row_id), "tenant_id": str(tenant_id), "requested_field": requested_field},
        )
    return row_id


# ---------------------------------------------------------------------------
# leak_finding
# ---------------------------------------------------------------------------


def test_leak_finding_tenant_cannot_see_another_tenants_rows(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    _insert_leak_finding(tenant_a, marketplace="AMAZON")
    _insert_leak_finding(tenant_b, marketplace="FLIPKART")

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT marketplace FROM leak_finding")).fetchall()
    assert [r[0] for r in rows] == ["AMAZON"]

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT marketplace FROM leak_finding")).fetchall()
    assert [r[0] for r in rows] == ["FLIPKART"]


def test_leak_finding_tenant_context_none_raises_before_any_query(two_tenants) -> None:
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("tenant_scope(None) must raise before yielding a connection")


def test_leak_finding_unset_session_tenant_context_yields_zero_rows_not_an_error(two_tenants, app_engine) -> None:
    tenant_a, _ = two_tenants
    _insert_leak_finding(tenant_a)

    with app_engine.connect() as conn:
        # deliberately no SET LOCAL app.current_tenant_id here
        rows = conn.execute(text("SELECT marketplace FROM leak_finding")).fetchall()
    assert rows == []


def test_leak_finding_tenant_cannot_write_a_row_under_another_tenants_id(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO leak_finding (
                      id, tenant_id, reconciliation_exception_id, engine_result_ref, marketplace,
                      leak_category, severity, amount_paise, affected_line_count,
                      first_observed_at, age_days, status, confidence, formula_version
                    )
                    VALUES (
                      :id, :tenant_id, :exc_id, :ref, 'AMAZON',
                      'MISSING_SETTLEMENT', 'HIGH', 5000, 1,
                      now(), 10, 'NEW', 'DERIVED', 'LEAK_CLASSIFICATION.v1'
                    )
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b), "exc_id": str(uuid.uuid4()), "ref": str(uuid.uuid4())},
            )


# ---------------------------------------------------------------------------
# agent_data_request
# ---------------------------------------------------------------------------


def test_agent_data_request_tenant_cannot_see_another_tenants_rows(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    _insert_agent_data_request(tenant_a, requested_field="cogs_per_unit")
    _insert_agent_data_request(tenant_b, requested_field="rto_outcome")

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT requested_field FROM agent_data_request")).fetchall()
    assert [r[0] for r in rows] == ["cogs_per_unit"]

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT requested_field FROM agent_data_request")).fetchall()
    assert [r[0] for r in rows] == ["rto_outcome"]


def test_agent_data_request_tenant_context_none_raises_before_any_query(two_tenants) -> None:
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("tenant_scope(None) must raise before yielding a connection")


def test_agent_data_request_unset_session_tenant_context_yields_zero_rows_not_an_error(two_tenants, app_engine) -> None:
    tenant_a, _ = two_tenants
    _insert_agent_data_request(tenant_a)

    with app_engine.connect() as conn:
        # deliberately no SET LOCAL app.current_tenant_id here
        rows = conn.execute(text("SELECT requested_field FROM agent_data_request")).fetchall()
    assert rows == []


def test_agent_data_request_tenant_cannot_write_a_row_under_another_tenants_id(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_data_request (id, tenant_id, requested_field, reason, status)
                    VALUES (:id, :tenant_id, 'cogs_per_unit', 'spoofed', 'OPEN')
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b)},
            )
