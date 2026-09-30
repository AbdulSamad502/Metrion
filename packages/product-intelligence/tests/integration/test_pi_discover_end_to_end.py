"""Full `submit_pi_discover(...)` run against fake Tavily/YouTube clients and a real local
Postgres — never a live external API call. Verifies the whole direct_path call chain: run
status, revised `product_candidate` schema, review insights, embeddings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from product_intelligence.direct_path.pi_discover import submit_pi_discover
from product_intelligence.embedding.embed import MODEL_DIM
from product_intelligence.repositories import (
    niche_brief_repo,
    product_candidate_repo,
    product_embedding_repo,
    product_review_insight_repo,
)
from product_intelligence.repositories.tenant_context import tenant_scope
from product_intelligence.review_insight.text_extraction import TextExtractionResult, TextObservation
from product_intelligence.sources.cache import InProcessQueryCache
from product_intelligence.sources.tavily_client import TavilyImage, TavilySearchResult, TavilyUnavailable
from product_intelligence.sources.youtube_client import YoutubeVideo

pytestmark = pytest.mark.usefixtures("_clean_pi_tables")

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


class _FakeTavilyClient:
    def __init__(self, raises: bool = False) -> None:
        self._raises = raises

    def search(self, query, *, include_images=False, max_results=10):
        if self._raises:
            raise TavilyUnavailable("simulated Tavily outage")
        return [
            TavilySearchResult(
                url="https://example.com/wireless-earbuds",
                title="Wireless Earbuds Charging Case Review",
                content="These wireless earbuds with a charging case are priced at ₹1,499 in most listings",
                score=0.95,
                published_date="2026-09-20",
                retrieved_at=_NOW,
            )
        ]

    def images_for(self, query, *, max_images=5):
        return [
            TavilyImage(
                url="https://img.example.com/earbuds.jpg",
                source_url="https://example.com/wireless-earbuds",
                description="wireless earbuds charging case",
            )
        ]


class _FakeYoutubeClient:
    def __init__(self, raises: bool = False) -> None:
        self._raises = raises

    def search_videos(self, query, *, max_results=10):
        return [
            YoutubeVideo(
                video_id="abc123",
                title="Wireless Earbuds Charging Case Unboxing",
                channel_title="Tech Reviews India",
                view_count=25_000,
                comment_count=120,
                thumbnail_url="https://img.example.com/thumb.jpg",
                published_at=_NOW,
                retrieved_at=_NOW,
            )
        ]

    def top_comments_for(self, video_id, *, max_comments=20):
        return ["Great battery life on these!", "Case broke after a month, disappointed"]


class _FakeTextExtractor:
    def extract(self, texts, *, insight_source_type):
        sentiments = ["POSITIVE", "NEGATIVE"]
        return TextExtractionResult(
            insight_source_type=insight_source_type,
            observations=tuple(
                TextObservation(sentiment=sentiments[i % 2], themes=("battery life",)) for i in range(len(texts))
            ),
        )


class _FakeEmbeddingClient:
    def embed(self, text: str) -> list[float]:
        return [0.1] * MODEL_DIM


def _create_ready_brief(tenant_id: uuid.UUID) -> uuid.UUID:
    brief_id = niche_brief_repo.create_draft(
        tenant_id,
        created_by=uuid.uuid4(),
        category_text="wireless earbuds",
        budget_paise=500_000,
        marketplaces=["AMAZON"],
    )
    niche_brief_repo.mark_ready(tenant_id, brief_id, readied_at=_NOW)
    return brief_id


def test_full_discover_run_reaches_complete_with_populated_candidates() -> None:
    tenant_id = uuid.uuid4()
    brief_id = _create_ready_brief(tenant_id)

    result = submit_pi_discover(
        tenant_id,
        brief_id,
        "SHALLOW",
        requested_by=uuid.uuid4(),
        permission_check="PASS",
        entitlement_check="PASS",
        tavily=_FakeTavilyClient(),
        youtube=_FakeYoutubeClient(),
        cache=InProcessQueryCache(),
        text_extractor=_FakeTextExtractor(),
        embedding_client=_FakeEmbeddingClient(),
        now=_NOW,
    )

    assert result.status == "COMPLETE"
    assert len(result.candidate_ids) >= 1

    candidates = product_candidate_repo.list_candidates_for_run(tenant_id, result.run_id)
    assert len(candidates) == len(result.candidate_ids)
    for candidate in candidates:
        assert candidate["demand_signal"] == {
            "status": "UNAVAILABLE",
            "reason": "Google Ads API access pending brand verification",
        }
        assert candidate["opportunity_label"] == "CANDIDATE_OPPORTUNITY"
        assert candidate["score_explanation"]["signals"]
        assert candidate["score_explanation"]["summary"]


def test_review_insights_and_embeddings_are_written_for_the_shortlist() -> None:
    tenant_id = uuid.uuid4()
    brief_id = _create_ready_brief(tenant_id)

    result = submit_pi_discover(
        tenant_id,
        brief_id,
        "SHALLOW",
        requested_by=uuid.uuid4(),
        permission_check="PASS",
        entitlement_check="PASS",
        tavily=_FakeTavilyClient(),
        youtube=_FakeYoutubeClient(),
        cache=InProcessQueryCache(),
        text_extractor=_FakeTextExtractor(),
        embedding_client=_FakeEmbeddingClient(),
        now=_NOW,
    )

    assert result.shortlisted_candidate_ids
    candidate_id = result.shortlisted_candidate_ids[0]

    insights = product_review_insight_repo.list_insights_for_candidate(tenant_id, candidate_id)
    assert insights, "expected at least one product_review_insight row for the shortlisted candidate"
    for insight in insights:
        assert insight["insight_source_type"] in ("YOUTUBE_COMMENTARY", "WEB_EDITORIAL")

    embeddings = product_embedding_repo.get_embeddings_for_subject(tenant_id, "CANDIDATE", candidate_id)
    assert len(embeddings) == 1


def test_source_degradation_yields_partial_status_with_a_named_reason() -> None:
    tenant_id = uuid.uuid4()
    brief_id = _create_ready_brief(tenant_id)

    result = submit_pi_discover(
        tenant_id,
        brief_id,
        "SHALLOW",
        requested_by=uuid.uuid4(),
        permission_check="PASS",
        entitlement_check="PASS",
        tavily=_FakeTavilyClient(raises=True),
        youtube=_FakeYoutubeClient(),
        cache=InProcessQueryCache(),
        text_extractor=_FakeTextExtractor(),
        embedding_client=_FakeEmbeddingClient(),
        now=_NOW,
    )

    assert result.status == "PARTIAL"
    assert result.partial_reason is not None
    assert "Tavily unavailable" in result.partial_reason


def test_run_row_persisted_with_correct_final_status(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    brief_id = _create_ready_brief(tenant_id)

    result = submit_pi_discover(
        tenant_id,
        brief_id,
        "SHALLOW",
        requested_by=uuid.uuid4(),
        permission_check="PASS",
        entitlement_check="PASS",
        tavily=_FakeTavilyClient(),
        youtube=_FakeYoutubeClient(),
        cache=InProcessQueryCache(),
        text_extractor=_FakeTextExtractor(),
        embedding_client=_FakeEmbeddingClient(),
        now=_NOW,
    )

    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            text("SELECT status FROM pi_research_run WHERE id = :id"), {"id": str(result.run_id)}
        ).mappings().first()
    assert row["status"] == result.status
