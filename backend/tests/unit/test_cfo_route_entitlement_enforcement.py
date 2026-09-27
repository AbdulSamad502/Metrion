"""F3 of the entitlement roadmap — `api/v1/cfo.py`'s direct-execution HTTP routes previously
called `resolve_cfo_entitlement` ZERO times (confirmed via grep before this task started).
These tests prove the new `_require_cfo_entitlement` gate actually refuses the request — a
real `402`, composition function never called — for 3 representative routes
(`post_pricing_curve`, `post_reconcile`, `put_expense`). The other 7 routes follow the
identical, mechanically-applied pattern (see `api/v1/cfo.py` itself for the full list).

True unit tests: routes are called as plain Python functions (bypassing FastAPI's dependency
injection entirely — `AuthContext` is constructed directly), `resolve_cfo_entitlement` is
monkeypatched, and each route's composition function is replaced with a spy that fails the
test if invoked. No Postgres needed here — that's the integration suite's job.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from backend.api.v1 import cfo as cfo_routes
from backend.auth.context import AuthContext
from backend.entitlement import EntitlementResult


def _denied_result(*, meter_code: str) -> EntitlementResult:
    return EntitlementResult(
        passed=False,
        reason="OVER_CAP",
        meter_code=meter_code,
        usage_count=5,
        cap_value=5,
        evaluation_basis="OVER_CAP",
        denial_rendering="ERROR",
        reduced_payload_action_code=None,
        period_key="2026-09",
    )


def _fake_ctx(tenant_id: uuid.UUID) -> AuthContext:
    return AuthContext(
        app_user_id=uuid.uuid4(),
        clerk_user_id="user_test",
        email_verified=True,
        tenant_id=tenant_id,
        membership_status="ACTIVE",
        role="OWNER",
        permissions={},
        onboarding_state="COMPLETE",
    )


def _never_call(*args, **kwargs):
    raise AssertionError("composition function must NOT be called when entitlement is denied")


def test_post_pricing_curve_returns_402_and_never_computes_when_entitlement_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cfo_routes, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.pricing")
    )
    monkeypatch.setattr(cfo_routes, "compute_pricing_curve", _never_call)

    tenant_id = uuid.uuid4()
    body = cfo_routes.PricingCurveHttpRequest(
        sku="SKU-1",
        candidate_prices_paise=[100_000],
        basis="EXCLUSIVE",
        marketplace="AMAZON",
        category="Electronics",
        fee_type="referral",
        as_of_date=date(2026, 9, 25),
    )

    with pytest.raises(HTTPException) as exc_info:
        cfo_routes.post_pricing_curve(body, ctx=_fake_ctx(tenant_id))

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["reason"] == "OVER_CAP"
    assert exc_info.value.detail["meterCode"] == "cfo.pricing"


def test_post_reconcile_returns_402_and_never_reconciles_when_entitlement_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sharpest test here: `run_leak_shield_reconciliation` writes real, persisted
    `leak_finding` rows — proving it is never called on denial is exactly what F3 exists for."""
    monkeypatch.setattr(
        cfo_routes, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.reconcile")
    )
    monkeypatch.setattr(cfo_routes, "run_leak_shield_reconciliation", _never_call)

    tenant_id = uuid.uuid4()
    body = cfo_routes.ReconcileHttpRequest(
        marketplace="AMAZON",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        as_of_date=date(2026, 9, 25),
    )

    with pytest.raises(HTTPException) as exc_info:
        cfo_routes.post_reconcile(body, ctx=_fake_ctx(tenant_id))

    assert exc_info.value.status_code == 402


def test_put_expense_returns_402_and_never_writes_when_entitlement_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write route (manual_adjustment) — the entitlement gate must fire before the
    in-handler `financials.adjust` permission check and before `enter_expense` itself."""
    monkeypatch.setattr(
        cfo_routes, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.enter_expense")
    )
    monkeypatch.setattr(cfo_routes, "enter_expense", _never_call)

    tenant_id = uuid.uuid4()
    ctx = _fake_ctx(tenant_id)
    ctx.permissions["financials.adjust"] = True  # would otherwise pass the in-handler check
    body = cfo_routes.EnterExpenseRequest(
        target_type="SKU",
        target_ref="SKU-1",
        field="expense.packaging",
        value={"amount_paise": 100},
    )

    with pytest.raises(HTTPException) as exc_info:
        cfo_routes.put_expense(body, ctx=ctx)

    assert exc_info.value.status_code == 402


def test_post_anomaly_check_returns_402_and_never_computes_when_entitlement_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E3 — anomaly-check's entitlement gate is mandatory (unlike `cfo.preview`'s documented
    exemption), so it must follow F3's exact pattern like every other CFO route here."""
    monkeypatch.setattr(
        cfo_routes, "resolve_cfo_entitlement", lambda *a, **k: _denied_result(meter_code="cfo.anomaly_check")
    )
    monkeypatch.setattr(cfo_routes, "run_anomaly_check", _never_call)

    tenant_id = uuid.uuid4()
    body = cfo_routes.AnomalyCheckHttpRequest(
        target_ref="SKU-1",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        as_of_date=date(2026, 9, 25),
    )

    with pytest.raises(HTTPException) as exc_info:
        cfo_routes.post_anomaly_check(body, ctx=_fake_ctx(tenant_id))

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["reason"] == "OVER_CAP"
    assert exc_info.value.detail["meterCode"] == "cfo.anomaly_check"
