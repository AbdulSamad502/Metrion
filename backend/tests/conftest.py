"""Suite-wide test environment.

R7 (approval prerequisites): a model endpoint is trusted only when the operator lists its exact host:port in
`LLM_OPERATOR_CONTROLLED_HOSTS`. The hosts below are the fake / unreachable endpoints the existing tests configure (no test calls a real model;
fakes are injected), so they are attested for the suite. `tests/unit/test_llm_endpoint_trust.py` removes the attestation to prove the guard."""

from __future__ import annotations

import pytest

TEST_LLM_HOSTS = "localhost:11434,127.0.0.1:11434,127.0.0.1:9,ollama.test:11434"


@pytest.fixture(autouse=True)
def _attest_the_fake_llm_endpoints_used_by_tests(monkeypatch):
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", TEST_LLM_HOSTS)
    yield
