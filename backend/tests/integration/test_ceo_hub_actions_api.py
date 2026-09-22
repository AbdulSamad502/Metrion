"""HTTP-layer coverage for Checkpoint 7's two new CEO Hub fixed actions:
`POST /api/v1/ceo-hub/discover-competitors` (`ci.discover_competitors`) and
`POST /api/v1/ceo-hub/request-price-scenario` (`ci.request_price_scenario`).

Both dispatch through `backend.agents.ceo_hub` to the same composition functions
(`backend.services.ci_actions.run_discovery`/`run_price_scenario`) the pre-existing
direct-execution routes in `api/v1/ci.py` use (C20: both entry paths enforce the same
checks) — these tests assert the CEO Hub's own added value: a parent `agent_run` row (C7),
not a re-test of §5.15/§6.10-§6.15 themselves (already covered by
test_ci_price_scenario_api.py / test_ci_discovery_api.py). Mirrors those files' fixtures
exactly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.auth import context as auth_context_module
from backend.main import app
from backend.repositories import agent_run_repo, app_user_repo, membership_repo

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


# --- ci.discover_competitors ------------------------------------------------------------


def test_discover_competitors_without_seller_product_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    resp = client.post("/api/v1/ceo-hub/discover-competitors", json={"product_id": "SKU-NOPE"}, headers=headers)
    assert resp.status_code == 404


def test_discover_competitors_creates_a_ceo_agent_run_and_a_discovery_run(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-CEO-DISC-1")

    resp = client.post("/api/v1/ceo-hub/discover-competitors", json={"product_id": "SKU-CEO-DISC-1"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["discoveryRunId"]
    assert body["status"] in ("COMPLETE", "PARTIAL", "WAITING_FOR_REVIEW", "FAILED")

    run = agent_run_repo.get_run(tenant_a, uuid.UUID(body["ceoAgentRunId"]))
    assert run is not None
    assert run["agent_id"] == "CEO"
    assert run["trigger_ref"] == "ceo_hub.ci.discover_competitors"
    assert run["parent_run_id"] is None


def test_discover_competitors_unauthenticated_is_401(client: TestClient) -> None:
    resp = client.post("/api/v1/ceo-hub/discover-competitors", json={"product_id": "SKU-X"})
    assert resp.status_code == 401


def test_discover_competitors_cross_tenant_seller_product_is_404(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    _set_seller_product(client, headers_a, "SKU-CEO-DISC-2")

    resp = client.post("/api/v1/ceo-hub/discover-competitors", json={"product_id": "SKU-CEO-DISC-2"}, headers=headers_b)
    assert resp.status_code == 404


# --- ci.request_price_scenario -----------------------------------------------------------


def test_request_price_scenario_unknown_competitor_url_is_404(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    resp = client.post(
        "/api/v1/ceo-hub/request-price-scenario",
        json={"competitor_url_id": str(uuid.uuid4()), "seller_price_paise": 100_000},
        headers=headers,
    )
    assert resp.status_code == 404


def test_request_price_scenario_returns_real_engine_result_and_ceo_agent_run(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _add_tracked_competitor_with_price(client, headers, url="https://amazon.in/dp/ceo-price-1", price_paise=90_000)

    resp = client.post(
        "/api/v1/ceo-hub/request-price-scenario",
        json={
            "competitor_url_id": url_id,
            "seller_price_paise": 100_000,
            "stance": "MATCH_LOWEST",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["pricePositioning"]) >= 1
    assert body["pricePositioning"][0]["confidence"] in ("DERIVED", "MANUAL")
    assert body["pricePositioning"][0]["engineResultRef"]
    assert body["repricingScenario"] is not None
    assert body["repricingScenario"]["engineResultRef"]

    run = agent_run_repo.get_run(tenant_a, uuid.UUID(body["ceoAgentRunId"]))
    assert run is not None
    assert run["agent_id"] == "CEO"
    assert run["trigger_ref"] == "ceo_hub.ci.request_price_scenario"
    assert run["status"] == "COMPLETE"


def test_request_price_scenario_matches_direct_execution_route_output_shape(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    """C20: both entry paths share `run_price_scenario` — same competitor snapshot in, same
    engine call, same shape out. Asserts the two routes agree rather than re-testing the
    engine wiring itself (already covered by test_ci_price_scenario_api.py)."""
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _add_tracked_competitor_with_price(client, headers, url="https://amazon.in/dp/ceo-price-2", price_paise=90_000)

    direct_resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000},
        headers=headers,
    )
    ceo_resp = client.post(
        "/api/v1/ceo-hub/request-price-scenario",
        json={"competitor_url_id": url_id, "seller_price_paise": 100_000},
        headers=headers,
    )
    assert direct_resp.status_code == 200 and ceo_resp.status_code == 200
    direct_body, ceo_body = direct_resp.json(), ceo_resp.json()
    assert direct_body["pricePositioning"][0]["metricCode"] == ceo_body["pricePositioning"][0]["metricCode"]
    assert direct_body["pricePositioning"][0]["valuePaise"] == ceo_body["pricePositioning"][0]["valuePaise"]


def test_request_price_scenario_unauthenticated_is_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/ceo-hub/request-price-scenario",
        json={"competitor_url_id": str(uuid.uuid4()), "seller_price_paise": 100_000},
    )
    assert resp.status_code == 401
