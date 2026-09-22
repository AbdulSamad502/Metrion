"""HTTP-layer coverage for the CI and CEO-Hub CI endpoints (`api/v1/ci.py`,
`api/v1/ceo_hub.py`) — exercised through `TestClient(app)` against a real Postgres, with
only the actual Clerk network call stubbed (`get_clerk_client`, via `_FakeClerkClient`
below). Everything else — the six-step `require_auth()` chain, RLS/tenant scoping, the
permission grid — runs for real. This is the coverage flagged as missing at Checkpoint 5:
no prior test exercised these routers over HTTP, only their underlying domain functions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.auth import context as auth_context_module
from backend.auth.permissions import AGENT_CI
from backend.main import app
from backend.repositories import app_user_repo, membership_repo

pytestmark = pytest.mark.usefixtures("_clean_backend_tables")


@dataclass
class _FakeAuthState:
    is_signed_in: bool
    payload: dict[str, Any] | None


@dataclass
class _FakeClerkClient:
    """Maps a bearer token to (clerk_user_id, clerk_org_id) — an unregistered or missing
    token is simply not signed in, exercising the real 401 path exactly like a bad/expired
    real JWT would."""

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


def _register_deny_all_partner(fake_clerk: _FakeClerkClient, tenant_id: uuid.UUID) -> dict[str, str]:
    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", email_verified=True,
        auth_provider="GOOGLE", display_name="Test Partner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.upsert_partner(tenant_id, user_row["id"], role="PARTNER", status="ACTIVE")

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


# --- Auth / tenant-isolation ------------------------------------------------------------


def test_unauthenticated_request_is_401(client: TestClient) -> None:
    resp = client.get("/api/v1/ci/summary")
    assert resp.status_code == 401


def test_unrecognized_token_is_401(client: TestClient, fake_clerk: _FakeClerkClient) -> None:
    resp = client.get("/api/v1/ci/summary", headers={"Authorization": "Bearer garbage-token"})
    assert resp.status_code == 401


def test_verified_user_with_no_membership_is_403(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id, email=f"{clerk_user_id}@example.com", email_verified=True,
        auth_provider="GOOGLE", display_name="No Membership",
    )
    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_a}")

    resp = client.get("/api/v1/ci/summary", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_partner_without_agent_ci_permission_is_403(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_deny_all_partner(fake_clerk, tenant_a)

    resp = client.post("/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/x"}, headers=headers)
    assert resp.status_code == 403
    assert AGENT_CI in resp.json()["detail"]


def test_owner_bypasses_permission_grid(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = client.get("/api/v1/ci/competitor-urls", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


# --- Competitor URL CRUD -----------------------------------------------------------------


def test_create_and_list_competitor_url(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    create_resp = client.post(
        "/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/test123", "label": "Rival"}, headers=headers
    )
    assert create_resp.status_code == 200
    url_id = create_resp.json()["id"]

    list_resp = client.get("/api/v1/ci/competitor-urls", headers=headers)
    assert list_resp.status_code == 200
    urls = list_resp.json()
    assert len(urls) == 1
    assert urls[0]["id"] == url_id
    assert urls[0]["label"] == "Rival"


def test_non_allowlisted_host_is_400(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = client.post("/api/v1/ci/competitor-urls", json={"url": "https://alibaba.com/dp/x"}, headers=headers)
    assert resp.status_code == 400


def test_patch_tags_and_archive(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = client.post(
        "/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/tagme"}, headers=headers
    ).json()["id"]

    patch_resp = client.patch(
        f"/api/v1/ci/competitor-urls/{url_id}", json={"tags": ["DIRECT_RIVAL"]}, headers=headers
    )
    assert patch_resp.status_code == 200
    listed = client.get("/api/v1/ci/competitor-urls", headers=headers).json()
    assert listed[0]["tags"] == ["DIRECT_RIVAL"]

    archive_resp = client.patch(f"/api/v1/ci/competitor-urls/{url_id}", json={"archive": True}, headers=headers)
    assert archive_resp.status_code == 200
    listed_after_archive = client.get("/api/v1/ci/competitor-urls", headers=headers).json()
    assert listed_after_archive[0]["status"] == "ARCHIVED"


# --- Cross-tenant isolation ----------------------------------------------------------------


def test_cross_tenant_handoff_is_404_not_leaked(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)

    url_id = client.post(
        "/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/isolation-test"}, headers=headers_a
    ).json()["id"]

    resp_as_b = client.get(f"/api/v1/ci/competitor-urls/{url_id}/handoff", headers=headers_b)
    assert resp_as_b.status_code == 404

    resp_as_a = client.get(f"/api/v1/ci/competitor-urls/{url_id}/handoff", headers=headers_a)
    assert resp_as_a.status_code == 404  # no research submitted yet — still not a 200 with fabricated data


def test_cross_tenant_snapshot_history_returns_empty_not_other_tenants_data(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, tenant_b = two_tenants
    headers_a = _register_owner(fake_clerk, tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)

    url_id = client.post(
        "/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/isolation-history"}, headers=headers_a
    ).json()["id"]

    resp_as_b = client.get(f"/api/v1/ci/competitor-urls/{url_id}/snapshots", headers=headers_b)
    assert resp_as_b.status_code == 200
    assert resp_as_b.json() == []


# --- CEO Hub -------------------------------------------------------------------------------


def test_ceo_hub_agents_requires_no_auth(client: TestClient) -> None:
    resp = client.get("/api/v1/ceo-hub/agents")
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()}
    assert ids == {"CI", "PI", "CFO", "CMO"}


def test_research_now_manual_fields_only_succeeds_and_links_to_ceo_run(
    client: TestClient, fake_clerk: _FakeClerkClient, two_tenants
) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    url_id = client.post(
        "/api/v1/ci/competitor-urls", json={"url": "https://amazon.in/dp/research-now-test"}, headers=headers
    ).json()["id"]

    resp = client.post(
        "/api/v1/ceo-hub/research-now",
        json={"competitor_url_id": url_id, "image_refs": [], "manual_fields": {"listed_price_paise": 99900, "availability": "IN_STOCK"}},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ci"]["captureStatus"] == "COMPLETE"

    linkage_resp = client.get(f"/api/v1/ceo-hub/runs/{body['ceoAgentRunId']}", headers=headers)
    assert linkage_resp.status_code == 200
    linkage = linkage_resp.json()
    assert linkage["parent"]["agentId"] == "CEO"
    assert linkage["parent"]["parentRunId"] is None
    assert len(linkage["children"]) == 1
    assert linkage["children"][0]["agentId"] == "CI"


def test_summary_reflects_created_competitor(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    client.post("/api/v1/ci/competitor-urls", json={"url": "https://flipkart.com/p/summary-test"}, headers=headers)

    resp = client.get("/api/v1/ci/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["trackedCompetitors"] == 1
    assert body["staleCompetitors"] == 1  # no research submitted yet -> counts as stale


# --- Digest --------------------------------------------------------------------------------


def test_digest_preview_empty_with_no_activity(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = client.get("/api/v1/ci/digest/preview", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["competitorsWithActivity"] == 0


def test_digest_subscription_defaults_then_updates(client: TestClient, fake_clerk: _FakeClerkClient, two_tenants) -> None:
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    default_resp = client.get("/api/v1/ci/digest/subscription", headers=headers)
    assert default_resp.status_code == 200
    assert default_resp.json()["isDefault"] is True

    put_resp = client.put(
        "/api/v1/ci/digest/subscription", json={"frequency": "DAILY", "channel": "IN_APP", "enabled": True}, headers=headers
    )
    assert put_resp.status_code == 200

    updated_resp = client.get("/api/v1/ci/digest/subscription", headers=headers)
    body = updated_resp.json()
    assert body["frequency"] == "DAILY"
    assert body["isDefault"] is False
