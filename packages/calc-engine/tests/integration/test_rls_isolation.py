"""RLS fail-closed verification — auth.md §7.3, S1-S9. This is the test the project's own
instructions specifically demanded before Category B could be called done: tenant isolation
"hasn't actually been verified yet, only assumed from the schema design." It is verified here
against a real Postgres, connected as metrion_app (the actual runtime role), not metrion_migrate.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")


def _insert_metric_result(tenant_id: uuid.UUID, target_ref: str) -> uuid.UUID:
    result_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO metric_result
                    (id, tenant_id, metric_code, grain, target_ref, value_paise, recognition_state,
                     confidence, calculation_basis, formula_version, config_version,
                     canonical_data_version, computed_at)
                VALUES
                    (:id, :tenant_id, 'NET_REALIZED_REVENUE', 'LINE', :target_ref, 100000, 'RECOGNISED',
                     'PROVISIONAL', 'test row', 'NET_REALIZED_REVENUE.v1', 'v1', 'deadbeef', :computed_at)
                """
            ),
            {"id": str(result_id), "tenant_id": str(tenant_id), "target_ref": target_ref, "computed_at": datetime.now(timezone.utc)},
        )
    return result_id


def test_tenant_cannot_see_another_tenants_rows(two_tenants):
    tenant_a, tenant_b = two_tenants
    _insert_metric_result(tenant_a, "line-a-1")
    _insert_metric_result(tenant_b, "line-b-1")

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT target_ref FROM metric_result")).fetchall()
    assert [r[0] for r in rows] == ["line-a-1"]  # tenant A never sees tenant B's row

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT target_ref FROM metric_result")).fetchall()
    assert [r[0] for r in rows] == ["line-b-1"]


def test_tenant_context_none_raises_before_any_query(two_tenants):
    """Application-layer fail-closed (S8): a missing tenant_id must raise, not silently run
    an unscoped query and rely on RLS alone to return zero rows."""
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("tenant_scope(None) must raise before yielding a connection")


def test_unset_session_tenant_context_yields_zero_rows_not_an_error(two_tenants, app_engine):
    """The RLS half of the two-layer guarantee: a connection that never called SET LOCAL at
    all (simulating a hypothetical bypass of tenant_context.py) sees zero rows rather than
    every tenant's data — current_setting(..., true) returns NULL, and the policy predicate
    `tenant_id = NULL` is never true for any row (§7.3, S8)."""
    tenant_a, _ = two_tenants
    _insert_metric_result(tenant_a, "line-a-1")

    with app_engine.connect() as conn:
        # deliberately no SET LOCAL app.current_tenant_id here
        rows = conn.execute(text("SELECT target_ref FROM metric_result")).fetchall()
    assert rows == []


def test_tenant_cannot_write_a_row_under_another_tenants_id(two_tenants):
    """WITH CHECK (§7.3): a session scoped to tenant A cannot insert a row claiming to
    belong to tenant B."""
    tenant_a, tenant_b = two_tenants
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO metric_result
                        (id, tenant_id, metric_code, grain, target_ref, value_paise, recognition_state,
                         confidence, calculation_basis, formula_version, config_version,
                         canonical_data_version, computed_at)
                    VALUES
                        (:id, :tenant_id, 'NET_REALIZED_REVENUE', 'LINE', 'x', 1, 'RECOGNISED',
                         'PROVISIONAL', 'test row', 'v1', 'v1', 'deadbeef', now())
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b)},  # spoofed tenant_id
            )


def test_platform_default_discount_bearer_row_visible_to_every_tenant(two_tenants):
    """discount_bearer_config's policy deliberately admits tenant_id IS NULL rows regardless
    of session tenant (§5.3 platform-default semantics) — this is the one table where that's
    correct, not a leak, so it gets its own assertion rather than being lumped in with the
    strict-isolation cases above."""
    tenant_a, tenant_b = two_tenants
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO discount_bearer_config
                    (id, tenant_id, marketplace, component_code, bearer, source, confidence, effective_from, version)
                VALUES
                    (:id, NULL, 'AMAZON', 'SELLER_DISCOUNT', 'SELLER', 'spec default', 'PROVISIONAL', '2026-01-01', 1)
                """
            ),
            {"id": str(uuid.uuid4())},
        )

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT bearer FROM discount_bearer_config")).fetchall()
    assert [r[0] for r in rows] == ["SELLER"]
