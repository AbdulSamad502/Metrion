"""HTTP-layer coverage for Checkpoint 6: `GET /api/v1/ci/market-overview/{product_id}`
(deterministic-engine.md §5.15.1 wired in for real) and
`GET /api/v1/ci/competitor-urls/{id}/comparison` (competitor-intelligence-agent.md §6.19).
Mirrors test_ci_price_scenario_api.py's fixtures exactly.
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


def _set_seller_product(client: TestClient, headers: dict[str, str], product_id: str) -> None:
    body = {
        "category": "Computer Accessories",
        "attributes": [{"key": "brand", "value": "Acme"}],
        "keywords": ["wireless", "ergonomic"],
        "price_paise": 90_000,
        "fulfillment_type": "SELLER_FULFILLED",
    }
    resp = client.put(f"/api/v1/ci/seller-products/{product_id}", json=body, headers=headers)
    assert resp.status_code == 200, resp.text


def _add_tracked_competitor_with_price(client: TestClient, headers: dict[str, str], *, url: str, price_paise: int) -> str:
    url_id = client.post("/api/v1/ci/competitor-urls", json={"url": url}, headers=headers).json()["id"]
    resp = client.post(
        "/api/v1/ceo-hub/research-now",
        json={"competitor_url_id": url_id, "image_refs": [], "manual_fields": {"listed_price_paise": price_paise, "availability": "IN_STOCK"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return url_id


# --- market overview ------------------------------------------------------------------


def test_market_overview_without_seller_product_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    resp = client.get("/api/v1/ci/market-overview/SKU-NOPE", headers=headers)
    assert resp.status_code == 404


def test_market_overview_below_minimum_competitors_is_unavailable(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-MO-1")
    _add_tracked_competitor_with_price(client, headers, url="https://amazon.in/dp/mo-1a", price_paise=90_000)

    resp = client.get("/api/v1/ci/market-overview/SKU-MO-1", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trackedCompetitorCount"] == 0  # no linked_sku set — see known gap noted in discovery_run.py
    assert len(body["rows"]) == 1
    assert body["rows"][0]["isAvailable"] is False
    assert "INSUFFICIENT_COMPETITOR_PRICES" in body["rows"][0]["unavailableReason"]


def test_market_overview_cross_tenant_seller_product_is_404(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    _set_seller_product(client, headers_a, "SKU-MO-2")

    resp = client.get("/api/v1/ci/market-overview/SKU-MO-2", headers=headers_b)
    assert resp.status_code == 404


def test_unauthenticated_market_overview_is_401(client: TestClient) -> None:
    resp = client.get("/api/v1/ci/market-overview/SKU-X")
    assert resp.status_code == 401


# --- comparison ------------------------------------------------------------------------


def test_comparison_without_evidence_is_unavailable(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-CMP-1")
    url_id = client.post("/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/cmp-api-1"}, headers=headers).json()["id"]

    resp = client.get(f"/api/v1/ci/competitor-urls/{url_id}/comparison", params={"product_id": "SKU-CMP-1"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is False
    assert "AWAITING_EVIDENCE" in body["reason"]


def test_comparison_with_evidence_returns_four_buckets(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-CMP-2")
    url_id = _add_tracked_competitor_with_price(client, headers, url="https://amazon.in/dp/cmp-api-2", price_paise=90_000)

    resp = client.get(f"/api/v1/ci/competitor-urls/{url_id}/comparison", params={"product_id": "SKU-CMP-2"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert set(body.keys()) >= {"listingGaps", "productStrengths", "productWeaknesses", "differentiationOpportunities"}
    assert all(entry["state"] == "UNKNOWN" for entry in body["productWeaknesses"])


def test_comparison_cross_tenant_competitor_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    _set_seller_product(client, headers_b, "SKU-CMP-3")
    url_id = _add_tracked_competitor_with_price(client, headers_b, url="https://amazon.in/dp/cmp-api-3", price_paise=90_000)

    resp = client.get(f"/api/v1/ci/competitor-urls/{url_id}/comparison", params={"product_id": "SKU-CMP-3"}, headers=headers_a)
    assert resp.status_code == 404
