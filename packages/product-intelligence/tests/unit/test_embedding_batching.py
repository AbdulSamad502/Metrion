"""Batched embedding. Measured (nomic-embed-text, CPU host): each Ollama embedding request carries
~2.5 s of fixed overhead, so a 30-candidate run took 74.6 s sequentially and 17.7 s across the
pipeline's 5 worker threads, vs 3.9 s as ONE batched `/api/embed` request. The batch vectors are
the same direction as the legacy endpoint's (cosine 1.000000), only L2-normalised, and the sole
consumer is pgvector's magnitude-invariant cosine `<=>`.

The per-candidate path stays as the fallback (and for clients without `embed_many`), so the
degrade-not-fail contract is unchanged."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from product_intelligence.direct_path import pi_discover
from product_intelligence.discovery.discovery_run import CandidateRawSignals, DiscoveryRunOutcome
from product_intelligence.embedding import embed as embed_module
from product_intelligence.embedding.embed import MODEL_DIM, EmbeddingUnavailable, OllamaEmbeddingClient
from product_intelligence.repositories import niche_brief_repo, product_candidate_repo

# reuse the scaffolding the existing discovery tests use
from tests.unit.test_pi_discover import (  # type: ignore[import-not-found]
    _BRIEF_ID, _NOW, _REQUESTED_BY, _TENANT_ID, _FakeExtractor, _NoopTavily, _NoopYoutube, _patch_repos, _ready_brief,
)
from product_intelligence.sources.cache import InProcessQueryCache

__all__ = ["_patch_repos"]  # autouse fixture imported for its side effect


class _BatchClient:
    def __init__(self, *, fail_batch: bool = False) -> None:
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []
        self._fail_batch = fail_batch

    def embed(self, text: str) -> list[float]:
        self.single_calls.append(text)
        return [0.1] * MODEL_DIM

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        if self._fail_batch:
            raise EmbeddingUnavailable("batch endpoint down")
        return [[0.2] * MODEL_DIM for _ in texts]


def _wire(monkeypatch: pytest.MonkeyPatch, n: int) -> list:
    monkeypatch.setattr(niche_brief_repo, "get_brief", lambda tenant_id, brief_id: _ready_brief())
    ids = [uuid4() for _ in range(n)]

    def fake_run_discovery(tenant_id, *, run_id, niche_brief, tavily, youtube, cache, candidate_cap=30, product_extraction_client=None, now=None):
        return DiscoveryRunOutcome(
            run_id=run_id, status="COMPLETE", candidate_ids=tuple(ids), partial_reason=None,
            tavily_degraded=False, youtube_degraded=False,
            raw_signals_by_candidate={i: CandidateRawSignals((), (), None, None) for i in ids},
        )

    monkeypatch.setattr(pi_discover, "run_discovery", fake_run_discovery)
    monkeypatch.setattr(
        product_candidate_repo, "list_candidates_for_run",
        lambda tenant_id, run_id: [
            {"id": str(i), "proxy_state": "COMPUTED", "proxy_score": "50.00", "title_length": 5 + k,
             "title_structure": {}, "keyword_themes": {}}
            for k, i in enumerate(ids)
        ],
    )
    return ids


def _run(client):
    return pi_discover.submit_pi_discover(
        _TENANT_ID, _BRIEF_ID, "SHALLOW",
        requested_by=_REQUESTED_BY, permission_check="PASS", entitlement_check="PASS",
        tavily=_NoopTavily(), youtube=_NoopYoutube(), cache=InProcessQueryCache(),
        text_extractor=_FakeExtractor(), embedding_client=client, now=_NOW,
    )


def test_all_candidates_are_embedded_with_one_batched_request_and_each_stored(monkeypatch) -> None:
    ids = _wire(monkeypatch, 7)
    stored: dict[str, int] = {}
    monkeypatch.setattr(
        pi_discover, "store_candidate_embedding",
        lambda tenant_id, candidate_id, vector, now=None: stored.__setitem__(str(candidate_id), len(vector)),
    )
    monkeypatch.setattr(pi_discover, "embed_candidate", lambda *a, **k: pytest.fail("per-candidate path must not run"))
    client = _BatchClient()

    result = _run(client)

    assert result.status == "COMPLETE"
    assert len(client.batch_calls) == 1 and len(client.batch_calls[0]) == 7  # ONE request, every candidate
    assert client.single_calls == []
    assert set(stored) == {str(i) for i in ids} and set(stored.values()) == {MODEL_DIM}


def test_failed_batch_falls_back_to_per_candidate_calls_and_still_embeds_everyone(monkeypatch) -> None:
    ids = _wire(monkeypatch, 4)
    embedded: list[str] = []
    monkeypatch.setattr(pi_discover, "embed_candidate", lambda tenant_id, candidate_id, **kw: embedded.append(str(candidate_id)))
    client = _BatchClient(fail_batch=True)

    result = _run(client)

    assert result.status == "COMPLETE"  # a down batch endpoint is not a failed run
    assert len(client.batch_calls) == 1
    assert sorted(embedded) == sorted(str(i) for i in ids)


def test_client_without_embed_many_keeps_the_original_per_candidate_behaviour(monkeypatch) -> None:
    ids = _wire(monkeypatch, 3)
    embedded: list[str] = []
    monkeypatch.setattr(pi_discover, "embed_candidate", lambda tenant_id, candidate_id, **kw: embedded.append(str(candidate_id)))

    class _OnlyEmbed:
        def embed(self, text: str) -> list[float]:
            return [0.1] * MODEL_DIM

    assert _run(_OnlyEmbed()).status == "COMPLETE"
    assert sorted(embedded) == sorted(str(i) for i in ids)


def test_one_candidates_store_failure_degrades_to_partial_without_losing_the_others(monkeypatch) -> None:
    ids = _wire(monkeypatch, 4)
    stored: list[str] = []

    def flaky_store(tenant_id, candidate_id, vector, now=None):
        if str(candidate_id) == str(ids[1]):
            raise RuntimeError("db write failed")
        stored.append(str(candidate_id))

    monkeypatch.setattr(pi_discover, "store_candidate_embedding", flaky_store)
    result = _run(_BatchClient())

    assert result.status == "PARTIAL" and "1 candidate(s) had degraded embedding generation" in result.partial_reason
    assert len(stored) == 3


# --- the HTTP contract of embed_many ---------------------------------------------------------


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._body


def _client_with(monkeypatch, body):
    seen = {}

    def fake_post(url, *, json, timeout):
        seen.update(url=url, json=json)
        return _Resp(body)

    monkeypatch.setattr(httpx, "post", fake_post)
    return OllamaEmbeddingClient(host="http://h", model="nomic-embed-text"), seen


def test_embed_many_posts_one_request_with_all_inputs(monkeypatch) -> None:
    client, seen = _client_with(monkeypatch, {"embeddings": [[1, 2], [3, 4]]})
    assert client.embed_many(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]
    assert seen["url"] == "http://h/api/embed"
    assert seen["json"] == {"model": "nomic-embed-text", "input": ["a", "b"]}


@pytest.mark.parametrize(
    "body",
    [{"embeddings": [[1.0]]}, {"embeddings": "nope"}, {"embeddings": [["x"], ["y"]]}, {}, []],  # wrong count/shape/type
)
def test_embed_many_rejects_malformed_or_partial_responses(monkeypatch, body) -> None:
    client, _ = _client_with(monkeypatch, body)
    with pytest.raises(EmbeddingUnavailable):
        client.embed_many(["a", "b"])


def test_embed_many_wraps_http_errors_as_embedding_unavailable(monkeypatch) -> None:
    def boom(url, *, json, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(EmbeddingUnavailable):
        OllamaEmbeddingClient(host="http://h").embed_many(["a"])


def test_store_candidate_embedding_still_rejects_a_wrong_dimension() -> None:
    with pytest.raises(EmbeddingUnavailable):
        embed_module.store_candidate_embedding(uuid4(), uuid4(), [0.1, 0.2])
