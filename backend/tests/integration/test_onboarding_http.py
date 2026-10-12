"""`POST /api/v1/onboarding/business` as the onboarding page uses it: the one write that creates a workspace.

The page sends `{business_name}` and reads `{tenantId, clerkOrgId}` back (it passes `clerkOrgId` to Clerk's `setActive`). Real app, auth chain, tenant and membership
repositories and Postgres (the scratch database); only Clerk is faked, including organisation creation, so no organisation is created anywhere real."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.v1 import onboarding as onboarding_api
from backend.auth import context as auth_context_module
from backend.main import app
from backend.repositories import app_user_repo, membership_repo, tenant_repo


@dataclass
class _AuthState:
    is_signed_in: bool
    payload: dict[str, Any] | None


@dataclass
class _Organizations:
    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def create(self, *, request: Any) -> Any:
        org_id = f"org_{uuid.uuid4().hex}"
        self.created.append(request.name)
        return SimpleNamespace(id=org_id)

    def delete(self, *, organization_id: str) -> None:
        self.deleted.append(organization_id)


@dataclass
class _Clerk:
    tokens: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    organizations: _Organizations = field(default_factory=_Organizations)

    async def authenticate_request_async(self, request: Any, options: Any) -> _AuthState:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token in self.tokens:
            user, org = self.tokens[token]
            return _AuthState(True, {"sub": user, "org_id": org})
        return _AuthState(False, None)


@pytest.fixture
def clerk(monkeypatch) -> _Clerk:
    fake = _Clerk()
    monkeypatch.setattr(auth_context_module, "get_clerk_client", lambda: fake)
    monkeypatch.setattr(onboarding_api, "get_clerk_client", lambda: fake)
    return fake


def _new_user(clerk: _Clerk, *, verified: bool = True, org: str | None = None) -> dict[str, str]:
    user = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(clerk_user_id=user, email=f"{user}@example.com", email_verified=verified, auth_provider="GOOGLE", display_name="New Seller")
    token = f"tok_{uuid.uuid4()}"
    clerk.tokens[token] = (user, org)
    return {"Authorization": f"Bearer {token}"}


URL = "/api/v1/onboarding/business"


def test_a_verified_seller_with_no_workspace_gets_one_and_the_page_gets_what_it_reads(clerk):
    client = TestClient(app)
    headers = _new_user(clerk)
    resp = client.post(URL, json={"business_name": "Zyquora Home"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) >= {"tenantId", "clerkOrgId"}  # the two fields the onboarding page reads
    assert clerk.organizations.created == ["Zyquora Home"] and body["clerkOrgId"].startswith("org_")
    tenant = tenant_repo.get_by_clerk_org_id(body["clerkOrgId"])
    assert tenant is not None and str(tenant["id"]) == body["tenantId"] and tenant["business_name"] == "Zyquora Home"  # the workspace really exists, under the name given


def test_the_business_name_is_validated_before_anything_is_created(clerk):
    client = TestClient(app)
    headers = _new_user(clerk)
    for bad in ({}, {"business_name": ""}, {"business_name": "x" * 201}, {"business_name": 5}, {"businessName": "Zyquora"}):
        assert client.post(URL, json=bad, headers=headers).status_code == 422, bad
    assert clerk.organizations.created == []  # no organisation was created for an invalid request


def test_it_needs_a_session_and_a_verified_email(clerk):
    client = TestClient(app)
    assert client.post(URL, json={"business_name": "Zyquora"}).status_code == 401
    unverified = _new_user(clerk, verified=False)
    assert client.post(URL, json={"business_name": "Zyquora"}, headers=unverified).status_code in (403, 409)
    assert clerk.organizations.created == []


def test_a_member_who_already_has_a_workspace_is_refused_and_no_second_one_is_made(clerk, two_tenants):
    a, _ = two_tenants
    user = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(clerk_user_id=user, email=f"{user}@example.com", email_verified=True, auth_provider="GOOGLE", display_name="Owner")
    row = app_user_repo.get_by_clerk_user_id(user)
    membership_repo.create_owner(a, row["id"])
    token = f"tok_{uuid.uuid4()}"
    clerk.tokens[token] = (user, f"org_{a}")
    resp = TestClient(app).post(URL, json={"business_name": "Another"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 409
    assert clerk.organizations.created == []
