"""R7: an LLM endpoint is INTERNAL only when the operator attests its exact host:port. Loopback alone is NOT evidence of control (F5)."""

from __future__ import annotations

import pytest

from backend import config


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("LLM_OPERATOR_CONTROLLED_HOSTS", raising=False)
    for fn in (config.ollama_host, config.ceo_ollama_host, config.cmo_ollama_host, config.cmo_vision_ollama_host):
        fn.cache_clear() if hasattr(fn, "cache_clear") else None
    yield
    for fn in (config.ollama_host, config.ceo_ollama_host, config.cmo_ollama_host, config.cmo_vision_ollama_host):
        fn.cache_clear() if hasattr(fn, "cache_clear") else None


def test_loopback_without_attestation_is_external():
    for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://[::1]:11434", "http://127.0.0.2:11434"):
        assert config.llm_endpoint_trust(url) == "EXTERNAL", url


def test_an_attested_exact_host_and_port_is_internal(monkeypatch):
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "localhost:11434, llm.internal:8080")
    assert config.llm_endpoint_trust("http://localhost:11434") == "INTERNAL"
    assert config.llm_endpoint_trust("http://LOCALHOST:11434/") == "INTERNAL"  # case and a trailing slash do not matter
    assert config.llm_endpoint_trust("https://llm.internal:8080") == "INTERNAL"
    assert config.llm_endpoint_trust("http://localhost:11435") == "EXTERNAL"  # another port is another service
    assert config.llm_endpoint_trust("http://llm.internal:80") == "EXTERNAL"


def test_look_alike_private_and_unparsable_endpoints_are_external(monkeypatch):
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "localhost:11434")
    for url in ("http://localhost.evil.com:11434", "http://evil.com/localhost:11434", "http://10.0.0.5:11434", "http://192.168.1.10:11434", "", "not a url", "ftp://localhost:11434",
                "http://localhost:notaport", "http://api.openai.com"):
        assert config.llm_endpoint_trust(url) == "EXTERNAL", url


def test_an_entry_without_a_port_never_matches(monkeypatch):
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "localhost")
    assert config.llm_endpoint_trust("http://localhost:11434") == "EXTERNAL"
    assert config.llm_endpoint_trust("http://localhost") == "EXTERNAL"  # entry 'localhost' != 'localhost:80'


def test_default_ports_are_filled_in(monkeypatch):
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "llm.internal:443")
    assert config.llm_endpoint_trust("https://llm.internal") == "INTERNAL"


def test_verified_endpoint_returns_the_url_or_fails_closed(monkeypatch):
    with pytest.raises(config.LlmEndpointNotVerified, match="EXTERNAL until the operator attests"):
        config.verified_llm_endpoint("http://localhost:11434", setting="OLLAMA_HOST")
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "localhost:11434")
    assert config.verified_llm_endpoint("http://localhost:11434", setting="OLLAMA_HOST") == "http://localhost:11434"


def test_every_configured_host_getter_refuses_an_unattested_endpoint(monkeypatch):
    monkeypatch.setenv("CMO_OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("CMO_VISION_OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setenv("CEO_OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    for getter in (config.ollama_host, config.ceo_ollama_host, config.cmo_ollama_host, config.cmo_vision_ollama_host):
        with pytest.raises(config.MissingConfig):  # LlmEndpointNotVerified IS a MissingConfig: existing handlers answer 503 "not configured"
            getter()
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "localhost:11434")
    for getter in (config.ollama_host, config.ceo_ollama_host, config.cmo_ollama_host, config.cmo_vision_ollama_host):
        assert getter() == "http://localhost:11434"
