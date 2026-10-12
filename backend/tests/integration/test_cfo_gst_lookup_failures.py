"""Issue 5 (Metrion_24_Fixes): "Cotton bedsheet / Home textiles lookup returned a generic failure".

The lookup fetches allow-listed public tax pages and has the language model read them. Three different things can happen, and a seller must be able to tell them apart:
the model server is unreachable (a dependency failure: 503 with a plain sentence, nothing stored), no page matched (a normal answer: 200 with `noMatch` and the pages
tried), or it matched (a result, stored). Fakes stand in for the network and the model; nothing real is called."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.gst_lookup.fetcher import FetchError, RawPage
from cfo.reasoning.ollama_provider import OllamaUnavailable
from tests.integration.test_cfo_gst_lookup import (  # noqa: F401  (fixtures and helpers)
    _clean_gst_lookup_table,
    _register_partner_with_permissions,
    app_client,
    fake_clerk,
)

BODY = {"product_title": "Cotton bedsheet", "category": "Home textiles"}
_NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


class _Fetcher:
    def __init__(self, page_ok: bool) -> None:
        self.page_ok = page_ok
        self.urls: list[str] = []

    def fetch(self, url: str):
        self.urls.append(url)
        return RawPage(url=url, status_code=200, body="Home textiles: see the schedule.", fetched_at=_NOW) if self.page_ok else FetchError(reason="timeout")


class _Llm:
    def __init__(self, response: str | None) -> None:
        self.response = response

    def complete(self, *, model: str, prompt: str) -> str:
        if self.response is None:
            raise OllamaUnavailable("Ollama request failed: connection refused")
        return self.response


def _install(monkeypatch, fetcher, llm) -> None:
    from backend.services import cfo_actions

    monkeypatch.setattr(cfo_actions, "HttpxGstFetcher", lambda: fetcher)
    monkeypatch.setattr(cfo_actions, "OllamaLlmProvider", lambda **kw: llm)


def _stored(tenant_id) -> int:
    # FORCE RLS: without the tenant context a count is always 0, which would make every "nothing stored" check vacuous.
    from calc_engine.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_id) as conn:
        return conn.execute(text("SELECT count(*) FROM gst_lookup_result")).scalar_one()


@pytest.fixture
def headers(fake_clerk, two_tenants):
    return _register_partner_with_permissions(fake_clerk, two_tenants[0], permissions={"agent.cfo": True, "service.gst_lookup": True})


def test_model_unreachable_is_a_503_with_a_plain_sentence_and_nothing_is_stored(app_client, headers, monkeypatch, two_tenants):
    _install(monkeypatch, _Fetcher(page_ok=True), _Llm(None))
    resp = app_client.post("/api/v1/cfo/gst-lookup", json=BODY, headers=headers)
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "could not be reached" in detail and "Ollama" not in detail and "Traceback" not in detail
    assert _stored(two_tenants[0]) == 0


def test_no_page_matching_is_a_normal_200_that_lists_what_was_tried(app_client, headers, monkeypatch, two_tenants):
    fetcher = _Fetcher(page_ok=True)
    _install(monkeypatch, fetcher, _Llm("MATCH: NO\n"))
    resp = app_client.post("/api/v1/cfo/gst-lookup", json=BODY, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"] is None and body["noMatch"]["queryText"] == "Cotton bedsheet"
    assert body["noMatch"]["attemptedUrls"] == fetcher.urls and fetcher.urls
    assert _stored(two_tenants[0]) == 0  # a non-result is never cached


def test_every_page_failing_to_load_is_also_a_no_match_not_an_error(app_client, headers, monkeypatch):
    _install(monkeypatch, _Fetcher(page_ok=False), _Llm(None))  # the model is never reached when no page loads
    resp = app_client.post("/api/v1/cfo/gst-lookup", json=BODY, headers=headers)
    assert resp.status_code == 200 and resp.json()["noMatch"]["reason"] is not None


def test_a_matching_page_gives_a_stored_provisional_result_that_is_served_from_cache_next_time(app_client, headers, monkeypatch, two_tenants):
    llm = _Llm("MATCH: YES\nRATE_PCT: 5\nHSN: 6302\nCATEGORY: bed linen\nAMBIGUOUS: NO\nAMBIGUITY_NOTE: NONE\n")  # plumbing only: the rate is whatever the (fake) page said
    _install(monkeypatch, _Fetcher(page_ok=True), llm)
    first = app_client.post("/api/v1/cfo/gst-lookup", json=BODY, headers=headers).json()
    assert first["fromCache"] is False and first["result"]["likelyRatePct"] == "5" and first["result"]["status"] == "PROVISIONAL"
    assert _stored(two_tenants[0]) == 1
    _install(monkeypatch, _Fetcher(page_ok=True), _Llm(None))  # a second ask must not need the model at all
    second = app_client.post("/api/v1/cfo/gst-lookup", json=BODY, headers=headers).json()
    assert second["fromCache"] is True and second["result"]["id"] == first["result"]["id"]
