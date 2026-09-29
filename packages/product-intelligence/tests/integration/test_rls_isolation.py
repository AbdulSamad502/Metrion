"""RLS fail-closed verification — auth.md §7.3. Same four-test shape as calc-engine's and
competitor-intelligence's own test_rls_isolation.py: cross-tenant SELECT isolation,
tenant_id=None fail-closed at the application layer, unset-session-yields-zero-rows,
cross-tenant INSERT rejection. Covers `niche_brief` (no FK dependencies) and
`product_candidate` (FK-dependent on `pi_research_run`/`niche_brief`) so both a leaf table
and a dependent table are verified — RLS correctness must be checked at scaffolding time,
not deferred to Checkpoint 2/3, per the PI build plan's Checkpoint 1 scope.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from product_intelligence.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_pi_tables")


def _insert_niche_brief(tenant_id: uuid.UUID, category_text: str) -> uuid.UUID:
    row_id = uuid.uuid4()
    created_by = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO niche_brief (id, tenant_id, status, category_text, created_by)
                VALUES (:id, :tenant_id, 'DRAFT', :category_text, :created_by)
                """
            ),
            {
                "id": str(row_id),
                "tenant_id": str(tenant_id),
                "category_text": category_text,
                "created_by": str(created_by),
            },
        )
    return row_id


def _insert_candidate_chain(tenant_id: uuid.UUID, candidate_title: str) -> uuid.UUID:
    """niche_brief -> pi_research_run -> product_candidate, all under the same tenant_id."""
    brief_id = _insert_niche_brief(tenant_id, "test niche")
    run_id = uuid.uuid4()
    candidate_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO pi_research_run
                    (id, tenant_id, niche_brief_id, depth, trigger, candidate_cap, status)
                VALUES
                    (:id, :tenant_id, :niche_brief_id, 'SHALLOW', 'DIRECT_UI', 5, 'QUEUED')
                """
            ),
            {"id": str(run_id), "tenant_id": str(tenant_id), "niche_brief_id": str(brief_id)},
        )
        conn.execute(
            text(
                """
                INSERT INTO product_candidate
                    (id, tenant_id, run_id, candidate_title, source_diversity, proxy_state,
                     proxy_basis, score_explanation, source_urls, capture_status, confidence)
                VALUES
                    (:id, :tenant_id, :run_id, :candidate_title, 0, 'UNAVAILABLE',
                     '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'UNAVAILABLE', 'UNAVAILABLE')
                """
            ),
            {
                "id": str(candidate_id),
                "tenant_id": str(tenant_id),
                "run_id": str(run_id),
                "candidate_title": candidate_title,
            },
        )
    return candidate_id


def test_tenant_cannot_see_another_tenants_niche_briefs(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    _insert_niche_brief(tenant_a, "tenant a niche")
    _insert_niche_brief(tenant_b, "tenant b niche")

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT category_text FROM niche_brief")).fetchall()
    assert [r[0] for r in rows] == ["tenant a niche"]

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT category_text FROM niche_brief")).fetchall()
    assert [r[0] for r in rows] == ["tenant b niche"]


def test_tenant_cannot_see_another_tenants_product_candidates(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    _insert_candidate_chain(tenant_a, "tenant a candidate")
    _insert_candidate_chain(tenant_b, "tenant b candidate")

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT candidate_title FROM product_candidate")).fetchall()
    assert [r[0] for r in rows] == ["tenant a candidate"]

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT candidate_title FROM product_candidate")).fetchall()
    assert [r[0] for r in rows] == ["tenant b candidate"]


def test_tenant_context_none_raises_before_any_query(two_tenants) -> None:
    with pytest.raises(ValueError, match="tenant_id=None"):
        with tenant_scope(None):
            pytest.fail("tenant_scope(None) must raise before yielding a connection")


def test_unset_session_tenant_context_yields_zero_rows_not_an_error(two_tenants, app_engine) -> None:
    tenant_a, _ = two_tenants
    _insert_niche_brief(tenant_a, "tenant a niche")

    with app_engine.connect() as conn:
        # deliberately no SET LOCAL app.current_tenant_id here
        rows = conn.execute(text("SELECT category_text FROM niche_brief")).fetchall()
    assert rows == []


def test_tenant_cannot_write_a_row_under_another_tenants_id(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO niche_brief (id, tenant_id, status, category_text, created_by)
                    VALUES (:id, :tenant_id, 'DRAFT', 'spoofed', :created_by)
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b), "created_by": str(uuid.uuid4())},
            )
