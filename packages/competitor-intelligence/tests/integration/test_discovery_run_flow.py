"""Checkpoint 5 — the discovery run state machine, end to end against a real Postgres:
QUEUED -> SEARCHING -> DISCOVERING -> WAITING_FOR_REVIEW/RESEARCHING -> COMPLETE/PARTIAL,
seller accept/reject/promote decisions, and the accept -> tracked competitor_url promotion
(competitor-intelligence-agent.md §6.12.2, §6.13, §6.14, §6.15). Unit-level state-machine
behaviour against mocked repositories is covered in tests/unit/test_discovery_run.py — this
file's job is proving the same orchestration works against the real
`ci_discovery_run`/`ci_candidate`/`ci_candidate_relevance` tables, the real
`PostgresSearchResultCache`, tenant isolation (RLS), and the real `competitor_url` table a
candidate gets promoted into.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from competitor_intelligence.discovery.budget import DiscoveryBudget
from competitor_intelligence.discovery.discovery_run import (
    accept_candidate,
    reject_candidate,
    start_discovery_run,
)
from competitor_intelligence.discovery.mock_search_provider import MockSearchProvider
from competitor_intelligence.discovery.search_cache import PostgresSearchResultCache
from competitor_intelligence.repositories import (
    ci_candidate_repo,
    ci_discovery_run_repo,
    competitor_url_repo,
)
from competitor_intelligence.repositories.tenant_context import tenant_scope
from competitor_intelligence.seller_product.types import SellerProduct

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _seller_product(**overrides) -> SellerProduct:
    defaults = dict(
        product_id="SKU-DISCOVERY-1",
        title="Acme Wireless Mouse Pro",
        category="Computer Accessories",
        price_paise=89_900,
        attributes=(("brand", "Acme"),),
        keywords=("wireless", "ergonomic", "silent click"),
        fulfillment_type="SELLER_FULFILLED",
        review_count=None,
        rating=None,
        last_updated=datetime.now(timezone.utc),
        field_source={},
    )
    defaults.update(overrides)
    return SellerProduct(**defaults)


def test_exact_match_candidate_flows_through_to_recommended_and_accept(two_tenants) -> None:
    tenant_a, _ = two_tenants
    requested_by = uuid.uuid4()

    provider = MockSearchProvider(
        default_results=[]  # generate_queries produces several distinct query texts; use fixtures below
    )
    # Real query text is generated internally — target every possible generated query with
    # the same real-looking candidate via a provider that ignores the query text entirely
    # (default_results, not exact fixtures), exactly like the unit tests in this checkpoint.
    from competitor_intelligence.discovery.search_provider import SearchResult

    provider = MockSearchProvider(
        default_results=[
            SearchResult(
                rank=1,
                url="https://amazon.in/dp/e2e-exact",
                title="Acme Wireless Mouse Pro",
                snippet="wireless ergonomic silent click mouse",
                source="MOCK",
                retrieved_at=datetime.now(timezone.utc),
            )
        ]
    )

    outcome = start_discovery_run(
        tenant_a,
        requested_by=requested_by,
        seller_product=_seller_product(),
        provider=provider,
        provider_name="MOCK",
        cache=PostgresSearchResultCache(),
        budget=DiscoveryBudget(),
        discovery_enabled=True,
    )

    assert outcome.status == "COMPLETE"
    assert outcome.raw_candidate_count >= 1
    assert len(outcome.recommended_candidate_ids) >= 1

    run = ci_discovery_run_repo.get_run(tenant_a, outcome.discovery_run_id)
    assert run["status"] == "COMPLETE"

    # Real ci_search_query/ci_search_result rows exist (PostgresSearchResultCache actually
    # persisted them, not just an in-memory fake) — proves this checkpoint's orchestration
    # is wired to the real Checkpoint 3 persistence layer, not bypassing it.
    with tenant_scope(tenant_a) as conn:
        query_count = conn.execute(text("SELECT count(*) FROM ci_search_query WHERE discovery_run_id = :id"), {"id": str(outcome.discovery_run_id)}).scalar_one()
        assert query_count > 0

    recommended_id = outcome.recommended_candidate_ids[0]
    candidate = ci_candidate_repo.get_candidate(tenant_a, recommended_id)
    assert candidate["tier"] == "RECOMMENDED"
    assert candidate["identity_match"] == "EXACT_MATCH"
    assert candidate["evidence_status"] == "AWAITING_EVIDENCE"

    # Accepting promotes it into a real, tenant-scoped competitor_url row (§6.15 rule 6),
    # subject to the same C4/D7 allowlist competitor_url_repo already enforces.
    result = accept_candidate(tenant_a, recommended_id, decided_by=requested_by)
    tracked = competitor_url_repo.get_by_ids(tenant_a, [result.competitor_url_id])
    assert len(tracked) == 1
    assert tracked[0]["url"] == "https://amazon.in/dp/e2e-exact"
    assert tracked[0]["marketplace"] == "AMAZON"

    accepted_candidate = ci_candidate_repo.get_candidate(tenant_a, recommended_id)
    assert accepted_candidate["seller_decision"] == "APPROVED"
    assert accepted_candidate["competitor_url_id"] == result.competitor_url_id


def test_uncertain_candidate_blocks_run_until_seller_decides(two_tenants) -> None:
    tenant_a, _ = two_tenants
    requested_by = uuid.uuid4()

    from competitor_intelligence.discovery.search_provider import SearchResult

    # No title/snippet at all -> resolve_identity's "insufficient identifying text" path ->
    # UNCERTAIN (never silently assumed to be exact, AC20).
    provider = MockSearchProvider(
        default_results=[
            SearchResult(rank=1, url="https://flipkart.com/p/e2e-uncertain", title=None, snippet=None, source="MOCK", retrieved_at=datetime.now(timezone.utc))
        ]
    )

    outcome = start_discovery_run(
        tenant_a,
        requested_by=requested_by,
        seller_product=_seller_product(product_id="SKU-DISCOVERY-2"),
        provider=provider,
        provider_name="MOCK",
        cache=PostgresSearchResultCache(),
        budget=DiscoveryBudget(),
        discovery_enabled=True,
    )

    assert outcome.status == "WAITING_FOR_REVIEW"
    assert len(outcome.uncertain_candidate_ids) == 1

    run = ci_discovery_run_repo.get_run(tenant_a, outcome.discovery_run_id)
    assert run["status"] == "WAITING_FOR_REVIEW"

    candidate_id = outcome.uncertain_candidate_ids[0]
    run_outcome = reject_candidate(tenant_a, candidate_id, decided_by=requested_by)

    assert run_outcome.status in ("COMPLETE", "PARTIAL")
    final_run = ci_discovery_run_repo.get_run(tenant_a, outcome.discovery_run_id)
    assert final_run["status"] == run_outcome.status

    rejected_candidate = ci_candidate_repo.get_candidate(tenant_a, candidate_id)
    assert rejected_candidate["seller_decision"] == "REJECTED"
    assert rejected_candidate["competitor_url_id"] is None


def test_discovery_run_rows_are_tenant_isolated(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    requested_by = uuid.uuid4()

    outcome = start_discovery_run(
        tenant_a,
        requested_by=requested_by,
        seller_product=_seller_product(product_id="SKU-DISCOVERY-3"),
        provider=MockSearchProvider(),  # no results at all — discovery_enabled path with an
        # empty provider is enough to prove row-level isolation without needing candidates
        provider_name="MOCK",
        cache=PostgresSearchResultCache(),
        budget=DiscoveryBudget(),
        discovery_enabled=True,
    )

    with tenant_scope(tenant_b) as conn:
        assert conn.execute(text("SELECT * FROM ci_discovery_run WHERE id = :id"), {"id": str(outcome.discovery_run_id)}).fetchall() == []

    with tenant_scope(tenant_a) as conn:
        assert len(conn.execute(text("SELECT * FROM ci_discovery_run WHERE id = :id"), {"id": str(outcome.discovery_run_id)}).fetchall()) == 1


def test_discovery_disabled_never_sends_a_query_and_completes_with_no_candidates(two_tenants) -> None:
    tenant_a, _ = two_tenants
    outcome = start_discovery_run(
        tenant_a,
        requested_by=uuid.uuid4(),
        seller_product=_seller_product(product_id="SKU-DISCOVERY-4"),
        provider=MockSearchProvider(fail=True),  # would raise if ever called
        provider_name="MOCK",
        cache=PostgresSearchResultCache(),
        budget=DiscoveryBudget(),
        discovery_enabled=False,
    )
    assert outcome.status == "COMPLETE"
    assert outcome.raw_candidate_count == 0
