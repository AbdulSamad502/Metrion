"""B3: the CEO HTTP surface over the real app, auth chain (Clerk faked) and a real Postgres (spec §8, auth.md §7, R1, R10, R13).

Only Clerk and the two model handles are faked. Everything between — authentication, the membership grid, tenant context, RLS, the
orchestrator, the registry/choke point, the repositories — is real."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import config
from backend.api.v1 import ceo as ceo_api
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_CREATE, INVESTIGATION_VIEW, OWNER_ROLE, PARTNER_ROLE
from backend.ceo.runtime import CeoRuntime
from backend.llm.model import ScriptedModel
from backend.repositories import app_user_repo, investigation_repo as repo, membership_repo
from tests.integration.ceo_support import T0, row_counts, save_metric
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, seed_books

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

STATE = "How did last month go?"
STATE_DECISION = decision(route="BUSINESS_STATE", route_key="BS_PNL_LATEST")


@dataclass
class _AuthState:
    is_signed_in: bool
    payload: dict[str, Any] | None


@dataclass
class _FakeClerk:
    tokens: dict[str, tuple[str, str | None]] = field(default_factory=dict)

    async def authenticate_request_async(self, request: Any, options: Any) -> _AuthState:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token in self.tokens:
            user, org = self.tokens[token]
            return _AuthState(True, {"sub": user, "org_id": org})
        return _AuthState(False, None)


@pytest.fixture
def clerk(monkeypatch):
    from backend.auth import context as auth_context

    client = _FakeClerk()
    monkeypatch.setattr(auth_context, "get_clerk_client", lambda: client)
    return client


def login(clerk: _FakeClerk, tenant: uuid.UUID, *, role: str, permissions: dict[str, object] | None = None) -> dict[str, str]:
    user = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(clerk_user_id=user, email=f"{user}@example.com", email_verified=True, auth_provider="GOOGLE", display_name="T")
    row = app_user_repo.get_by_clerk_user_id(user)
    membership_repo.upsert_partner(tenant, row["id"], role=role, status="ACTIVE")
    if permissions is not None:
        membership_repo.set_permissions(tenant, row["id"], permissions)
    token = f"tok_{uuid.uuid4()}"
    clerk.tokens[token] = (user, f"org_{tenant}")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api(clerk, two_tenants):
    """(client, tenant A headers (OWNER), tenant B headers (OWNER), A, B) with a scripted runtime installed."""
    from backend.main import app

    a, b = two_tenants
    cls = Scripted({STATE: STATE_DECISION, "hello": decision()})
    rt = runtime(cls, Grounded())
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    try:
        yield TestClient(app), login(clerk, a, role=OWNER_ROLE), login(clerk, b, role=OWNER_ROLE), a, b
    finally:
        app.dependency_overrides.pop(ceo_api.get_runtime, None)


def start(client, headers) -> str:
    r = client.post("/api/v1/ceo/investigations", json={"title": "Why profit?"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["investigationId"]


# ------------------------------------------------------------------------------------------------ authentication
def test_every_endpoint_requires_authentication(api):
    client, *_ = api
    inv = str(uuid.uuid4())
    for method, path, body in (
        ("post", "/api/v1/ceo/investigations", {}), ("get", "/api/v1/ceo/investigations", None), ("get", f"/api/v1/ceo/investigations/{inv}", None),
        ("post", f"/api/v1/ceo/investigations/{inv}/turns", {"message": "hi"}), ("get", f"/api/v1/ceo/investigations/{inv}/findings", None),
        ("post", f"/api/v1/ceo/investigations/{inv}/resolve", {"resolution_note": "x"}),
    ):
        for headers in ({}, {"Authorization": "Bearer nope"}):
            r = getattr(client, method)(path, headers=headers, **({"json": body} if body is not None else {}))
            assert r.status_code == 401, (method, path)


# ------------------------------------------------------------------------------------------------ the flow
def test_start_turn_read_and_resolve_over_http(api, two_tenants):
    client, ha, _, a, _ = api
    seed_books(a)
    inv = start(client, ha)

    r = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["route"], body["routeKey"], body["compositionMode"]) == ("DELIVERED", "BUSINESS_STATE", "BS_PNL_LATEST", "TEMPLATE")
    assert "₹482,150.00" in body["answer"]
    assert [f["action_key"] for f in body["findings"]] == ["BS_PNL_LATEST"] and body["findings"][0]["source"] == "BUSINESS_STATE"
    assert {"admission", "classification", "state_read"} <= set(body["timings"]["stages"]) and isinstance(body["timings"]["totalMs"], int)
    assert [e["kind"] for e in body["events"]][:2] == ["TURN_RECEIVED", "TURN_ADMITTED"] and body["events"][-1]["kind"] == "ANSWER_READY"

    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    assert [m["role"] for m in detail["messages"]] == ["USER", "CEO"] and detail["investigation"]["status"] == "ACTIVE"
    assert set(detail["agents"]) == {"CFO", "CI", "PI", "CMO"} and detail["turns"][0]["status"] == "DELIVERED"

    polled = client.get(f"/api/v1/ceo/investigations/{inv}/findings", params={"turn_id": body["turnId"]}, headers=ha).json()
    assert [f["action_key"] for f in polled] == ["BS_PNL_LATEST"]  # the polling seam for progressive delivery
    assert [i["id"] for i in client.get("/api/v1/ceo/investigations", headers=ha).json()] == [inv]

    done = client.post(f"/api/v1/ceo/investigations/{inv}/resolve", json={"resolution_note": "Fees explained it."}, headers=ha)
    assert done.status_code == 200 and done.json() == {"status": "RESOLVED"}
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["investigation"]["resolution_note"] == "Fees explained it."
    again = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "INVESTIGATION_NOT_ACTIVE"
    assert client.post(f"/api/v1/ceo/investigations/{inv}/resolve", json={"resolution_note": "again"}, headers=ha).status_code == 409


def test_validation_errors(api):
    client, ha, *_ = api
    inv = start(client, ha)
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": ""}, headers=ha).status_code == 422
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "   "}, headers=ha).status_code == 422
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={}, headers=ha).status_code == 422
    assert client.post(f"/api/v1/ceo/investigations/{inv}/resolve", json={"resolution_note": ""}, headers=ha).status_code == 422
    assert client.get("/api/v1/ceo/investigations/not-a-uuid", headers=ha).status_code == 422
    assert client.get(f"/api/v1/ceo/investigations/{uuid.uuid4()}", headers=ha).status_code == 404


# ------------------------------------------------------------------------------------------------ authorisation
def test_the_permission_grid_is_enforced(api, clerk, two_tenants):
    client, ha, _, a, _ = api
    inv = start(client, ha)
    no_ceo = login(clerk, a, role=PARTNER_ROLE, permissions={INVESTIGATION_VIEW: True, INVESTIGATION_CREATE: True})
    no_view = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True})
    no_create = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_VIEW: True})
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "hello"}, headers=no_ceo).status_code == 403
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=no_view).status_code == 403
    assert client.get("/api/v1/ceo/investigations", headers=no_view).status_code == 403
    assert client.post("/api/v1/ceo/investigations", json={}, headers=no_create).status_code == 403
    # a member with only agent.ceo can chat?  Not without investigation.view: the turn is denied (and logged), never half-run.
    denied = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "hello"}, headers=no_view)
    assert denied.status_code == 200 and denied.json()["status"] == "DENIED" and "do not have access" in denied.json()["answer"]
    assert row_counts(a, "investigation_message") == {"investigation_message": 0}  # a member without view writes nothing into the investigation


def test_tenant_comes_only_from_the_session_never_from_the_request(api, two_tenants):
    client, ha, hb, a, b = api
    inv = start(client, ha)
    r = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "hello", "tenant_id": str(b), "tenantId": str(b)}, headers=ha)
    assert r.status_code == 200
    assert row_counts(b, "investigation", "investigation_message", "agent_run") == {"investigation": 0, "investigation_message": 0, "agent_run": 0}
    assert row_counts(a, "investigation_message")["investigation_message"] == 2
    created = client.post("/api/v1/ceo/investigations", json={"title": "x", "tenant_id": str(b)}, headers=ha)
    assert created.status_code == 201 and repo.get_investigation(a, uuid.UUID(created.json()["investigationId"])) is not None
    assert repo.list_investigations(b) == []


def test_another_tenant_gets_404_everywhere_and_sees_nothing(api, two_tenants):
    client, ha, hb, a, b = api
    seed_books(a)
    inv = start(client, ha)
    client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha)
    for method, path, body in (
        ("get", f"/api/v1/ceo/investigations/{inv}", None), ("get", f"/api/v1/ceo/investigations/{inv}/findings", None),
        ("post", f"/api/v1/ceo/investigations/{inv}/turns", {"message": STATE}), ("post", f"/api/v1/ceo/investigations/{inv}/resolve", {"resolution_note": "mine now"}),
    ):
        r = getattr(client, method)(path, headers=hb, **({"json": body} if body is not None else {}))
        assert r.status_code == 404 and r.json()["detail"] == {"code": "NOT_FOUND"}, (method, path, r.text)
    assert client.get("/api/v1/ceo/investigations", headers=hb).json() == []
    assert repo.get_investigation(a, uuid.UUID(inv))["status"] == "ACTIVE"  # B's resolve attempt changed nothing
    assert row_counts(b, "agent_run", "investigation_turn", "investigation_finding") == {"agent_run": 0, "investigation_turn": 0, "investigation_finding": 0}


def test_investigations_are_visible_tenant_wide_to_members_with_view(api, clerk, two_tenants):
    client, ha, _, a, _ = api
    inv = start(client, ha)
    colleague = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_VIEW: True})  # CP1-D8: BOTH keys (view alone is not enough — see test_ceo_api_permissions.py)
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=colleague).status_code == 200  # D8: tenant-wide visibility
    assert [i["id"] for i in client.get("/api/v1/ceo/investigations", headers=colleague).json()] == [inv]


# ------------------------------------------------------------------------------------------------ configuration
def test_an_unconfigured_ceo_is_a_503_with_no_work_done(clerk, two_tenants, monkeypatch):
    from backend.main import app

    a, _ = two_tenants
    for name in ("CEO_LLM_MODEL", "CEO_LLM_TIMEOUT_SECONDS", "CEO_CLASSIFIER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config.ceo_llm_model.cache_clear()
    config.ceo_classifier_model.cache_clear()
    config.ceo_llm_timeout_seconds.cache_clear()
    headers = login(clerk, a, role=OWNER_ROLE)
    client = TestClient(app)
    r = client.post("/api/v1/ceo/investigations", json={}, headers=headers)
    assert r.status_code == 503 and r.json()["detail"] == {"code": "CEO_NOT_CONFIGURED"}
    assert row_counts(a, "investigation") == {"investigation": 0}


def test_configuration_builds_a_runtime_without_choosing_a_model_or_a_bound(monkeypatch):
    from backend.services import ceo_runtime

    for name, value in (("CEO_LLM_MODEL", "model-x"), ("CEO_LLM_TIMEOUT_SECONDS", "120")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("CEO_CLASSIFIER_MODEL", raising=False)
    monkeypatch.delenv("CEO_LEG_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("CEO_PLAYBOOK_MAX_LEGS", raising=False)
    for fn in (config.ceo_llm_model, config.ceo_classifier_model, config.ceo_llm_timeout_seconds, config.ceo_ollama_host, config.ceo_llm_provider, config.ceo_llm_think):
        fn.cache_clear()
    rt = ceo_runtime.build_runtime()
    assert rt.classifier.name == "model-x" and rt.composer is not None and rt.composer.name == "model-x"  # one configured model serves both seams
    assert rt.leg_timeout_seconds is None and rt.max_legs is None  # no default bound exists (§6.12 rule 5)
    monkeypatch.setenv("CEO_CLASSIFIER_MODEL", "small-y")
    monkeypatch.setenv("CEO_LEG_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("CEO_PLAYBOOK_MAX_LEGS", "4")
    config.ceo_classifier_model.cache_clear()
    rt = ceo_runtime.build_runtime()
    assert (rt.classifier.name, rt.composer.name, rt.leg_timeout_seconds, rt.max_legs) == ("small-y", "model-x", 30, 4)  # L5: separable models
    monkeypatch.setenv("CEO_LLM_PROVIDER", "not-registered")
    config.ceo_llm_provider.cache_clear()
    with pytest.raises(config.MissingConfig):
        ceo_runtime.build_runtime()
    for fn in (config.ceo_llm_model, config.ceo_classifier_model, config.ceo_llm_timeout_seconds, config.ceo_ollama_host, config.ceo_llm_provider, config.ceo_llm_think):
        fn.cache_clear()
