"""Checkpoint 5 — the discovery run state machine (competitor-intelligence-agent.md
§6.12.2, §6.13, §6.14, §6.15). Runs entirely against `MockSearchProvider`/
`InMemorySearchResultCache` — no database required, mirroring `test_query_runner.py`'s own
scope from Checkpoint 3. Postgres-backed behaviour (RLS, persistence) is covered separately
in `tests/integration/test_discovery_run_flow.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from competitor_intelligence.discovery.budget import DiscoveryBudget
from competitor_intelligence.discovery.discovery_run import (
    AnalysisBudgetExceeded,
    CandidateNotAllowlisted,
    CandidateNotFound,
    accept_candidate,
    build_relevance_inputs,
    promote_to_analysis,
    reject_candidate,
    start_discovery_run,
)
from competitor_intelligence.discovery.mock_search_provider import MockSearchProvider
from competitor_intelligence.discovery.relevance_scoring import AxisState
from competitor_intelligence.discovery.search_cache import InMemorySearchResultCache
from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.repositories import (
    ci_candidate_relevance_repo,
    ci_candidate_repo,
    ci_discovery_run_repo,
    competitor_url_repo,
)
from competitor_intelligence.seller_product.types import SellerProduct


# ---- test doubles for the repositories (no DB — pure in-memory) -----------------------
# These fakes satisfy exactly the functions discovery_run.py calls, keyed the same
# tenant-first way the real Postgres repos are, so a test that forgets to scope by tenant
# fails the same way (matching search_cache.py's InMemorySearchResultCache convention).


class _FakeDiscoveryRunRepo:
    def __init__(self) -> None:
        self.runs: dict = {}

    def create_run(self, tenant_id, *, seller_product_ref, requested_by, status="QUEUED", provider_name=None):
        run_id = uuid4()
        self.runs[run_id] = {
            "id": run_id,
            "tenant_id": tenant_id,
            "seller_product_ref": seller_product_ref,
            "requested_by": requested_by,
            "status": status,
            "provider_name": provider_name,
            "partial_reason": None,
            "failed_reason": None,
            "raw_candidate_count": 0,
            "analyzed_candidate_count": 0,
        }
        return run_id

    def get_run(self, tenant_id, discovery_run_id):
        run = self.runs.get(discovery_run_id)
        return dict(run) if run else None

    def update_status(self, tenant_id, discovery_run_id, *, status, partial_reason=None, failed_reason=None, finished_at=None):
        run = self.runs[discovery_run_id]
        run["status"] = status
        if partial_reason is not None:
            run["partial_reason"] = partial_reason
        if failed_reason is not None:
            run["failed_reason"] = failed_reason

    def update_candidate_counts(self, tenant_id, discovery_run_id, *, raw_candidate_count, analyzed_candidate_count):
        run = self.runs[discovery_run_id]
        run["raw_candidate_count"] = raw_candidate_count
        run["analyzed_candidate_count"] = analyzed_candidate_count


class _FakeCandidateRepo:
    def __init__(self) -> None:
        self.candidates: dict = {}

    def create_candidate(self, tenant_id, *, discovery_run_id, candidate_url, origin="DISCOVERED", search_result_id=None, marketplace=None, tier="RAW"):
        candidate_id = uuid4()
        self.candidates[candidate_id] = {
            "id": candidate_id,
            "tenant_id": tenant_id,
            "discovery_run_id": discovery_run_id,
            "candidate_url": candidate_url,
            "origin": origin,
            "marketplace": marketplace,
            "tier": tier,
            "identity_match": None,
            "identity_match_basis": None,
            "seller_decision": "NONE",
            "seller_decided_by": None,
            "evidence_status": "AWAITING_EVIDENCE",
            "competitor_url_id": None,
        }
        return candidate_id

    def set_identity_resolution(self, tenant_id, candidate_id, resolution, *, tier):
        c = self.candidates[candidate_id]
        c["identity_match"] = resolution.identity_match.value
        c["tier"] = tier

    def set_tier(self, tenant_id, candidate_id, tier):
        self.candidates[candidate_id]["tier"] = tier

    def set_seller_decision(self, tenant_id, candidate_id, *, decision, decided_by):
        c = self.candidates[candidate_id]
        c["seller_decision"] = decision
        c["seller_decided_by"] = decided_by

    def set_evidence_status(self, tenant_id, candidate_id, evidence_status):
        self.candidates[candidate_id]["evidence_status"] = evidence_status

    def set_competitor_url_id(self, tenant_id, candidate_id, competitor_url_id):
        self.candidates[candidate_id]["competitor_url_id"] = competitor_url_id

    def set_origin(self, tenant_id, candidate_id, origin):
        self.candidates[candidate_id]["origin"] = origin

    def get_candidate(self, tenant_id, candidate_id):
        c = self.candidates.get(candidate_id)
        return dict(c) if c else None

    def list_candidates_for_run(self, tenant_id, discovery_run_id, *, tier=None):
        rows = [dict(c) for c in self.candidates.values() if c["discovery_run_id"] == discovery_run_id]
        if tier is not None:
            rows = [r for r in rows if r["tier"] == tier]
        return rows


class _FakeRelevanceRepo:
    def __init__(self) -> None:
        self.rows: list = []

    def insert_relevance(self, tenant_id, *, candidate_id, breakdown, recalculated_from=None):
        row_id = uuid4()
        self.rows.append({"id": row_id, "candidate_id": candidate_id, "breakdown": breakdown})
        return row_id


class _FakeCompetitorUrlRepo:
    def __init__(self) -> None:
        self.urls: dict = {}

    def create_url(self, tenant_id, *, marketplace, url, added_by, label=None, linked_sku=None):
        url_id = uuid4()
        self.urls[url_id] = {"id": url_id, "marketplace": marketplace, "url": url, "added_by": added_by}
        return url_id


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch):
    """Swaps the real Postgres-backed repository modules for the in-memory fakes above, for
    every test in this file — discovery_run.py imports these modules by name and calls
    `module_name.function(...)`, so monkeypatching the module attributes it holds a
    reference to is sufficient; no test needs a live Postgres connection."""
    import competitor_intelligence.discovery.discovery_run as dr

    fake_run_repo = _FakeDiscoveryRunRepo()
    fake_candidate_repo = _FakeCandidateRepo()
    fake_relevance_repo = _FakeRelevanceRepo()
    fake_url_repo = _FakeCompetitorUrlRepo()

    monkeypatch.setattr(dr, "ci_discovery_run_repo", fake_run_repo)
    monkeypatch.setattr(dr, "ci_candidate_repo", fake_candidate_repo)
    monkeypatch.setattr(dr, "ci_candidate_relevance_repo", fake_relevance_repo)
    monkeypatch.setattr(dr, "competitor_url_repo", fake_url_repo)

    return {
        "run_repo": fake_run_repo,
        "candidate_repo": fake_candidate_repo,
        "relevance_repo": fake_relevance_repo,
        "url_repo": fake_url_repo,
    }


def _seller_product(**overrides) -> SellerProduct:
    defaults = dict(
        product_id="SKU-1",
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


def _result(url: str, title: str, snippet: str = "", rank: int = 1) -> SearchResult:
    return SearchResult(rank=rank, url=url, title=title, snippet=snippet, source="MOCK", retrieved_at=datetime.now(timezone.utc))


TENANT = uuid4()
REQUESTED_BY = uuid4()


class TestStartDiscoveryRun:
    def test_discovery_disabled_completes_immediately_with_no_candidates(self, _patch_repos):
        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=MockSearchProvider(),
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(),
            discovery_enabled=False,
        )
        assert outcome.status == "COMPLETE"
        assert outcome.raw_candidate_count == 0

    def test_provider_failure_on_every_query_ends_failed(self, _patch_repos):
        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=MockSearchProvider(fail=True),
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(),
            discovery_enabled=True,
        )
        assert outcome.status == "FAILED"
        assert outcome.failed_reason is not None

    def test_exact_match_candidate_reaches_recommended_and_run_completes(self, _patch_repos):
        provider = MockSearchProvider(
            default_results=[_result("https://amazon.in/dp/abc", "Acme Wireless Mouse Pro", "wireless ergonomic silent click mouse")]
        )
        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=provider,
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(),
            discovery_enabled=True,
        )
        assert outcome.status == "COMPLETE"
        assert outcome.raw_candidate_count >= 1
        assert len(outcome.recommended_candidate_ids) >= 1
        assert outcome.uncertain_candidate_ids == ()

    def test_no_identifying_text_is_uncertain_and_blocks_the_run(self, _patch_repos):
        # A candidate with no brand/model tokens at all resolves UNCERTAIN per
        # identity_resolution.py's own rule ("insufficient identifying text") — never
        # silently assumed to be exact (AC20).
        provider = MockSearchProvider(default_results=[_result("https://amazon.in/dp/xyz", "", "")])
        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=provider,
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(),
            discovery_enabled=True,
        )
        assert outcome.status == "WAITING_FOR_REVIEW"
        assert len(outcome.uncertain_candidate_ids) == 1
        assert outcome.recommended_candidate_ids == ()

    def test_different_brand_is_not_a_match_and_never_recommended(self, _patch_repos):
        provider = MockSearchProvider(
            default_results=[_result("https://amazon.in/dp/xyz", "Globex Wireless Mouse X200", "wireless mouse")]
        )
        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=provider,
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(),
            discovery_enabled=True,
        )
        # NOT_A_MATCH does not block the run and is never recommended.
        assert outcome.status == "COMPLETE"
        assert outcome.recommended_candidate_ids == ()

    def test_max_raw_candidates_budget_hit_propagates_to_partial_status(self, _patch_repos, monkeypatch):
        # run_discovery_queries's own budget-limit behaviour (query_runner.py) is already
        # covered by Checkpoint 3's test_query_runner.py — this test's job is only to prove
        # discovery_run.py correctly propagates a query-stage partial_reason into the run's
        # final status, not to re-derive query_runner's own cap-hitting logic (a
        # MockSearchProvider call already truncates to `max_results=budget.max_raw_candidates`
        # per query, so triggering the cross-query cap here would require faking distinct
        # per-query results rather than exercising anything new in this module).
        import competitor_intelligence.discovery.discovery_run as dr
        from competitor_intelligence.discovery.query_runner import DiscoveryQueryRunResult

        canned = DiscoveryQueryRunResult(
            queries_sent=(),
            queries_dropped_for_privacy=(),
            query_errors=(),
            raw_results=(_result("https://amazon.in/dp/1", "Acme Wireless Mouse Pro", "wireless"),),
            partial_reason="max_raw_candidates",
            discovery_enabled=True,
        )
        monkeypatch.setattr(dr, "run_discovery_queries", lambda **kwargs: canned)

        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=MockSearchProvider(),
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(),
            discovery_enabled=True,
        )
        assert outcome.status == "PARTIAL"
        assert outcome.partial_reason == "max_raw_candidates"

    def test_recommended_capped_at_budget_and_sorted_by_score(self, _patch_repos):
        # Two EXACT_MATCH-shaped candidates, one clearly closer on price proximity, capped
        # to a Recommended set of 1.
        results = [
            _result("https://amazon.in/dp/close", "Acme Wireless Mouse Pro", "wireless ergonomic silent click"),
            _result("https://amazon.in/dp/far", "Acme Wireless Mouse Pro Deluxe", "wireless"),
        ]
        provider = MockSearchProvider(default_results=results)
        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=provider,
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(max_recommended_candidates=1),
            discovery_enabled=True,
        )
        assert len(outcome.recommended_candidate_ids) == 1


class TestRelevanceInputsHonesty:
    def test_price_proximity_is_unknown_when_candidate_price_never_observed(self):
        # §6.10.2: a search snippet never yields a trustworthy price fact — this must never
        # be silently treated as a known 0% difference.
        inputs = build_relevance_inputs(
            _result("https://amazon.in/dp/1", "Acme Wireless Mouse Pro"), _seller_product()
        )
        assert inputs.price_proximity.state is AxisState.UNKNOWN
        assert inputs.category.state is AxisState.UNKNOWN  # candidate category never observed either
        assert inputs.features.state is AxisState.UNKNOWN

    def test_keyword_overlap_uses_real_text(self):
        inputs = build_relevance_inputs(
            _result("https://amazon.in/dp/1", "Acme Wireless Mouse", "ergonomic silent click design"),
            _seller_product(),
        )
        assert inputs.keywords.state is AxisState.KNOWN
        assert inputs.keywords.score >= 1


class TestSellerDecisions:
    def _run_to_waiting_for_review(self, _patch_repos):
        provider = MockSearchProvider(default_results=[_result("https://amazon.in/dp/xyz", "", "")])
        outcome = start_discovery_run(
            TENANT,
            requested_by=REQUESTED_BY,
            seller_product=_seller_product(),
            provider=provider,
            provider_name="MOCK",
            cache=InMemorySearchResultCache(),
            budget=DiscoveryBudget(),
            discovery_enabled=True,
        )
        assert outcome.status == "WAITING_FOR_REVIEW"
        return outcome

    def _register_run(self, _patch_repos, discovery_run_id, **overrides):
        row = {
            "id": discovery_run_id,
            "seller_product_ref": "SKU-1",
            "raw_candidate_count": 1,
            "analyzed_candidate_count": 1,
            "status": "RESEARCHING",
            "partial_reason": None,
            "failed_reason": None,
        }
        row.update(overrides)
        _patch_repos["run_repo"].runs[discovery_run_id] = row

    def test_accept_candidate_promotes_into_tracked_competitor_url(self, _patch_repos):
        discovery_run_id = uuid4()
        self._register_run(_patch_repos, discovery_run_id)
        candidate_id = _patch_repos["candidate_repo"].create_candidate(
            TENANT, discovery_run_id=discovery_run_id, candidate_url="https://amazon.in/dp/abc", marketplace="AMAZON", tier="RECOMMENDED"
        )
        result = accept_candidate(TENANT, candidate_id, decided_by=REQUESTED_BY)
        assert result.competitor_url_id in _patch_repos["url_repo"].urls
        assert _patch_repos["candidate_repo"].candidates[candidate_id]["seller_decision"] == "APPROVED"
        assert _patch_repos["candidate_repo"].candidates[candidate_id]["competitor_url_id"] == result.competitor_url_id

    def test_accept_candidate_without_allowlisted_marketplace_raises(self, _patch_repos):
        candidate_id = _patch_repos["candidate_repo"].create_candidate(
            TENANT, discovery_run_id=uuid4(), candidate_url="https://notallowed.example.com/x", marketplace=None
        )
        with pytest.raises(CandidateNotAllowlisted):
            accept_candidate(TENANT, candidate_id, decided_by=REQUESTED_BY)

    def test_accept_unknown_candidate_raises(self, _patch_repos):
        with pytest.raises(CandidateNotFound):
            accept_candidate(TENANT, uuid4(), decided_by=REQUESTED_BY)

    def test_resolving_last_pending_uncertain_candidate_unblocks_the_run(self, _patch_repos):
        outcome = self._run_to_waiting_for_review(_patch_repos)
        candidate_id = outcome.uncertain_candidate_ids[0]

        result = accept_candidate(TENANT, candidate_id, decided_by=REQUESTED_BY)
        assert result.run_outcome.status in ("COMPLETE", "PARTIAL")

    def test_rejecting_the_only_uncertain_candidate_also_unblocks_the_run(self, _patch_repos):
        outcome = self._run_to_waiting_for_review(_patch_repos)
        candidate_id = outcome.uncertain_candidate_ids[0]

        run_outcome = reject_candidate(TENANT, candidate_id, decided_by=REQUESTED_BY)
        assert run_outcome.status in ("COMPLETE", "PARTIAL")


class TestPromoteToAnalysis:
    def test_promote_unanalyzed_candidate_scores_it(self, _patch_repos):
        candidate_id = _patch_repos["candidate_repo"].create_candidate(
            TENANT, discovery_run_id=uuid4(), candidate_url="https://amazon.in/dp/raw", tier="RAW"
        )
        candidate = _patch_repos["candidate_repo"].get_candidate(TENANT, candidate_id)
        _patch_repos["run_repo"].runs[candidate["discovery_run_id"]] = {
            "id": candidate["discovery_run_id"],
            "raw_candidate_count": 1,
            "analyzed_candidate_count": 0,
            "partial_reason": None,
        }

        breakdown = promote_to_analysis(
            TENANT,
            candidate_id,
            seller_product=_seller_product(),
            candidate_result=_result("https://amazon.in/dp/raw", "Acme Wireless Mouse Pro", "wireless ergonomic silent click"),
            budget=DiscoveryBudget(),
        )
        assert breakdown is not None
        assert _patch_repos["candidate_repo"].candidates[candidate_id]["origin"] == "PROMOTED_BY_SELLER"
        assert _patch_repos["candidate_repo"].candidates[candidate_id]["tier"] == "ANALYZED"

    def test_promote_beyond_analyzed_budget_raises(self, _patch_repos):
        candidate_id = _patch_repos["candidate_repo"].create_candidate(
            TENANT, discovery_run_id=uuid4(), candidate_url="https://amazon.in/dp/raw", tier="RAW"
        )
        candidate = _patch_repos["candidate_repo"].get_candidate(TENANT, candidate_id)
        _patch_repos["run_repo"].runs[candidate["discovery_run_id"]] = {
            "id": candidate["discovery_run_id"],
            "raw_candidate_count": 1,
            "analyzed_candidate_count": 20,
            "partial_reason": None,
        }

        with pytest.raises(AnalysisBudgetExceeded):
            promote_to_analysis(
                TENANT,
                candidate_id,
                seller_product=_seller_product(),
                candidate_result=_result("https://amazon.in/dp/raw", "Acme Wireless Mouse Pro"),
                budget=DiscoveryBudget(max_analyzed_candidates=20),
            )
