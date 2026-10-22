"""`POST /api/v1/cfo/query` — the CFO 2.0 planner over HTTP, real Postgres, mocked planner model only (no real LLM).

The route accepts a question and CEO-resolved periods, never a plan; it answers with an evidence packet whose figures each cite a result."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

_AS_OF = date(2026, 10, 1)


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


@pytest.fixture
def fake_clerk(monkeypatch):
    from dataclasses import dataclass, field
    from typing import Any

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


def _seed_zero_cap(migrate_engine, *, agent_code: str, meter_code: str) -> None:
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entitlement_cap_config
                  (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
                VALUES
                  (:id, NULL, :agent_code, :meter_code, 'TENANT', 'MONTH', 0, :effective_from, 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "effective_from": _AS_OF,
            },
        )


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


def _seed_zero_cap(migrate_engine, *, agent_code: str, meter_code: str) -> None:
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entitlement_cap_config
                  (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
                VALUES
                  (:id, NULL, :agent_code, :meter_code, 'TENANT', 'MONTH', 0, :effective_from, 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "effective_from": _AS_OF,
            },
        )



class _FakeOllama:
    """Stands in for the local Ollama provider: returns a fixed plan, records the prompt it was given."""

    prompts: list[str] = []
    reply: str = ""

    def __init__(self, host: str) -> None:
        pass

    def complete(self, *, model: str, prompt: str) -> str:
        _FakeOllama.prompts.append(prompt)
        return _FakeOllama.reply


PLAN = json.dumps({"plan_version": "1", "intent": "METRIC_BY_DIMENSION", "limit": 20,
                   "periods": [{"start": "2026-09-01", "end": "2026-09-30", "as_of_date": "2026-10-01"}],
                   "steps": [{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "GROSS_SALES"}}]})
BODY = {"question": "how much did I sell on each marketplace in September?", "period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01"}


@pytest.fixture
def planner_on(monkeypatch):
    import backend.services.cfo_query as q

    _FakeOllama.prompts = []
    _FakeOllama.reply = PLAN
    monkeypatch.setenv("CFO_PLANNER_MODEL", "mock-planner")
    monkeypatch.setattr(q, "OllamaLlmProvider", _FakeOllama)
    monkeypatch.setattr(q, "_process_cache", None)
    return _FakeOllama


def _seed(tenant_id: uuid.UUID) -> None:
    from datetime import datetime, timezone

    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.sales_line_repo import insert_sales_line
    from data_foundation.repositories.tenant_context import tenant_scope

    fid = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(text(
            "INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at)"
            " VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'synthetic.csv', 100, 'file://x', :u, :at)"),
            {"id": str(fid), "t": str(tenant_id), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4()), "at": datetime.now(timezone.utc)})
    run = ingestion_run_repo.insert_ingestion_run(tenant_id, report_file_id=fid, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc))
    for mp, gross in (("MEESHO", 40_000), ("MEESHO", 25_000), ("FLIPKART", 15_000)):
        insert_sales_line(tenant_id, ingestion_run_id=run, marketplace=mp,
                          canonical_fields={"order_ref": f"O-{uuid.uuid4().hex[:6]}", "quantity": 1, "gross_item_amount": gross, "order_date": date(2026, 9, 10), "sku": "S"},
                          source_row_number=1, source_row_json={}, confidence="PROVISIONAL")


def test_a_question_over_http_returns_an_evidence_packet_with_refs(app_client, fake_clerk, two_tenants, planner_on):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _seed(tenant_a)
    resp = app_client.post("/api/v1/cfo/query", json=BODY, headers=headers)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == "ANSWERED"
    vals = {dict((k, v) for k, v in f["dimensionKeys"]).get("marketplace", "ALL"): f["valuePaise"] for f in out["figures"]}
    assert vals == {"MEESHO": 65_000, "FLIPKART": 15_000, "ALL": 80_000}
    assert all(f["engineResultRef"] for f in out["figures"])
    assert str(tenant_a) not in planner_on.prompts[0]  # the model is told nothing about the tenant or the data
    assert "65000" not in planner_on.prompts[0] and "40000" not in planner_on.prompts[0]  # ...and receives no figures


def test_a_second_identical_question_is_served_from_the_cache(app_client, fake_clerk, two_tenants, planner_on):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _seed(tenant_a)
    first = app_client.post("/api/v1/cfo/query", json=BODY, headers=headers).json()
    second = app_client.post("/api/v1/cfo/query", json=BODY, headers=headers).json()
    assert first["cached"] is False and second["cached"] is True and second["figures"] == first["figures"]


def test_a_bad_plan_from_the_model_is_an_honest_refusal_not_an_error(app_client, fake_clerk, two_tenants, planner_on):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    planner_on.reply = '{"plan_version": "1", "intent": "METRIC_BY_DIMENSION", "tenant_id": "x"}'
    resp = app_client.post("/api/v1/cfo/query", json=BODY, headers=headers)
    assert resp.status_code == 200 and resp.json()["status"] == "REFUSED" and resp.json()["code"] == "PLAN_MALFORMED"
    assert len(planner_on.prompts) == 2  # exactly one bounded retry


def test_the_planner_is_off_until_a_model_is_configured(app_client, fake_clerk, two_tenants, monkeypatch):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    monkeypatch.delenv("CFO_PLANNER_MODEL", raising=False)
    resp = app_client.post("/api/v1/cfo/query", json=BODY, headers=headers)
    assert resp.status_code == 200 and resp.json()["code"] == "PLANNER_OFF"


def test_a_plan_or_tenant_in_the_request_is_rejected(app_client, fake_clerk, two_tenants, planner_on):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    for extra in ({"plan": {"steps": []}}, {"tenant_id": str(uuid.uuid4())}, {"sql": "select 1"}):
        assert app_client.post("/api/v1/cfo/query", json={**BODY, **extra}, headers=headers).status_code == 422
    assert planner_on.prompts == []


def test_capped_entitlement_denies_402(app_client, fake_clerk, two_tenants, migrate_engine, planner_on):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.query")
    headers = _register_owner(fake_clerk, tenant_a)
    assert app_client.post("/api/v1/cfo/query", json=BODY, headers=headers).status_code == 402
    assert planner_on.prompts == []


def test_one_tenant_never_sees_anothers_figures(app_client, fake_clerk, two_tenants, planner_on):
    tenant_a, tenant_b = two_tenants
    _seed(tenant_a)
    headers_b = _register_owner(fake_clerk, tenant_b)
    out = app_client.post("/api/v1/cfo/query", json=BODY, headers=headers_b).json()
    assert out["status"] == "ANSWERED" and all(f["status"] == "UNAVAILABLE" for f in out["figures"])


def test_the_response_carries_per_marketplace_coverage_and_labels_a_partial_total(app_client, fake_clerk, two_tenants, planner_on):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    _seed(tenant_a)  # Meesho + Flipkart lines with no cancellation/RTO status
    planner_on.reply = json.dumps({"plan_version": "1", "intent": "METRIC_BY_DIMENSION", "limit": 20,
                                   "periods": [{"start": "2026-09-01", "end": "2026-09-30", "as_of_date": "2026-10-01"}],
                                   "steps": [{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}]})
    out = app_client.post("/api/v1/cfo/query", json=BODY, headers=headers).json()
    assert out["status"] == "ANSWERED"
    assert {c["marketplace"] for c in out["coverage"]} == {"MEESHO", "FLIPKART"} and all(c["included"] is False for c in out["coverage"])
    c = out["coverage"][0]
    assert c["sharePct"] == "0.0" and c["thresholdPct"] == "95.0" and c["excludedAmountPaise"] in (65_000, 15_000) and c["excludedRef"] and c["reason"]
    assert out["figures"][0]["status"] == "UNAVAILABLE"
