"""HTTP-layer coverage for Checkpoint 7's `GET /api/v1/ci/alerts` (Layer 1 alerts,
competitor-intelligence-agent.md §6.17, C26). Mirrors test_ci_landscape_api.py's fixtures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.auth import context as auth_context_module
from backend.main import app
from backend.repositories import app_user_repo, membership_repo

pytestmark = pytest.mark.usefixtures("_clean_backend_tables")


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


@pytest.fixture
def fake_clerk(monkeypatch):
    client = _FakeClerkClient()
    monkeypatch.setattr(auth_context_module, "get_clerk_client", lambda: client)
    return client


@pytest.fixture
def client():
    return TestClient(app)


def _register_owner(fake_clerk: _FakeClerkClient, tenant_id: uuid.UUID) -> dict[str, str]:
    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", email_verified=True,
        auth_provider="GOOGLE", display_name="Test Owner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_id, user_row["id"])

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


def _create_competitor(client: TestClient, headers: dict[str, str], *, url: str) -> str:
    resp = client.post("/api/v1/ci/competitor-urls", json={"url": url}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _research(client: TestClient, headers: dict[str, str], *, url_id: str, price_paise: int) -> None:
    resp = client.post(
        "/api/v1/ceo-hub/research-now",
        json={"competitor_url_id": url_id, "image_refs": [], "manual_fields": {"listed_price_paise": price_paise, "availability": "IN_STOCK"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def test_alerts_empty_with_no_activity(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    resp = client.get("/api/v1/ci/alerts", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["alerts"] == []


def test_alerts_after_a_threshold_breaching_price_drop(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_competitor(client, headers, url="https://amazon.in/dp/alert-api-1")
    _research(client, headers, url_id=url_id, price_paise=100_000)
    _research(client, headers, url_id=url_id, price_paise=80_000)

    resp = client.get("/api/v1/ci/alerts", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "alerts" in body and "since" in body and "until" in body
    assert len(body["alerts"]) == 1
    alert = body["alerts"][0]
    # C26/AC29: the alert's own observational content states no margin/contribution/
    # break-even figure or implication. `handoff.suggestedAction.suggestedQuestion` is
    # allowed (and expected) to name "contribution margin" — that's the whole point of
    # suggesting CFO as the next agent (§6.17, T58), not CI stating one itself.
    for forbidden in ("margin", "contribution", "break-even"):
        assert forbidden not in alert["message"].lower()
        assert forbidden not in alert["handoff"]["implication"].lower()
    assert alert["handoff"]["suggestedAction"]["targetAgent"] == "CFO"


def test_alerts_unauthenticated_is_401(client: TestClient) -> None:
    resp = client.get("/api/v1/ci/alerts")
    assert resp.status_code == 401


def test_alerts_tenant_isolation(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    url_id = _create_competitor(client, headers_a, url="https://amazon.in/dp/alert-api-2")
    _research(client, headers_a, url_id=url_id, price_paise=100_000)
    _research(client, headers_a, url_id=url_id, price_paise=70_000)

    resp = client.get("/api/v1/ci/alerts", headers=headers_b)
    assert resp.status_code == 200
    assert resp.json()["alerts"] == []
