"""`POST /api/v1/cfo/anomaly-check` — the Brain-3 narration wiring E3's own close-out named as
a real, un-built gap ("no Brain-3 narration step"). Real Postgres, mirrors
`test_cfo_pnl.py`/`test_cfo_gst_lookup.py`'s own `app_client`/`fake_clerk`/`_register_owner`
fixture conventions exactly.

Covers:
1. Default behaviour (`include_narration` omitted / `False`) is BYTE-IDENTICAL to the route's
   shape before this checkpoint — no `narration` key present at all, and the LLM provider is
   never constructed/called (monkeypatched to raise if touched).
2. `include_narration: true` calls a FAKE `OllamaLlmProvider` (never real Ollama — this file
   monkeypatches `backend.api.v1.cfo.OllamaLlmProvider` itself, the first CFO integration test
   to fake this class out at the route level, mirroring `test_cfo_gst_lookup.py`'s own
   fetcher/LLM-injection pattern one level up) and returns real narration text under
   `narration`.

No test in this file ever constructs a real `cfo.reasoning.ollama_provider.OllamaLlmProvider`
or reaches a network call — grepped directly before finishing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

_AS_OF = date(2026, 9, 26)
_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 9, 30)


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


@pytest.fixture
def fake_clerk(monkeypatch):
    from backend.auth import context as auth_context_module

    @dataclass
    class _FakeAuthState:
        is_signed_in: bool
        payload: dict[str, Any] | None

    @dataclass
    class _FakeClerkClient:
        tokens: dict[str, tuple[str, str | None]] = field(default_factory=dict)

        async def authenticate_request_async(self, request: Any, options: Any) -> _FakeAuthState:
            header = request.headers.get("authorization", "")
            token = header.removeprefix("Bearer ").strip()
            if token in self.tokens:
                clerk_user_id, clerk_org_id = self.tokens[token]
                return _FakeAuthState(is_signed_in=True, payload={"sub": clerk_user_id, "org_id": clerk_org_id})
            return _FakeAuthState(is_signed_in=False, payload=None)

    client = _FakeClerkClient()
    monkeypatch.setattr(auth_context_module, "get_clerk_client", lambda: client)
    return client


def _register_owner(fake_clerk, tenant_id: uuid.UUID) -> dict[str, str]:
    from backend.repositories import app_user_repo, membership_repo

    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=True,
        auth_provider="GOOGLE",
        display_name="Test Owner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_id, user_row["id"])

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


def _anomaly_check_body(*, include_narration: bool | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "target_ref": "SKU-ANOMALY-1",
        "period_start": _PERIOD_START.isoformat(),
        "period_end": _PERIOD_END.isoformat(),
        "as_of_date": _AS_OF.isoformat(),
    }
    if include_narration is not None:
        body["include_narration"] = include_narration
    return body


class _RaisingOllamaProvider:
    """Stands in for `cfo.reasoning.ollama_provider.OllamaLlmProvider` — raises if ever
    constructed, proving the default (`include_narration` False/omitted) path never
    instantiates a provider or reaches an LLM call at all."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("OllamaLlmProvider must not be constructed when include_narration is False")


@dataclass
class _FakeCompletingProvider:
    response: str = "Your Z-score check for MARGIN_PCT did not fire this period."
    calls: list[str] = field(default_factory=list)

    def complete(self, *, model: str, prompt: str) -> str:
        self.calls.append(prompt)
        return self.response


class _FakeOllamaProviderFactory:
    """Stands in for the `OllamaLlmProvider` class itself — `post_anomaly_check` calls
    `OllamaLlmProvider(host=ollama_host())` positionally-by-keyword; this factory accepts the
    same call shape and returns a shared fake instance whose `.complete()` never touches
    Ollama/the network."""

    def __init__(self, instance: _FakeCompletingProvider) -> None:
        self._instance = instance

    def __call__(self, *args: Any, **kwargs: Any) -> _FakeCompletingProvider:
        return self._instance


def test_default_response_shape_is_unchanged_and_never_constructs_a_provider(
    app_client, fake_clerk, two_tenants, monkeypatch
):
    from backend.api.v1 import cfo as cfo_routes

    monkeypatch.setattr(cfo_routes, "OllamaLlmProvider", _RaisingOllamaProvider)

    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post("/api/v1/cfo/anomaly-check", json=_anomaly_check_body(), headers=headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert set(body.keys()) == {"targetRef", "metric", "seriesLength", "methods"}
    assert "narration" not in body


def test_include_narration_false_explicitly_also_never_constructs_a_provider(
    app_client, fake_clerk, two_tenants, monkeypatch
):
    from backend.api.v1 import cfo as cfo_routes

    monkeypatch.setattr(cfo_routes, "OllamaLlmProvider", _RaisingOllamaProvider)

    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post(
        "/api/v1/cfo/anomaly-check", json=_anomaly_check_body(include_narration=False), headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert "narration" not in resp.json()


def test_include_narration_true_calls_fake_provider_and_returns_narration_text(
    app_client, fake_clerk, two_tenants, monkeypatch
):
    from backend.api.v1 import cfo as cfo_routes

    fake_instance = _FakeCompletingProvider()
    monkeypatch.setattr(cfo_routes, "OllamaLlmProvider", _FakeOllamaProviderFactory(fake_instance))

    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post(
        "/api/v1/cfo/anomaly-check", json=_anomaly_check_body(include_narration=True), headers=headers
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["narration"] == fake_instance.response
    assert len(fake_instance.calls) == 1  # the fake provider really was called, once
    # the composed prompt really names the structured outcome's own metric/target_ref
    assert body["metric"] in fake_instance.calls[0]
    assert body["targetRef"] in fake_instance.calls[0]
