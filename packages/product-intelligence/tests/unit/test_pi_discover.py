"""direct_path/pi_discover.py — fail-closed permission/entitlement, shortlist selection,
degrade-not-fail aggregation. Repository calls monkeypatched (no live Postgres); Tavily/
YouTube/embedding/text-extractor are in-memory fakes (never a live network call)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from product_intelligence.direct_path import pi_discover
from product_intelligence.discovery.discovery_run import DiscoveryRunOutcome
from product_intelligence.discovery.feasibility import FeasibilityOutcome
from product_intelligence.embedding.embed import EmbeddingUnavailable
from product_intelligence.repositories import niche_brief_repo, pi_research_run_repo, product_candidate_repo
from product_intelligence.sources.cache import InProcessQueryCache
from product_intelligence.sources.tavily_client import TavilyClient
from product_intelligence.sources.youtube_client import YoutubeClient
from product_intelligence.review_insight.text_extraction import TextExtractionResult, TextObservation

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
_TENANT_ID = uuid4()
_BRIEF_ID = uuid4()
_REQUESTED_BY = uuid4()


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


class _FakeExtractor:
    def extract(self, texts, *, insight_source_type):
        return TextExtractionResult(
            insight_source_type=insight_source_type,
            observations=tuple(TextObservation(sentiment="POSITIVE", themes=()) for _ in texts),
        )


class _FakeEmbeddingClient:
    def __init__(self, dim: int = 768) -> None:
        self._dim = dim

    def embed(self, text: str) -> list[float]:
        return [0.1] * self._dim


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pi_research_run_repo, "create_run", lambda tenant_id, **kw: uuid4())
    monkeypatch.setattr(pi_research_run_repo, "finish_run", lambda tenant_id, run_id, **kw: None)
    # Harmless default for every test that doesn't care about feasibility specifically —
    # a real DB-free UNAVAILABLE outcome, not a mock that silently claims COMPUTED.
    monkeypatch.setattr(
        pi_discover,
        "compute_candidate_feasibility",
        lambda tenant_id, *, niche_brief, candidate, now=None: FeasibilityOutcome(
            status="UNAVAILABLE", estimate_ref=None, low_paise=None, high_paise=None,
            cogs_basis=None, assumptions=None, unavailable_reason="test default — not exercised",
        ),
    )
    monkeypatch.setattr(product_candidate_repo, "update_feasibility", lambda *a, **kw: None)


def _ready_brief() -> dict:
    return {"id": str(_BRIEF_ID), "status": "READY", "category_text": "wireless earbuds", "marketplaces": ["AMAZON"]}


def test_fails_closed_when_permission_check_is_not_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niche_brief_repo, "get_brief", lambda tenant_id, brief_id: _ready_brief())

    result = pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="FAIL", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=_FakeEmbeddingClient(), now=_NOW,
    )

    assert result.status == "FAILED"
    assert result.candidate_ids == ()
    assert "permission or entitlement" in result.failed_reason


def test_fails_closed_when_entitlement_check_is_not_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niche_brief_repo, "get_brief", lambda tenant_id, brief_id: _ready_brief())

    result = pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="PASS", entitlement_check="FAIL",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=_FakeEmbeddingClient(), now=_NOW,
    )

    assert result.status == "FAILED"


def test_fails_closed_when_niche_brief_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        niche_brief_repo, "get_brief", lambda tenant_id, brief_id: {**_ready_brief(), "status": "DRAFT"}
    )

    result = pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="PASS", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=_FakeEmbeddingClient(), now=_NOW,
    )

    assert result.status == "FAILED"
    assert "not READY" in result.failed_reason


def test_fails_closed_when_niche_brief_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niche_brief_repo, "get_brief", lambda tenant_id, brief_id: None)

    result = pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="PASS", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=_FakeEmbeddingClient(), now=_NOW,
    )

    assert result.status == "FAILED"


def test_successful_run_shortlists_top_candidates_by_proxy_score_and_embeds_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(niche_brief_repo, "get_brief", lambda tenant_id, brief_id: _ready_brief())

    candidate_ids = [uuid4() for _ in range(3)]
    raw_by_id = {}

    def _fake_run_discovery(tenant_id, *, run_id, niche_brief, tavily, youtube, cache, candidate_cap=30, product_extraction_client=None, now=None):
        from product_intelligence.discovery.discovery_run import CandidateRawSignals

        for cid in candidate_ids:
            raw_by_id[cid] = CandidateRawSignals(
                youtube_video_ids=(), web_snippet_texts=(), primary_youtube_source_url=None, primary_web_source_url=None
            )
        return DiscoveryRunOutcome(
            run_id=run_id, status="COMPLETE", candidate_ids=tuple(candidate_ids), partial_reason=None,
            tavily_degraded=False, youtube_degraded=False, raw_signals_by_candidate=raw_by_id,
        )

    monkeypatch.setattr(pi_discover, "run_discovery", _fake_run_discovery)

    scores = {candidate_ids[0]: "30.00", candidate_ids[1]: "90.00", candidate_ids[2]: "60.00"}
    monkeypatch.setattr(
        product_candidate_repo,
        "list_candidates_for_run",
        lambda tenant_id, run_id: [
            {"id": str(cid), "proxy_state": "COMPUTED", "proxy_score": scores[cid],
             "title_length": 5, "title_structure": {}, "keyword_themes": {}}
            for cid in candidate_ids
        ],
    )

    embedded_ids: list[str] = []
    monkeypatch.setattr(
        pi_discover,
        "embed_candidate",
        lambda tenant_id, candidate_id, **kw: embedded_ids.append(str(candidate_id)),
    )

    result = pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="PASS", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=_FakeEmbeddingClient(), now=_NOW,
    )

    assert result.status == "COMPLETE"
    # highest proxy_score first
    assert result.shortlisted_candidate_ids[0] == candidate_ids[1]
    assert len(embedded_ids) == 3


def test_embedding_failures_degrade_run_to_partial_never_fail_whole_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(niche_brief_repo, "get_brief", lambda tenant_id, brief_id: _ready_brief())
    candidate_id = uuid4()

    def _fake_run_discovery(tenant_id, *, run_id, niche_brief, tavily, youtube, cache, candidate_cap=30, product_extraction_client=None, now=None):
        from product_intelligence.discovery.discovery_run import CandidateRawSignals

        return DiscoveryRunOutcome(
            run_id=run_id, status="COMPLETE", candidate_ids=(candidate_id,), partial_reason=None,
            tavily_degraded=False, youtube_degraded=False,
            raw_signals_by_candidate={
                candidate_id: CandidateRawSignals((), (), None, None)
            },
        )

    monkeypatch.setattr(pi_discover, "run_discovery", _fake_run_discovery)
    monkeypatch.setattr(
        product_candidate_repo,
        "list_candidates_for_run",
        lambda tenant_id, run_id: [
            {"id": str(candidate_id), "proxy_state": "COMPUTED", "proxy_score": "50.00",
             "title_length": 5, "title_structure": {}, "keyword_themes": {}}
        ],
    )

    def _raise_embedding_unavailable(tenant_id, candidate_id, **kw):
        raise EmbeddingUnavailable("dimension mismatch")

    monkeypatch.setattr(pi_discover, "embed_candidate", _raise_embedding_unavailable)

    result = pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="PASS", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=_FakeEmbeddingClient(), now=_NOW,
    )

    assert result.status == "PARTIAL"
    assert "degraded embedding generation" in result.partial_reason


def test_feasibility_is_computed_and_written_back_for_every_shortlisted_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quality-pass regression (2026-10-01): `estimate_product_feasibility` previously had no
    caller anywhere in PI. This proves `submit_pi_discover` actually calls
    `compute_candidate_feasibility` for each shortlisted candidate and writes the result back
    via `product_candidate_repo.update_feasibility` — not just that the module exists."""
    monkeypatch.setattr(niche_brief_repo, "get_brief", lambda tenant_id, brief_id: _ready_brief())
    candidate_id = uuid4()

    def _fake_run_discovery(tenant_id, *, run_id, niche_brief, tavily, youtube, cache, candidate_cap=30, product_extraction_client=None, now=None):
        from product_intelligence.discovery.discovery_run import CandidateRawSignals

        return DiscoveryRunOutcome(
            run_id=run_id, status="COMPLETE", candidate_ids=(candidate_id,), partial_reason=None,
            tavily_degraded=False, youtube_degraded=False,
            raw_signals_by_candidate={candidate_id: CandidateRawSignals((), (), None, None)},
        )

    monkeypatch.setattr(pi_discover, "run_discovery", _fake_run_discovery)
    monkeypatch.setattr(
        product_candidate_repo,
        "list_candidates_for_run",
        lambda tenant_id, run_id: [
            {"id": str(candidate_id), "proxy_state": "COMPUTED", "proxy_score": "50.00",
             "title_length": 5, "title_structure": {}, "keyword_themes": {}}
        ],
    )
    monkeypatch.setattr(pi_discover, "embed_candidate", lambda tenant_id, candidate_id, **kw: None)

    feasibility_calls: list[dict] = []
    monkeypatch.setattr(
        pi_discover,
        "compute_candidate_feasibility",
        lambda tenant_id, *, niche_brief, candidate, now=None: (
            feasibility_calls.append({"tenant_id": tenant_id, "candidate": candidate})
            or FeasibilityOutcome(
                status="COMPUTED", estimate_ref=uuid4(), low_paise=50_000, high_paise=70_000,
                cogs_basis="UNKNOWN", assumptions=["no stated_cogs_paise was provided"], unavailable_reason=None,
            )
        ),
    )
    update_calls: list[dict] = []
    monkeypatch.setattr(
        product_candidate_repo,
        "update_feasibility",
        lambda tenant_id, candidate_id, **kw: update_calls.append({"candidate_id": candidate_id, **kw}),
    )

    result = pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="PASS", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=_FakeEmbeddingClient(), now=_NOW,
    )

    assert result.status == "COMPLETE"
    assert len(feasibility_calls) == 1
    assert feasibility_calls[0]["candidate"]["id"] == str(candidate_id)
    assert len(update_calls) == 1
    assert update_calls[0]["candidate_id"] == candidate_id
    assert update_calls[0]["feasibility_status"] == "COMPUTED"
    assert update_calls[0]["feasibility_low_paise"] == 50_000
    assert update_calls[0]["feasibility_cogs_basis"] == "UNKNOWN"
