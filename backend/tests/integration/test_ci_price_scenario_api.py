"""HTTP-layer coverage for `POST /api/v1/ci/competitor-urls/{url_id}/price-scenario`
(Checkpoint 1, `deterministic-engine.md` §5.15/§5.15.1) — wires `compute_price_positioning`
and `compute_repricing_scenario` in through a real backend endpoint for the first time.
Mirrors `test_ci_api.py`'s fixtures exactly.
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


def _create_url_with_price(client: TestClient, headers: dict[str, str], *, listed_price_paise: int, url: str) -> str:
    url_id = client.post("/api/v1/ci/competitor-urls", json={"url": url}, headers=headers).json()["id"]
    resp = client.post(
        "/api/v1/ceo-hub/research-now",
        json={
            "competitor_url_id": url_id,
            "image_refs": [],
            "manual_fields": {"listed_price_paise": listed_price_paise, "availability": "IN_STOCK"},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return url_id


# --- Real competitor price -> real result ---------------------------------------------------


def test_price_positioning_with_real_competitor_price(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_url_with_price(client, headers, listed_price_paise=90_000, url="https://amazon.in/dp/scenario-1")

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    positioning = body["pricePositioning"]
    assert len(positioning) == 3  # AVERAGE, MIN, MAX
    for row in positioning:
        assert row["metricCode"] == "PRICE_POSITIONING"
        assert row["isAvailable"] is True
        assert row["valuePaise"] == 10_000  # 100_000 - 90_000, single competitor
        assert row["confidence"] == "MANUAL"  # weakest of MANUAL (seller) / DERIVED (competitor)
        assert row["engineResultRef"]  # a real UUID string, non-empty
    assert body["repricingScenario"] is None


def test_repricing_scenario_included_when_stance_supplied(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_url_with_price(client, headers, listed_price_paise=70_000, url="https://amazon.in/dp/scenario-2")

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000, "stance": "MATCH_LOWEST"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["repricingScenario"] is not None
    assert body["repricingScenario"]["metricCode"] == "REPRICING_SCENARIO"
    assert body["repricingScenario"]["isAvailable"] is True
    assert body["repricingScenario"]["valuePaise"] == 70_000
    assert body["repricingScenario"]["engineResultRef"]


def test_repricing_scenario_beat_lowest_by_pct(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_url_with_price(client, headers, listed_price_paise=100_000, url="https://amazon.in/dp/scenario-pct")

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 120_000, "stance": "BEAT_LOWEST_BY_PCT", "stance_param_pct": "10"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["repricingScenario"]["isAvailable"] is True
    assert body["repricingScenario"]["valuePaise"] == 90_000  # 100_000 - 10%


# --- No usable competitor price -> UNAVAILABLE, never fabricated ---------------------------


def test_no_snapshot_at_all_returns_unavailable(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = client.post(
        "/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/scenario-no-snapshot"}, headers=headers
    ).json()["id"]

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    positioning = body["pricePositioning"]
    assert len(positioning) == 1
    assert positioning[0]["isAvailable"] is False
    assert positioning[0]["valuePaise"] is None
    assert positioning[0]["unavailableReason"] is not None


def test_pending_manual_entry_only_returns_unavailable(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = client.post(
        "/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/scenario-pending"}, headers=headers
    ).json()["id"]

    # No listed_price_paise -> capture_status resolves to PENDING_MANUAL_ENTRY, no usable price.
    resp = client.post(
        "/api/v1/ceo-hub/research-now",
        json={"competitor_url_id": url_id, "image_refs": [], "manual_fields": {}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    scenario_resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000},
        headers=headers,
    )
    assert scenario_resp.status_code == 200, scenario_resp.text
    positioning = scenario_resp.json()["pricePositioning"]
    assert len(positioning) == 1
    assert positioning[0]["isAvailable"] is False


# --- Auth / tenant isolation -----------------------------------------------------------------


def test_wrong_tenant_url_id_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)

    url_id = _create_url_with_price(client, headers_a, listed_price_paise=90_000, url="https://amazon.in/dp/scenario-cross-tenant")

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000},
        headers=headers_b,
    )
    assert resp.status_code == 404


def test_nonexistent_url_id_is_404(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{uuid.uuid4()}/price-scenario",
        json={"seller_price_paise": 100_000},
        headers=headers,
    )
    assert resp.status_code == 404


def test_unauthenticated_request_is_401(client: TestClient) -> None:
    resp = client.post(
        f"/api/v1/ci/competitor-urls/{uuid.uuid4()}/price-scenario",
        json={"seller_price_paise": 100_000},
    )
    assert resp.status_code == 401


# --- Validation -------------------------------------------------------------------------------


def test_missing_seller_price_is_422(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_url_with_price(client, headers, listed_price_paise=90_000, url="https://amazon.in/dp/scenario-missing-price")

    resp = client.post(f"/api/v1/ci/competitor-urls/{url_id}/price-scenario", json={}, headers=headers)
    assert resp.status_code == 422


def test_zero_seller_price_is_422(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_url_with_price(client, headers, listed_price_paise=90_000, url="https://amazon.in/dp/scenario-zero-price")

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 0},
        headers=headers,
    )
    assert resp.status_code == 422


def test_invalid_stance_is_422(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_url_with_price(client, headers, listed_price_paise=90_000, url="https://amazon.in/dp/scenario-bad-stance")

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000, "stance": "NOT_A_REAL_STANCE"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_beat_lowest_by_pct_missing_param_is_unavailable_not_exception(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    """§5.15 rule 3: a stance requiring stance_param with none supplied is UNAVAILABLE, never
    a fabricated result and never an unhandled exception."""
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = _create_url_with_price(client, headers, listed_price_paise=90_000, url="https://amazon.in/dp/scenario-missing-stance-param")

    resp = client.post(
        f"/api/v1/ci/competitor-urls/{url_id}/price-scenario",
        json={"seller_price_paise": 100_000, "stance": "BEAT_LOWEST_BY_PCT"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    scenario = resp.json()["repricingScenario"]
    assert scenario["isAvailable"] is False
    assert scenario["unavailableReason"] is not None
