"""`POST /api/v1/cfo/cash-reconciliation` — cfo-agent.md §6.10, deterministic-engine.md §5.13.3,
real Postgres.

Closes the gap: `cash_reconciliation()` is new this checkpoint (deterministic-engine.md
§5.13.3) — this file is the route-level proof, mirroring `test_cfo_pnl.py`'s real-Postgres
fixture conventions (`app_client`, `fake_clerk`, `_register_owner`, `_seed_zero_cap`) exactly.

Covers: a real settlement_line produces a real, available `cashReceived`; `cashExpected`/
`cashVariance` are structurally unavailable (the disclosed scope limit); entitlement denial.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

_AS_OF = date(2026, 1, 20)
_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)


@pytest.fixture(autouse=True)
def _clean_tables(migrate_engine):
    tables = ("line_component", "sales_line", "settlement_line", "ingestion_run", "report_file")
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def _insert_report_file_and_run(tenant_id: uuid.UUID, *, marketplace: str) -> uuid.UUID:
    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    file_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_file
                    (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                     byte_size, storage_uri, uploaded_by, uploaded_at)
                VALUES
                    (:id, :tenant_id, :marketplace, 'SETTLEMENT', :sha, 'synthetic.xlsx', 100,
                     's3://bucket/x', :uploaded_by, :uploaded_at)
                """
            ),
            {
                "id": str(file_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": datetime.now(timezone.utc),
            },
        )
    return ingestion_run_repo.insert_ingestion_run(
        tenant_id,
        report_file_id=file_id,
        adapter_id=f"{marketplace.lower()}.synthetic.v1",
        adapter_version="v1",
        started_at=datetime.now(timezone.utc),
    )


def _insert_settlement_line(tenant_id: uuid.UUID, *, ingestion_run_id: uuid.UUID, marketplace: str) -> None:
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO settlement_line
                    (id, tenant_id, ingestion_run_id, marketplace, order_ref, line_ref,
                     settlement_id, gross_settlement_amount, currency, settlement_date,
                     document_type, source_row_number, source_row_json, confidence)
                VALUES
                    (:id, :tenant_id, :ingestion_run_id, :marketplace, 'ORD-1', NULL,
                     NULL, 5000, 'INR', :settlement_date, 'SETTLEMENT', 1, '{}'::jsonb, 'VERIFIED')
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "ingestion_run_id": str(ingestion_run_id),
                "marketplace": marketplace,
                "settlement_date": date(2026, 1, 15),
            },
        )


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


def _body(marketplace: str = "MEESHO") -> dict[str, object]:
    return {
        "marketplace": marketplace,
        "period_start": _PERIOD_START.isoformat(),
        "period_end": _PERIOD_END.isoformat(),
        "as_of_date": _AS_OF.isoformat(),
    }


def test_cash_received_real_and_expected_structurally_unavailable(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    run_id = _insert_report_file_and_run(tenant_a, marketplace="MEESHO")
    _insert_settlement_line(tenant_a, ingestion_run_id=run_id, marketplace="MEESHO")

    resp = app_client.post("/api/v1/cfo/cash-reconciliation", json=_body(), headers=headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["cashReceived"]["isAvailable"] is True
    assert body["cashReceived"]["valuePaise"] == 5000
    assert body["cashExpected"]["isAvailable"] is False
    assert body["cashExpected"]["unavailableReason"] is not None
    assert body["cashVariance"]["isAvailable"] is False
    assert body["tdsDeducted"]["isAvailable"] is False


def test_tcs_collected_unavailable_for_meesho(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post("/api/v1/cfo/cash-reconciliation", json=_body("MEESHO"), headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tcsCollected"]["isAvailable"] is False


def test_cash_reconciliation_route_denies_402_when_cfo_entitlement_capped(app_client, fake_clerk, two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.cash_reconciliation")
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post("/api/v1/cfo/cash-reconciliation", json=_body(), headers=headers)
    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["evaluationBasis"] == "OVER_CAP"
