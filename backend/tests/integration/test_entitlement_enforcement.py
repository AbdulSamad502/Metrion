"""F3 of the entitlement roadmap, integration coverage — mirrors F2's own `test_entitlement.py`
pattern exactly (seed a real, platform-default `entitlement_cap_config` row as `metrion_migrate`,
`cap_value=0` so the very first check is guaranteed `OVER_CAP`/denied). Proves real enforcement
against a real Postgres: the composition function's side effects do NOT happen (no new
`leak_finding`/`manual_adjustment` row is written), the real denial is raised/returned, and
`agent_run.status = 'FAILED'`.

Covers 2 real dispatch functions (`dispatch_cfo_reconcile`, `dispatch_cfo_enter_expense`) and 2
real HTTP routes (`POST /api/v1/cfo/reconcile`, `PUT /api/v1/cfo/expenses`) — the sharpest,
most money-adjacent surfaces (leak findings, manual financial adjustments).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from backend.agents import ceo_hub
from backend.entitlement import EntitlementDenied
from backend.repositories import agent_run_repo
from backend.tenant_context import tenant_scope

_AS_OF = date(2026, 9, 25)
_OCCURRED_AT = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def _seed_zero_cap(migrate_engine, *, agent_code: str, meter_code: str) -> None:
    """A platform-default (tenant_id IS NULL) entitlement_cap_config row with cap_value=0 —
    the same posture F2's own `_seed_platform_cap` uses, guaranteeing the very first check is
    OVER_CAP/denied with zero metered_event rows needed."""
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


def _leak_finding_count(tenant_id: uuid.UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return conn.execute(text("SELECT count(*) FROM leak_finding")).scalar_one()


def _manual_adjustment_count(tenant_id: uuid.UUID) -> int:
    with tenant_scope(tenant_id) as conn:
        return conn.execute(text("SELECT count(*) FROM manual_adjustment")).scalar_one()


# --- dispatch layer (agents/ceo_hub.py) ---------------------------------------------------


def test_dispatch_cfo_reconcile_denies_and_writes_no_leak_finding_when_cap_is_zero(
    two_tenants, migrate_engine, app_user
):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.reconcile")

    assert _leak_finding_count(tenant_a) == 0

    with pytest.raises(EntitlementDenied) as exc_info:
        ceo_hub.dispatch_cfo_reconcile(
            tenant_a,
            requested_by=app_user,
            marketplace="AMAZON",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            as_of_date=_AS_OF,
            permission_check="PASS",
            now=_OCCURRED_AT,
        )

    assert exc_info.value.result.evaluation_basis == "OVER_CAP"
    assert _leak_finding_count(tenant_a) == 0  # the composition function never ran

    with tenant_scope(tenant_a) as conn:
        run_row = conn.execute(
            text(
                "SELECT status, entitlement_check, error_reason FROM agent_run "
                "WHERE tenant_id = :t AND trigger_ref = 'ceo_hub.cfo.reconcile'"
            ),
            {"t": str(tenant_a)},
        ).mappings().first()
    assert run_row is not None
    assert run_row["status"] == "FAILED"
    assert run_row["entitlement_check"] == "DENIED"
    assert run_row["error_reason"] == "OVER_CAP"


def test_dispatch_cfo_enter_expense_denies_and_writes_no_manual_adjustment_when_cap_is_zero(
    two_tenants, migrate_engine, app_user
):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.enter_expense")

    assert _manual_adjustment_count(tenant_a) == 0

    with pytest.raises(EntitlementDenied):
        ceo_hub.dispatch_cfo_enter_expense(
            tenant_a,
            requested_by=app_user,
            target_type="PERIOD",
            target_ref="2026-09",
            field="expense.packaging",
            value={"amount_paise": 5_000},
            reason=None,
            permission_check="PASS",
            now=_OCCURRED_AT,
        )

    assert _manual_adjustment_count(tenant_a) == 0

    with tenant_scope(tenant_a) as conn:
        run_row = conn.execute(
            text(
                "SELECT status FROM agent_run "
                "WHERE tenant_id = :t AND trigger_ref = 'ceo_hub.cfo.enter_expense'"
            ),
            {"t": str(tenant_a)},
        ).mappings().first()
    assert run_row is not None
    assert run_row["status"] == "FAILED"


def test_dispatch_cfo_anomaly_check_denies_and_never_runs_when_cap_is_zero(two_tenants, migrate_engine, app_user):
    """E3 — anomaly-check's entitlement gate is mandatory (F3's exact pattern), same as every
    other real CFO dispatch function proven here."""
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.anomaly_check")

    from backend.services.cfo_actions import AnomalyCheckRequest

    request = AnomalyCheckRequest(
        target_ref="SKU-1",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        as_of_date=_AS_OF,
        requested_by=app_user,
    )

    with pytest.raises(EntitlementDenied) as exc_info:
        ceo_hub.dispatch_cfo_anomaly_check(
            tenant_a,
            requested_by=app_user,
            request=request,
            permission_check="PASS",
            now=_OCCURRED_AT,
        )

    assert exc_info.value.result.evaluation_basis == "OVER_CAP"

    with tenant_scope(tenant_a) as conn:
        run_row = conn.execute(
            text(
                "SELECT status, entitlement_check, error_reason FROM agent_run "
                "WHERE tenant_id = :t AND trigger_ref = 'ceo_hub.cfo.anomaly_check'"
            ),
            {"t": str(tenant_a)},
        ).mappings().first()
    assert run_row is not None
    assert run_row["status"] == "FAILED"
    assert run_row["entitlement_check"] == "DENIED"
    assert run_row["error_reason"] == "OVER_CAP"


# --- HTTP route layer (api/v1/cfo.py) -------------------------------------------------------


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


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


def test_post_reconcile_route_returns_402_and_writes_no_leak_finding_when_cap_is_zero(
    app_client, fake_clerk, two_tenants, migrate_engine
):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.reconcile")
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post(
        "/api/v1/cfo/reconcile",
        json={
            "marketplace": "AMAZON",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "as_of_date": "2026-09-25",
        },
        headers=headers,
    )

    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["evaluationBasis"] == "OVER_CAP"
    assert _leak_finding_count(tenant_a) == 0


def test_put_expense_route_returns_402_and_writes_no_manual_adjustment_when_cap_is_zero(
    app_client, fake_clerk, two_tenants, migrate_engine
):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.enter_expense")
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.put(
        "/api/v1/cfo/expenses",
        json={
            "target_type": "PERIOD",
            "target_ref": "2026-09",
            "field": "expense.packaging",
            "value": {"amount_paise": 5_000},
        },
        headers=headers,
    )

    assert resp.status_code == 402, resp.text
    assert _manual_adjustment_count(tenant_a) == 0


def test_post_anomaly_check_route_returns_402_when_cap_is_zero(app_client, fake_clerk, two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.anomaly_check")
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post(
        "/api/v1/cfo/anomaly-check",
        json={
            "target_ref": "SKU-1",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "as_of_date": "2026-09-25",
        },
        headers=headers,
    )

    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["evaluationBasis"] == "OVER_CAP"


def test_post_anomaly_check_route_succeeds_when_entitled(app_client, fake_clerk, two_tenants, migrate_engine):
    """No cap seeded at all -> `NO_CAP_CONFIGURED`/passed=True (entitlement.md §5.5) — the real
    success path, proving the entitlement gate does not deny by default. With no
    `CONTRIBUTION_MARGIN_PCT` history and no `anomaly_detection_config` rows seeded (this
    checkpoint's own explicit non-goal), the honest real response is a `200` carrying three
    `AnomalyConfigurationGap` outcomes and `seriesLength=0` — a real non-flag outcome, not an
    error."""
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post(
        "/api/v1/cfo/anomaly-check",
        json={
            "target_ref": "SKU-1",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "as_of_date": "2026-09-25",
        },
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["targetRef"] == "SKU-1"
    assert body["metric"] == "MARGIN_PCT"
    assert body["seriesLength"] == 0
    assert len(body["methods"]) == 3
    for method_outcome in body["methods"]:
        assert method_outcome["configurationGap"] is not None
        assert method_outcome["flag"] is None
