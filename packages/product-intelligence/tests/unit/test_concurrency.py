"""Bug-fix pass (2026-09-30), Fix 3 — proves the sequential-for-loop -> bounded
`ThreadPoolExecutor` change in `discovery_run.py`/`direct_path/pi_discover.py`/
`direct_path/pi_supplier_lookup.py` is real concurrency, not just present in the code: a run
with N independently-slow fake I/O calls must complete in roughly max(latencies), not
sum(latencies)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from product_intelligence.direct_path import pi_discover, pi_supplier_lookup
from product_intelligence.discovery import discovery_run
from product_intelligence.discovery.discovery_run import CandidateRawSignals, DiscoveryRunOutcome
from product_intelligence.discovery.feasibility import FeasibilityOutcome
from product_intelligence.embedding.embed import EmbeddingUnavailable
from product_intelligence.repositories import (
    pi_research_run_repo,
    pi_tenant_config_repo,
    product_candidate_repo,
    supplier_lead_repo,
)
from product_intelligence.sources.cache import InProcessQueryCache
from product_intelligence.sources.tavily_client import TavilySearchResult
from product_intelligence.supplier.google_places_client import PlaceDetails, PlaceIdResult
from product_intelligence.review_insight.text_extraction import TextExtractionResult

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
_TENANT_ID = uuid4()
_RUN_ID = uuid4()
_SLEEP_SECONDS = 0.3
_QUERY_COUNT = 3  # matches _queries_for_niche's fixed 3-query fan-out


class _SlowTavilyClient:
    """Each call sleeps `_SLEEP_SECONDS` — a stand-in for real network latency. If the 3
    queries run sequentially, a full discovery pass takes >= 3 * _SLEEP_SECONDS; concurrent,
    it takes roughly 1 * _SLEEP_SECONDS."""

    def search(self, query, *, include_images=False, max_results=10):
        time.sleep(_SLEEP_SECONDS)
        return [
            TavilySearchResult(
                url=f"https://a.com/{query}", title=f"Result for {query}", content=f"content about {query}",
                score=0.9, published_date=None, retrieved_at=_NOW,
            )
        ]

    def images_for(self, query, *, max_images=5):
        return []


class _SlowYoutubeClient:
    def search_videos(self, query, *, max_results=10):
        time.sleep(_SLEEP_SECONDS)
        return []

    def top_comments_for(self, video_id, *, max_comments=20):
        return []


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pi_research_run_repo, "update_status", lambda *a, **kw: None)
    monkeypatch.setattr(pi_tenant_config_repo, "get_tavily_cache_ttl_hours", lambda tenant_id: 24)
    monkeypatch.setattr(pi_tenant_config_repo, "get_youtube_cache_ttl_hours", lambda tenant_id: 24)
    monkeypatch.setattr(product_candidate_repo, "insert_candidate", lambda tenant_id, **kw: uuid4())


def test_discovery_run_tavily_and_youtube_queries_run_concurrently_not_sequentially(_patch_repos) -> None:
    tavily = _SlowTavilyClient()
    youtube = _SlowYoutubeClient()
    niche_brief = {"category_text": "wireless earbuds", "marketplaces": ["AMAZON"]}

    started = time.monotonic()
    discovery_run.run_discovery(
        _TENANT_ID, run_id=_RUN_ID, niche_brief=niche_brief, tavily=tavily, youtube=youtube,
        cache=InProcessQueryCache(), now=_NOW,
    )
    elapsed = time.monotonic() - started

    # Sequential would take >= (3 + 3) * _SLEEP_SECONDS = 1.8s; concurrent (Tavily pool and
    # YouTube pool each run their 3 queries in parallel) should land close to
    # 2 * _SLEEP_SECONDS (one pool's single round, run one after the other) — a generous
    # upper bound well below the sequential total proves real concurrency, not flakiness.
    sequential_total = 2 * _QUERY_COUNT * _SLEEP_SECONDS
    assert elapsed < sequential_total * 0.7, (
        f"expected concurrent discovery run well under {sequential_total:.2f}s "
        f"(sequential total), took {elapsed:.2f}s"
    )


class _SlowEmbeddingClient:
    def embed(self, text: str) -> list[float]:
        time.sleep(_SLEEP_SECONDS)
        return [0.1] * 8


class _NoopTavily:
    def search(self, query, *, include_images=False, max_results=10):
        return []

    def images_for(self, query, *, max_images=5):
        return []


class _NoopYoutube:
    def search_videos(self, query, *, max_results=10):
        return []

    def top_comments_for(self, video_id, *, max_comments=20):
        return []


class _NoopExtractor:
    def extract(self, texts, *, insight_source_type):
        return TextExtractionResult(insight_source_type=insight_source_type, observations=())


def test_pi_discover_embedding_calls_run_concurrently_not_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from product_intelligence.repositories import niche_brief_repo

    monkeypatch.setattr(pi_research_run_repo, "create_run", lambda tenant_id, **kw: uuid4())
    monkeypatch.setattr(pi_research_run_repo, "finish_run", lambda tenant_id, run_id, **kw: None)
    monkeypatch.setattr(
        niche_brief_repo,
        "get_brief",
        lambda tenant_id, brief_id: {
            "id": "brief", "status": "READY", "category_text": "wireless earbuds", "marketplaces": ["AMAZON"]
        },
    )

    candidate_count = 5
    candidate_ids = [uuid4() for _ in range(candidate_count)]

    def _fake_run_discovery(tenant_id, *, run_id, niche_brief, tavily, youtube, cache, candidate_cap=30, product_extraction_client=None, now=None):
        raw_by_id = {
            cid: CandidateRawSignals((), (), None, None) for cid in candidate_ids
        }
        return DiscoveryRunOutcome(
            run_id=run_id, status="COMPLETE", candidate_ids=tuple(candidate_ids), partial_reason=None,
            tavily_degraded=False, youtube_degraded=False, raw_signals_by_candidate=raw_by_id,
        )

    monkeypatch.setattr(pi_discover, "run_discovery", _fake_run_discovery)
    monkeypatch.setattr(
        product_candidate_repo,
        "list_candidates_for_run",
        lambda tenant_id, run_id: [
            {"id": str(cid), "proxy_state": "COMPUTED", "proxy_score": "50.00",
             "title_length": 5, "title_structure": {}, "keyword_themes": {}}
            for cid in candidate_ids
        ],
    )

    def _slow_embed_candidate(tenant_id, candidate_id, *, title_length, title_structure, keyword_themes, client, now):
        time.sleep(_SLEEP_SECONDS)
        try:
            client.embed("some text")
        except Exception:
            pass

    monkeypatch.setattr(pi_discover, "embed_candidate", _slow_embed_candidate)
    monkeypatch.setattr(
        pi_discover,
        "compute_candidate_feasibility",
        lambda tenant_id, *, niche_brief, candidate, now=None: FeasibilityOutcome(
            status="UNAVAILABLE", estimate_ref=None, low_paise=None, high_paise=None,
            cogs_basis=None, assumptions=None, unavailable_reason="test stub — not exercised",
        ),
    )
    monkeypatch.setattr(product_candidate_repo, "update_feasibility", lambda *a, **kw: None)

    started = time.monotonic()
    result = pi_discover.submit_pi_discover(
        _TENANT_ID, uuid4(), "SHALLOW",
        requested_by=uuid4(), permission_check="PASS", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_NoopExtractor(), embedding_client=_SlowEmbeddingClient(), now=_NOW,
    )
    elapsed = time.monotonic() - started

    assert result.status == "COMPLETE"
    sequential_total = candidate_count * _SLEEP_SECONDS
    assert elapsed < sequential_total * 0.7, (
        f"expected concurrent embedding pass well under {sequential_total:.2f}s "
        f"(sequential total), took {elapsed:.2f}s"
    )


class _SlowPlaces:
    def search_place_ids(self, query, *, max_results=10):
        time.sleep(_SLEEP_SECONDS)
        return [PlaceIdResult(place_id="p1", display_name="Acme Supplier", retrieved_at=_NOW)]

    def enrich_place(self, place_id):
        return PlaceDetails(
            place_id=place_id, display_name="Acme Supplier", phone=None, website=None,
            formatted_address=None, retrieved_at=_NOW,
        )


class _SlowSupplierTavily:
    def search(self, query, *, include_images=False, max_results=10):
        time.sleep(_SLEEP_SECONDS)
        return []

    def images_for(self, query, *, max_images=5):
        return []


def test_pi_supplier_lookup_per_candidate_lookups_run_concurrently_not_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_count = 5
    candidate_ids = [uuid4() for _ in range(candidate_count)]
    monkeypatch.setattr(
        product_candidate_repo, "get_candidate", lambda tenant_id, cid: {"candidate_title": "wireless earbuds idea"}
    )
    monkeypatch.setattr(supplier_lead_repo, "insert_lead", lambda tenant_id, **kw: uuid4())

    started = time.monotonic()
    results = pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=candidate_ids, places=_SlowPlaces(), tavily=_SlowSupplierTavily(),
        now=_NOW,
    )
    elapsed = time.monotonic() - started

    assert len(results) == candidate_count
    # each candidate does one Places search sleep + one Tavily search sleep sequentially
    # *within* itself, so per-candidate latency is ~2 * _SLEEP_SECONDS; sequential across
    # candidates would be candidate_count * 2 * _SLEEP_SECONDS.
    sequential_total = candidate_count * 2 * _SLEEP_SECONDS
    assert elapsed < sequential_total * 0.7, (
        f"expected concurrent supplier lookup well under {sequential_total:.2f}s "
        f"(sequential total), took {elapsed:.2f}s"
    )
