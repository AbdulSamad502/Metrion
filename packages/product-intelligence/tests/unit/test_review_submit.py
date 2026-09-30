"""review_insight/submit.py — orchestrates extraction+aggregate+persist. The repository call
is monkeypatched so this stays a unit test (no live Postgres) while still asserting the C7/C9
contract: raw comment/article text never reaches `insert_insight`'s arguments."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from product_intelligence.repositories import product_review_insight_repo
from product_intelligence.review_insight.submit import submit_candidate_review_insight
from product_intelligence.review_insight.text_extraction import TextExtractionResult, TextObservation

_NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
_TENANT_ID = uuid4()
_CANDIDATE_ID = uuid4()


class _FakeExtractor:
    def extract(self, texts, *, insight_source_type):
        return TextExtractionResult(
            insight_source_type=insight_source_type,
            observations=tuple(TextObservation(sentiment="POSITIVE", themes=("battery life",)) for _ in texts),
        )


def test_submits_one_row_per_source_type_that_had_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_calls: list[dict] = []

    def _fake_insert(tenant_id, **kwargs):
        captured_calls.append(kwargs)
        return uuid4()

    monkeypatch.setattr(product_review_insight_repo, "insert_insight", _fake_insert)

    results = submit_candidate_review_insight(
        _TENANT_ID,
        candidate_id=_CANDIDATE_ID,
        youtube_comments=["this is amazing, secret raw comment text A"],
        youtube_source_url="https://youtube.com/watch?v=abc",
        web_snippets=["secret raw web snippet text B"],
        web_source_url="https://example.com/article",
        extractor=_FakeExtractor(),
        now=_NOW,
    )

    assert len(results) == 2
    assert len(captured_calls) == 2
    source_types = {c["insight_source_type"] for c in captured_calls}
    assert source_types == {"YOUTUBE_COMMENTARY", "WEB_EDITORIAL"}


def test_raw_comment_and_snippet_text_never_reach_the_repository_call(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_calls: list[dict] = []
    monkeypatch.setattr(
        product_review_insight_repo,
        "insert_insight",
        lambda tenant_id, **kwargs: captured_calls.append(kwargs) or uuid4(),
    )

    raw_comment = "secret raw comment text A that must never round-trip to Postgres"
    raw_snippet = "secret raw web snippet text B that must never round-trip to Postgres"

    submit_candidate_review_insight(
        _TENANT_ID,
        candidate_id=_CANDIDATE_ID,
        youtube_comments=[raw_comment],
        youtube_source_url="https://youtube.com/watch?v=abc",
        web_snippets=[raw_snippet],
        web_source_url="https://example.com/article",
        extractor=_FakeExtractor(),
        now=_NOW,
    )

    rendered = repr(captured_calls)
    assert raw_comment not in rendered
    assert raw_snippet not in rendered


def test_no_row_written_for_a_source_type_with_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_calls: list[dict] = []
    monkeypatch.setattr(
        product_review_insight_repo,
        "insert_insight",
        lambda tenant_id, **kwargs: captured_calls.append(kwargs) or uuid4(),
    )

    results = submit_candidate_review_insight(
        _TENANT_ID,
        candidate_id=_CANDIDATE_ID,
        youtube_comments=["only youtube text here"],
        youtube_source_url="https://youtube.com/watch?v=abc",
        web_snippets=[],
        web_source_url=None,
        extractor=_FakeExtractor(),
        now=_NOW,
    )

    assert len(results) == 1
    assert len(captured_calls) == 1
    assert captured_calls[0]["insight_source_type"] == "YOUTUBE_COMMENTARY"
