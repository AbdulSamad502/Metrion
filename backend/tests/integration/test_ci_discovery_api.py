"""HTTP-layer coverage for Checkpoint 5's discovery-run endpoints:
`POST /api/v1/ci/discovery-runs`, `GET /api/v1/ci/discovery-runs/{id}`,
`POST /api/v1/ci/discovery-runs/{id}/candidates/{candidate_id}/decision`,
`POST /api/v1/ci/discovery-runs/{id}/candidates/{candidate_id}/promote`
(competitor-intelligence-agent.md §6.12.2, §6.13, §6.14, §6.15). Mirrors
`test_ci_price_scenario_api.py`'s fixtures exactly.
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


def _set_seller_product(client: TestClient, headers: dict[str, str], product_id: str, **fields) -> None:
    body = {
        "category": "Computer Accessories",
        "attributes": [{"key": "brand", "value": "Acme"}],
        "keywords": ["wireless", "ergonomic", "silent click"],
        "price_paise": 89_900,
        "fulfillment_type": "SELLER_FULFILLED",
    }
    body.update(fields)
    resp = client.put(f"/api/v1/ci/seller-products/{product_id}", json=body, headers=headers)
    assert resp.status_code == 200, resp.text


# --- starting a run ----------------------------------------------------------------------


def test_start_discovery_run_without_seller_product_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    resp = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-NOPE"}, headers=headers)
    assert resp.status_code == 404


def test_start_discovery_run_completes_and_returns_recommended_candidates(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-API-1")

    resp = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-1"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # MockSearchProvider (default fixtures, no configured results) returns nothing for any
    # query — this proves the endpoint completes honestly with zero fabricated candidates,
    # exactly like an evidence-upload run with nothing submitted never fabricates a snapshot.
    assert body["status"] == "COMPLETE"
    assert body["rawCandidateCount"] == 0
    assert body["recommendedCandidateIds"] == []


def test_get_discovery_run_returns_tiered_candidates(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-API-2")

    run_id = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-2"}, headers=headers).json()["discoveryRunId"]
    resp = client.get(f"/api/v1/ci/discovery-runs/{run_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["discoveryRunId"] == run_id
    assert set(body.keys()) >= {"recommended", "otherAnalyzed", "unanalyzed", "status"}


def test_get_discovery_run_cross_tenant_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    _set_seller_product(client, headers_a, "SKU-API-3")
    run_id = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-3"}, headers=headers_a).json()["discoveryRunId"]

    resp = client.get(f"/api/v1/ci/discovery-runs/{run_id}", headers=headers_b)
    assert resp.status_code == 404


def test_unauthenticated_start_discovery_run_is_401(client: TestClient, fake_clerk: _FakeClerkClient) -> None:
    resp = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-X"})
    assert resp.status_code == 401


# --- candidate decisions ------------------------------------------------------------------
# These exercise accept/reject directly against a manually-inserted RAW candidate (no live
# search backend to guarantee a specific identity-match outcome deterministically over HTTP)
# — the discovery_run.py unit/integration tests already prove the automatic
# identity-resolution -> gating -> tiering pipeline end to end; this file's job is proving
# the HTTP layer (auth, tenant scoping, allowlist enforcement, error mapping) around it.


def _insert_raw_candidate(tenant_id: uuid.UUID, *, discovery_run_id: uuid.UUID, url: str, marketplace: str | None) -> uuid.UUID:
    from competitor_intelligence.repositories import ci_candidate_repo

    return ci_candidate_repo.create_candidate(
        tenant_id, discovery_run_id=discovery_run_id, candidate_url=url, marketplace=marketplace, tier="RECOMMENDED"
    )


def test_accept_candidate_promotes_into_tracked_competitor_url(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-API-4")
    run_id = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-4"}, headers=headers).json()["discoveryRunId"]

    candidate_id = _insert_raw_candidate(
        tenant_a, discovery_run_id=uuid.UUID(run_id), url="https://amazon.in/dp/api-accept", marketplace="AMAZON"
    )

    resp = client.post(
        f"/api/v1/ci/discovery-runs/{run_id}/candidates/{candidate_id}/decision",
        json={"decision": "ACCEPT"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["competitorUrlId"] is not None

    tracked = client.get("/api/v1/ci/competitor-urls", headers=headers).json()
    assert any(u["id"] == body["competitorUrlId"] for u in tracked)


def test_accept_candidate_not_on_allowlist_is_400(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-API-5")
    run_id = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-5"}, headers=headers).json()["discoveryRunId"]

    candidate_id = _insert_raw_candidate(
        tenant_a, discovery_run_id=uuid.UUID(run_id), url="https://notallowed.example.com/x", marketplace=None
    )

    resp = client.post(
        f"/api/v1/ci/discovery-runs/{run_id}/candidates/{candidate_id}/decision",
        json={"decision": "ACCEPT"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_reject_candidate_does_not_create_a_competitor_url(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-API-6")
    run_id = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-6"}, headers=headers).json()["discoveryRunId"]

    candidate_id = _insert_raw_candidate(
        tenant_a, discovery_run_id=uuid.UUID(run_id), url="https://amazon.in/dp/api-reject", marketplace="AMAZON"
    )

    resp = client.post(
        f"/api/v1/ci/discovery-runs/{run_id}/candidates/{candidate_id}/decision",
        json={"decision": "REJECT"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["competitorUrlId"] is None

    tracked = client.get("/api/v1/ci/competitor-urls", headers=headers).json()
    assert not any(u.get("url") == "https://amazon.in/dp/api-reject" for u in tracked)


def test_decision_on_candidate_from_another_run_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _set_seller_product(client, headers, "SKU-API-7")
    run_id = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-7"}, headers=headers).json()["discoveryRunId"]

    other_run_id = uuid.uuid4()
    candidate_id = _insert_raw_candidate(
        tenant_a, discovery_run_id=other_run_id, url="https://amazon.in/dp/api-mismatch", marketplace="AMAZON"
    )

    resp = client.post(
        f"/api/v1/ci/discovery-runs/{run_id}/candidates/{candidate_id}/decision",
        json={"decision": "ACCEPT"},
        headers=headers,
    )
    assert resp.status_code == 404


def test_decision_cross_tenant_candidate_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    _set_seller_product(client, headers_b, "SKU-API-8")
    run_id_b = client.post("/api/v1/ci/discovery-runs", json={"product_id": "SKU-API-8"}, headers=headers_b).json()["discoveryRunId"]
    candidate_id = _insert_raw_candidate(
        tenant_b, discovery_run_id=uuid.UUID(run_id_b), url="https://amazon.in/dp/cross-tenant", marketplace="AMAZON"
    )

    resp = client.post(
        f"/api/v1/ci/discovery-runs/{run_id_b}/candidates/{candidate_id}/decision",
        json={"decision": "ACCEPT"},
        headers=headers_a,
    )
    assert resp.status_code == 404
