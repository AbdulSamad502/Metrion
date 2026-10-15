"""`POST /api/v1/cfo/pnl` — cfo-agent.md §6.8 `cfo.pnl`, real Postgres.

Closes the gap: `CFO_PNL`/`dispatch_cfo_pnl` (agents/ceo_hub.py) and `compute_period_pnl`
(services/cfo_actions.py) were already fully built and tested, but no HTTP route ever called
either of them. This file is the route-level proof, mirroring
`test_cfo_gst_lookup.py`/`test_cfo_preview.py`'s own real-Postgres fixture conventions
(`app_client`, `fake_clerk`, `_register_owner`/`_register_partner_with_permissions`,
`_seed_zero_cap`) exactly.

**Request shape note**: `PeriodPnlHttpRequest` posts already-assembled `CanonicalLine`s (a
fuller shape than `GstPeriodSummaryLineRequest`, since `compute_period_pnl` genuinely needs
cancellation/return/RTO status fields that route deliberately omits — see
`PeriodPnlLineRequest`'s own docstring in `api/v1/cfo.py`). This mirrors the established
precedent `/gst/period-summary` and `/batch-size` already set for caller-assembled canonical
data over HTTP in this file; `compute_period_pnl` has no raw-ingestion path of its own to call
instead (`PeriodPnlRequest`'s own docstring, judgment call 4).

Covers: a successful call returns 200 with `marginPct`, `feeRatioPct` and `returnRatePct`
(each with its real `valueFraction`) present; entitlement denial (a real seeded
`entitlement_cap_config` cap_value=0 row) returns 402; a member without `agent.cfo` returns
403.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

_AS_OF = date(2026, 9, 25)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)


@pytest.fixture(autouse=True)
def _clean_metric_result_table(migrate_engine):
    """`metric_result` is owned by calc-engine's own migration chain, not backend's
    `_clean_backend_tables` fixture — cleaned here directly, mirroring `test_cfo_preview.py`'s
    own before/after convention for calc-engine-owned tables."""
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM metric_result"))
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM metric_result"))


def _pnl_body(sku: str = "SKU-1") -> dict[str, object]:
    """One line, COGS available, no cancellation/return/RTO — the plain happy path. Real money
    math: gross_item_amount 1000.00 INR, a 50.00 INR COMMISSION fee component, COGS 100.00 INR
    per unit at quantity 2 -> a real, non-zero CONTRIBUTION_PROFIT and CONTRIBUTION_MARGIN_PCT,
    never a stubbed/seeded MetricResult."""
    sales_line_id = str(uuid.uuid4())
    return {
        "lines": [
            {
                "sales_line_id": sales_line_id,
                "marketplace": "MEESHO",
                "document_type": "INVOICE",
                "quantity": 2,
                "invoice_date": _AS_OF.isoformat(),
                "dispatch_date": _AS_OF.isoformat(),
                "order_date": _AS_OF.isoformat(),
                "gross_item_amount_paise": 1_000_00,
                "components": [
                    {
                        "component_kind": "FEE",
                        "component_code": "COMMISSION",
                        "source_side": "INVOICE",
                        "amount_paise": 50_00,
                    }
                ],
                "confidence": "VERIFIED",
                "cancellation_state": "DELIVERED",
                "return_status": "DELIVERED",
                "rto_status": "NOT_RTO",
            }
        ],
        "period_start": _PERIOD_START.isoformat(),
        "period_end": _PERIOD_END.isoformat(),
        "as_of_date": _AS_OF.isoformat(),
        "recognition_state": "RECOGNISED",
        "sku_by_line": {sales_line_id: sku},
        "cost_history_by_sku": {sku: [{"amount_paise": 100_00, "effective_from": "2026-01-01"}]},
        "fee_component_codes": ["COMMISSION"],
        "forward_logistics_codes": [],
        "reverse_logistics_codes": [],
        "non_refunded_fee_codes": [],
        "advertising_adjustment_values": [],
        "other_adjustment_values": [],
        "ingestion_run_ids": ["run-1"],
        "adapter_versions": ["meesho.v1"],
        "active_adjustment_ids": [],
    }


# --- HTTP route layer --------------------------------------------------------------------


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


def _register_partner_with_permissions(fake_clerk, tenant_id: uuid.UUID, *, permissions: dict[str, object]) -> dict[str, str]:
    """A PARTNER (not OWNER — OWNER bypasses the permission grid entirely, §5.2) with EXACTLY
    the given permissions grid, mirroring `test_cfo_gst_lookup.py`'s own helper exactly."""
    from backend.auth.permissions import PARTNER_ROLE
    from backend.repositories import app_user_repo, membership_repo

    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=True,
        auth_provider="GOOGLE",
        display_name="Test Partner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.upsert_partner(tenant_id, user_row["id"], role=PARTNER_ROLE, status="ACTIVE")
    membership_repo.set_permissions(tenant_id, user_row["id"], permissions)

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


def test_pnl_route_succeeds_and_returns_margin_pct(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post("/api/v1/cfo/pnl", json=_pnl_body(), headers=headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["nrr"]["isAvailable"] is True
    assert body["contributionProfit"]["isAvailable"] is True
    assert "marginPct" in body
    assert body["marginPct"]["metricCode"] == "CONTRIBUTION_MARGIN_PCT"
    assert body["marginPct"]["isAvailable"] is True
    assert body["marginPct"]["valuePaise"] is None  # a percentage, never paise-shaped
    assert body["marginPct"]["valueFraction"] is not None
    assert body["dataRequestId"] is None

    # anomaly-detection.md §6.1 P2's resolution (FEE_RATIO_PCT) and RETURN_RATE_PCT — both real
    # gaps this checkpoint closes, now present on the real HTTP response.
    assert "feeRatioPct" in body
    assert body["feeRatioPct"]["metricCode"] == "FEE_RATIO_PCT"
    assert body["feeRatioPct"]["isAvailable"] is True
    assert body["feeRatioPct"]["valuePaise"] is None
    assert body["feeRatioPct"]["valueFraction"] is not None

    assert "returnRatePct" in body
    assert body["returnRatePct"]["metricCode"] == "RETURN_RATE_PCT"
    assert body["returnRatePct"]["isAvailable"] is True
    assert body["returnRatePct"]["valuePaise"] is None
    assert body["returnRatePct"]["valueFraction"] is not None

    # Real, persisted rows — not a stubbed/seeded response.
    from calc_engine.repositories import metric_result_repo

    resolved = metric_result_repo.get(tenant_a, uuid.UUID(body["marginPct"]["engineResultRef"]))
    assert resolved is not None
    assert resolved["metric_code"] == "CONTRIBUTION_MARGIN_PCT"

    resolved_fee_ratio = metric_result_repo.get(tenant_a, uuid.UUID(body["feeRatioPct"]["engineResultRef"]))
    assert resolved_fee_ratio is not None
    assert resolved_fee_ratio["metric_code"] == "FEE_RATIO_PCT"

    resolved_return_rate = metric_result_repo.get(tenant_a, uuid.UUID(body["returnRatePct"]["engineResultRef"]))
    assert resolved_return_rate is not None
    assert resolved_return_rate["metric_code"] == "RETURN_RATE_PCT"


def test_pnl_route_denies_402_when_cfo_entitlement_capped(app_client, fake_clerk, two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.pnl")
    headers = _register_owner(fake_clerk, tenant_a)

    resp = app_client.post("/api/v1/cfo/pnl", json=_pnl_body(), headers=headers)
    assert resp.status_code == 402, resp.text
    assert resp.json()["detail"]["evaluationBasis"] == "OVER_CAP"


def test_pnl_route_denies_403_when_agent_cfo_permission_absent(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={})

    resp = app_client.post("/api/v1/cfo/pnl", json=_pnl_body(), headers=headers)
    assert resp.status_code == 403, resp.text


# --- ST-01: display-only "was advertising entered in this calculation?" --------------------------------------------------------------------------
# Additive response fields; ContributionProfit must be numerically identical whether advertising is absent or an explicit zero, and reduced by exactly the
# entered amount otherwise. The legacy expense tracker (PUT /cfo/expenses) rows are NOT read by this route, which is why the UI says "in this calculation".


def _pnl_with_advertising(app_client, headers, advertising):
    body = _pnl_body()
    body["advertising_adjustment_values"] = advertising
    resp = app_client.post("/api/v1/cfo/pnl", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pnl_route_reports_advertising_entered_without_changing_contribution_profit(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)

    absent = _pnl_with_advertising(app_client, headers, [])
    zero = _pnl_with_advertising(app_client, headers, [{"amount_paise": 0}])
    entered = _pnl_with_advertising(app_client, headers, [{"amount_paise": 4_500}])

    assert absent["advertisingEntered"] is False
    assert absent["advertisingCostsPaise"] is None
    assert zero["advertisingEntered"] is True
    assert zero["advertisingCostsPaise"] == 0
    assert entered["advertisingEntered"] is True
    assert entered["advertisingCostsPaise"] == 4_500

    assert zero["contributionProfit"]["valuePaise"] == absent["contributionProfit"]["valuePaise"]
    assert absent["contributionProfit"]["valuePaise"] - entered["contributionProfit"]["valuePaise"] == 4_500
