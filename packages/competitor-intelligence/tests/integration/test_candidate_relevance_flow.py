"""ci_discovery_run / ci_candidate / ci_candidate_relevance — competitor-intelligence-agent.md
§5.4, §6.13, §6.14. RLS isolation plus a round trip through
`repositories/ci_discovery_run_repo.py`, `repositories/ci_candidate_repo.py` and
`repositories/ci_candidate_relevance_repo.py`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from competitor_intelligence.discovery.identity_resolution import (
    IdentityMatch,
    IdentityMatchBasis,
    IdentityResolution,
)
from competitor_intelligence.discovery.relevance_scoring import (
    AxisResult,
    AxisState,
    RelevanceScoreInputs,
    score_relevance,
)
from competitor_intelligence.repositories import (
    ci_candidate_relevance_repo,
    ci_candidate_repo,
    ci_discovery_run_repo,
)
from competitor_intelligence.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")

_KNOWN2 = AxisResult(2, AxisState.KNOWN)
_UNKNOWN = AxisResult(0, AxisState.UNKNOWN)


def _basis() -> IdentityMatchBasis:
    return IdentityMatchBasis(
        candidate_brand="XYZ",
        seller_brand="XYZ",
        candidate_model_tokens=frozenset({"wireless", "mouse", "pro"}),
        seller_model_tokens=frozenset({"wireless", "mouse", "pro"}),
        candidate_pack_size=None,
        seller_pack_size=None,
        candidate_is_bundle=False,
        seller_is_bundle=False,
    )


def _relevance_inputs() -> RelevanceScoreInputs:
    return RelevanceScoreInputs(
        category=_KNOWN2,
        product=_KNOWN2,
        price_proximity=_KNOWN2,
        features=_KNOWN2,
        keywords=_KNOWN2,
        use_case=_KNOWN2,
        fulfillment=_UNKNOWN,
        review_tier=_UNKNOWN,
    )


def test_full_flow_round_trips_through_postgres(two_tenants) -> None:
    tenant_a, _ = two_tenants
    requested_by = uuid.uuid4()

    run_id = ci_discovery_run_repo.create_run(
        tenant_a, seller_product_ref="SKU-1", requested_by=requested_by, status="DISCOVERING"
    )
    assert ci_discovery_run_repo.get_run(tenant_a, run_id) is not None

    candidate_id = ci_candidate_repo.create_candidate(
        tenant_a, discovery_run_id=run_id, candidate_url="https://amazon.in/dp/abc", marketplace="AMAZON"
    )

    resolution = IdentityResolution(identity_match=IdentityMatch.EXACT_MATCH, basis=_basis())
    ci_candidate_repo.set_identity_resolution(tenant_a, candidate_id, resolution, tier="ANALYZED")

    stored = ci_candidate_repo.get_candidate(tenant_a, candidate_id)
    assert stored["identity_match"] == "EXACT_MATCH"
    assert stored["tier"] == "ANALYZED"
    assert stored["identity_match_basis"] is not None

    breakdown = score_relevance(_relevance_inputs(), is_provisional=True)
    relevance_id = ci_candidate_relevance_repo.insert_relevance(
        tenant_a, candidate_id=candidate_id, breakdown=breakdown
    )
    assert relevance_id is not None

    latest = ci_candidate_relevance_repo.get_latest_relevance(tenant_a, candidate_id)
    assert latest["band"] == "HIGH"
    assert latest["total_score"] == breakdown.total_score
    assert latest["is_provisional"] is True
    assert latest["axis_scores"]["fulfillment"] == 0
    assert latest["axis_states"]["fulfillment"] == "UNKNOWN"


def test_discovery_tables_are_tenant_isolated_at_the_row_level(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    run_id = ci_discovery_run_repo.create_run(tenant_a, seller_product_ref="SKU-1", requested_by=uuid.uuid4())
    candidate_id = ci_candidate_repo.create_candidate(
        tenant_a, discovery_run_id=run_id, candidate_url="https://amazon.in/dp/abc"
    )
    breakdown = score_relevance(_relevance_inputs(), is_provisional=True)
    ci_candidate_relevance_repo.insert_relevance(tenant_a, candidate_id=candidate_id, breakdown=breakdown)

    with tenant_scope(tenant_b) as conn:
        assert conn.execute(text("SELECT * FROM ci_discovery_run")).fetchall() == []
        assert conn.execute(text("SELECT * FROM ci_candidate")).fetchall() == []
        assert conn.execute(text("SELECT * FROM ci_candidate_relevance")).fetchall() == []

    with tenant_scope(tenant_a) as conn:
        assert len(conn.execute(text("SELECT * FROM ci_discovery_run")).fetchall()) == 1
        assert len(conn.execute(text("SELECT * FROM ci_candidate")).fetchall()) == 1
        assert len(conn.execute(text("SELECT * FROM ci_candidate_relevance")).fetchall()) == 1


def test_tenant_cannot_write_a_candidate_under_another_tenants_id(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    run_id = ci_discovery_run_repo.create_run(tenant_a, seller_product_ref="SKU-1", requested_by=uuid.uuid4())
    with pytest.raises(Exception):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ci_candidate (id, tenant_id, discovery_run_id, candidate_url)
                    VALUES (:id, :tenant_id, :run_id, 'https://amazon.in/dp/spoofed')
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tenant_b), "run_id": str(run_id)},
            )
