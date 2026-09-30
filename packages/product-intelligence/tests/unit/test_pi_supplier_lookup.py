"""direct_path/pi_supplier_lookup.py — cost-bounding split enforcement (free search vs. paid
enrich), degrade-not-fail on source errors. Repository calls monkeypatched (no live
Postgres); Places/Tavily clients are in-memory fakes (never a live network call)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from product_intelligence.direct_path import pi_supplier_lookup
from product_intelligence.repositories import product_candidate_repo, supplier_lead_repo
from product_intelligence.sources.tavily_client import TavilySearchResult, TavilyUnavailable
from product_intelligence.supplier.google_places_client import PlaceDetails, PlaceIdResult, PlacesUnavailable

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
_TENANT_ID = uuid4()
_RUN_ID = uuid4()
_CANDIDATE_ID = uuid4()


class _FakePlaces:
    def __init__(self, matches: list[PlaceIdResult] | None = None, raises: bool = False) -> None:
        self._matches = matches if matches is not None else []
        self._raises = raises
        self.search_calls = 0
        self.enrich_calls: list[str] = []

    def search_place_ids(self, query, *, max_results=10):
        self.search_calls += 1
        if self._raises:
            raise PlacesUnavailable("timeout")
        return self._matches

    def enrich_place(self, place_id):
        self.enrich_calls.append(place_id)
        return PlaceDetails(
            place_id=place_id, display_name="Acme Supplier", phone="+91-999", website="https://acme.example.com",
            formatted_address="Mumbai", retrieved_at=_NOW,
        )


class _FakeTavily:
    def __init__(self, results: list[TavilySearchResult] | None = None, raises: bool = False) -> None:
        self._results = results or []
        self._raises = raises

    def search(self, query, *, include_images=False, max_results=10):
        if self._raises:
            raise TavilyUnavailable("rate limit")
        return self._results

    def images_for(self, query, *, max_images=5):
        return []


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        product_candidate_repo, "get_candidate", lambda tenant_id, cid: {"candidate_title": "wireless earbuds idea"}
    )
    inserted: list[dict] = []
    monkeypatch.setattr(
        supplier_lead_repo, "insert_lead", lambda tenant_id, **kw: (inserted.append(kw), uuid4())[1]
    )
    yield inserted


def test_enrich_place_called_only_for_the_single_best_match_never_every_match(_patch_repos) -> None:
    matches = [
        PlaceIdResult(place_id="p1", display_name="Supplier 1", retrieved_at=_NOW),
        PlaceIdResult(place_id="p2", display_name="Supplier 2", retrieved_at=_NOW),
        PlaceIdResult(place_id="p3", display_name="Supplier 3", retrieved_at=_NOW),
    ]
    places = _FakePlaces(matches=matches)
    tavily = _FakeTavily()

    pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=[_CANDIDATE_ID], places=places, tavily=tavily, now=_NOW
    )

    assert places.enrich_calls == ["p1"]


def test_places_degraded_falls_back_to_tavily_leads_only(_patch_repos) -> None:
    places = _FakePlaces(raises=True)
    tavily = _FakeTavily(
        results=[TavilySearchResult(url="https://a.com/1", title="Wholesale Supplier", content="c", score=0.9, published_date=None, retrieved_at=_NOW)]
    )

    results = pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=[_CANDIDATE_ID], places=places, tavily=tavily, now=_NOW
    )

    assert len(results) == 1
    assert len(results[0].lead_ids) == 1
    assert "Google Places unavailable" in results[0].degraded_reason


def test_no_leads_found_from_either_source_sets_degraded_reason(_patch_repos) -> None:
    places = _FakePlaces(matches=[])
    tavily = _FakeTavily(results=[])

    [result] = pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=[_CANDIDATE_ID], places=places, tavily=tavily, now=_NOW
    )

    assert result.lead_ids == ()
    assert "no supplier lead found" in result.degraded_reason


def test_candidate_not_found_is_named_never_a_fabricated_lead(monkeypatch: pytest.MonkeyPatch, _patch_repos) -> None:
    monkeypatch.setattr(product_candidate_repo, "get_candidate", lambda tenant_id, cid: None)
    places = _FakePlaces()
    tavily = _FakeTavily()

    [result] = pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=[_CANDIDATE_ID], places=places, tavily=tavily, now=_NOW
    )

    assert result.lead_ids == ()
    assert result.degraded_reason == "candidate not found"


def test_search_place_ids_bounded_to_max_matches_per_candidate(_patch_repos) -> None:
    places = _FakePlaces(matches=[PlaceIdResult(place_id="p1", display_name="S", retrieved_at=_NOW)])
    tavily = _FakeTavily()

    pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=[_CANDIDATE_ID], places=places, tavily=tavily, now=_NOW
    )

    assert places.search_calls == 1


def test_supplier_filter_rejects_retail_and_listicle_results_and_accepts_manufacturer(
    _patch_repos,
) -> None:
    """Bug-fix pass (2026-09-30): a real run surfaced a major brand's retail storefront and a
    "best shoes" listicle as supplier_lead rows alongside genuine leads. Both must now be
    filtered out; a manufacturer-shaped result must still pass through."""
    places = _FakePlaces(matches=[])
    tavily = _FakeTavily(
        results=[
            TavilySearchResult(
                url="https://www.amazon.in/redtape-shoes",
                title="Red Tape Running Shoes - Official Store | Buy Online",
                content="Shop the latest Red Tape running shoes online",
                score=0.95, published_date=None, retrieved_at=_NOW,
            ),
            TavilySearchResult(
                url="https://shoereview.example.com/best-running-shoes",
                title="10 Best Running Shoes in India (2026 Buying Guide)",
                content="Our review of the best running shoes available this year",
                score=0.9, published_date=None, retrieved_at=_NOW,
            ),
            TavilySearchResult(
                url="https://indiamart.com/acme-footwear-manufacturer",
                title="Acme Footwear Manufacturer - Running Shoe Wholesale Supplier India",
                content="Acme is a leading running shoe manufacturer and wholesale supplier based in Agra, India",
                score=0.85, published_date=None, retrieved_at=_NOW,
            ),
        ]
    )

    [result] = pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=[_CANDIDATE_ID], places=places, tavily=tavily, now=_NOW
    )

    assert len(result.lead_ids) == 1
    inserted = _patch_repos
    assert len(inserted) == 1
    assert inserted[0]["supplier_name"] == "Acme Footwear Manufacturer - Running Shoe Wholesale Supplier India"


def test_supplier_filter_prefers_supplier_signal_results_when_over_cap(_patch_repos) -> None:
    places = _FakePlaces(matches=[])
    tavily = _FakeTavily(
        results=[
            TavilySearchResult(
                url="https://a.example.com/1", title="Generic Shoe Company Ltd", content="a footwear company",
                score=0.9, published_date=None, retrieved_at=_NOW,
            ),
            TavilySearchResult(
                url="https://b.example.com/2", title="Footwear Wholesale Supplier Delhi", content="wholesale supplier",
                score=0.8, published_date=None, retrieved_at=_NOW,
            ),
        ]
    )

    pi_supplier_lookup.lookup_suppliers_for_candidates(
        _TENANT_ID, run_id=_RUN_ID, candidate_ids=[_CANDIDATE_ID], places=places, tavily=tavily, now=_NOW
    )

    inserted = _patch_repos
    assert inserted[0]["supplier_name"] == "Footwear Wholesale Supplier Delhi"
