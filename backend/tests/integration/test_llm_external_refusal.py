"""R7: with an unattested (EXTERNAL) model endpoint every seller-data-bearing model call site refuses BEFORE anything is sent.

A fake transport proves zero connections are attempted, and the GST lookup (which would otherwise fetch public pages first) never fetches."""

from __future__ import annotations

import socket

import pytest

from backend import config
from backend.services import cmo_runtime, pi_actions

pytestmark = pytest.mark.usefixtures("two_tenants")


@pytest.fixture
def unattested(monkeypatch):
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "attested.example:11434")  # the configured endpoints below are NOT in the list
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("CEO_OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("CMO_OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("CMO_LLM_MODEL", "m")
    monkeypatch.setenv("CMO_LLM_TIMEOUT_SECONDS", "30")
    for fn in (config.ollama_host, config.ceo_ollama_host, config.cmo_ollama_host, config.cmo_vision_ollama_host, config.cmo_llm_timeout_seconds):
        getattr(fn, "cache_clear", lambda: None)()
    connections: list[object] = []

    def refuse(*args, **kwargs):
        connections.append(args)
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket, "create_connection", refuse)
    yield connections
    for fn in (config.ollama_host, config.ceo_ollama_host, config.cmo_ollama_host, config.cmo_vision_ollama_host, config.cmo_llm_timeout_seconds):
        getattr(fn, "cache_clear", lambda: None)()


def test_pi_model_clients_refuse_to_be_built(unattested):
    for build in (pi_actions._text_extractor, pi_actions._product_extraction_client, pi_actions._embedding_client):
        with pytest.raises(config.LlmEndpointNotVerified):
            build()
    assert unattested == []


def test_the_cmo_and_ceo_providers_refuse_to_be_built(unattested):
    with pytest.raises(config.LlmEndpointNotVerified):
        cmo_runtime._ollama_provider()
    from backend.services import ceo_runtime

    with pytest.raises(config.LlmEndpointNotVerified):
        ceo_runtime._ollama("some-model")
    assert unattested == []


def test_the_gst_lookup_refuses_before_it_fetches_any_page(unattested, two_tenants, monkeypatch):
    a, _ = two_tenants
    from backend.services import cfo_actions
    from calc_engine.gst_lookup.fetcher import HttpxGstFetcher

    fetched: list[str] = []
    monkeypatch.setattr(HttpxGstFetcher, "fetch", lambda self, url: fetched.append(url))
    with pytest.raises(config.LlmEndpointNotVerified):
        cfo_actions.run_gst_applicability_lookup(a, cfo_actions.GstLookupRequest(product_title="steel water bottle", requested_by=None))
    assert fetched == [] and unattested == []


def test_attesting_the_endpoint_restores_service(unattested, monkeypatch):
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "localhost:11434")
    for fn in (config.ollama_host, config.ceo_ollama_host, config.cmo_ollama_host):
        getattr(fn, "cache_clear", lambda: None)()
    assert pi_actions._embedding_client() is not None
    assert cmo_runtime._ollama_provider() is not None
