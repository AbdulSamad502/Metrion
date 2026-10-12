"""R1 / Q-R10: what PI actually sends to third parties, pinned. The approval classification (ceo/effects.py) rests on these payloads; if one
changes (e.g. a SKU, brand or price is added to a query) this test fails and the action must be reclassified in the same change.

Fake provider clients record every outgoing query; nothing leaves the process."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from product_intelligence.direct_path.pi_discover import submit_pi_discover
from product_intelligence.direct_path.pi_supplier_lookup import lookup_suppliers_for_candidates
from product_intelligence.embedding.embed import MODEL_DIM
from product_intelligence.repositories import niche_brief_repo, product_candidate_repo
from product_intelligence.review_insight.text_extraction import TextExtractionResult, TextObservation
from product_intelligence.sources.cache import InProcessQueryCache
from product_intelligence.sources.tavily_client import TavilyImage, TavilySearchResult
from product_intelligence.sources.youtube_client import YoutubeVideo
from product_intelligence.supplier.google_places_client import PlaceDetails, PlaceIdResult

pytestmark = pytest.mark.usefixtures("two_tenants")
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
CATEGORY = "steel water bottle"
BUDGET_PAISE = 123456789  # a distinctive seller figure that must never appear in any outgoing query


class RecTavily:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query, *, include_images=False, max_results=10):
        self.queries.append(query)
        return [TavilySearchResult(url="https://example.com/p", title="Insulated Steel Bottle 1L Review", content="steel bottle priced at 799", score=0.9, published_date="2026-09-20", retrieved_at=NOW)]

    def images_for(self, query, *, max_images=5):
        return [TavilyImage(url="https://img.example.com/b.jpg", source_url="https://example.com/p", description="bottle")]


class RecYoutube:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_videos(self, query, *, max_results=10):
        self.queries.append(query)
        return [YoutubeVideo(video_id="v1", title="Steel Bottle Unboxing", channel_title="c", view_count=10, comment_count=1, thumbnail_url="t", published_at=NOW, retrieved_at=NOW)]

    def top_comments_for(self, video_id, *, max_comments=20):
        return ["good"]


class FakeText:
    def extract(self, texts, *, insight_source_type):
        return TextExtractionResult(insight_source_type=insight_source_type, observations=tuple(TextObservation(sentiment="POSITIVE", themes=("x",)) for _ in texts))


class FakeEmbed:
    def embed(self, text: str) -> list[float]:
        return [0.1] * MODEL_DIM


class RecPlaces:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_place_ids(self, query, *, max_results=10):
        self.queries.append(query)
        return [PlaceIdResult(place_id="pl1", display_name="Acme Metals", retrieved_at=NOW)]

    def enrich_place(self, place_id):
        return PlaceDetails(place_id=place_id, display_name="Acme Metals", phone=None, website=None, formatted_address=None, retrieved_at=NOW)


def _ready_brief(a, app_user):
    brief = niche_brief_repo.create_draft(
        a, created_by=app_user, category_text=CATEGORY, budget_paise=BUDGET_PAISE, target_price_min_paise=50000, target_price_max_paise=90000, marketplaces=["AMAZON"],
        constraints={"exclude_brands": ["SecretBrand"]},
    )
    niche_brief_repo.mark_ready(a, brief, readied_at=NOW)
    return brief


def test_pi_discover_sends_only_the_three_variants_of_the_seller_entered_niche_text(two_tenants, app_user):
    a, _ = two_tenants
    tavily, youtube = RecTavily(), RecYoutube()
    result = submit_pi_discover(
        a, _ready_brief(a, app_user), "SHALLOW", requested_by=app_user, permission_check="PASS", entitlement_check="PASS", tavily=tavily, youtube=youtube,
        cache=InProcessQueryCache(), text_extractor=FakeText(), embedding_client=FakeEmbed(), now=NOW,
    )
    assert result.status in ("COMPLETE", "PARTIAL")
    expected = {CATEGORY, f"best {CATEGORY} india", f"{CATEGORY} review"}
    assert set(tavily.queries) == expected and set(youtube.queries) == expected
    for q in [*tavily.queries, *youtube.queries]:
        assert str(BUDGET_PAISE) not in q and "SecretBrand" not in q and "AMAZON" not in q  # no other brief field leaves Metrion


def test_pi_supplier_lookup_sends_a_public_candidate_title_plus_the_fixed_suffix_and_nothing_seller_entered(two_tenants, app_user):
    a, _ = two_tenants
    brief = _ready_brief(a, app_user)
    result = submit_pi_discover(
        a, brief, "SHALLOW", requested_by=app_user, permission_check="PASS", entitlement_check="PASS", tavily=RecTavily(), youtube=RecYoutube(),
        cache=InProcessQueryCache(), text_extractor=FakeText(), embedding_client=FakeEmbed(), now=NOW,
    )
    candidates = product_candidate_repo.list_candidates_for_run(a, result.run_id)
    assert candidates, "the run produced no candidate to look up"
    titles = {str(c["candidate_title"]) for c in candidates}
    places, tavily = RecPlaces(), RecTavily()
    lookup_suppliers_for_candidates(a, run_id=result.run_id, candidate_ids=[c["id"] for c in candidates[:5]], places=places, tavily=tavily, now=NOW)
    sent = [*places.queries, *tavily.queries]
    assert sent, "no supplier query was sent"
    for q in sent:
        assert q.endswith(" manufacturer supplier wholesale india")
        assert q.removesuffix(" manufacturer supplier wholesale india") in titles  # a persisted candidate title, derived from public search results
        assert str(BUDGET_PAISE) not in q and "SecretBrand" not in q and "AMAZON" not in q
