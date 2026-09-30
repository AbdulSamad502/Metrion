"""PI's direct-execution routes (`api/v1/pi.py`) — permission-denied and entitlement-denied
paths, plus `pi.discover`'s two-key gate specifically (T31-equivalent for `agent.pi` +
`research.niche_run`, mirroring `test_cfo_route_entitlement_enforcement.py`'s exact shape).

True unit tests: routes are called as plain Python functions (bypassing FastAPI's dependency
injection entirely — `AuthContext` is constructed directly), `resolve_pi_entitlement`/
`resolve_niche_run_entitlement` are monkeypatched, and `run_discovery`/`run_supplier_lookup`
are replaced with spies that fail the test if invoked. No Postgres needed here.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from backend.api.v1 import pi as pi_routes
from backend.auth.context import AuthContext
from backend.entitlement import EntitlementResult, NicheRunEntitlementResult


def _passing_pi_result(*, meter_code: str = "pi.discover") -> EntitlementResult:
    return EntitlementResult(
        passed=True,
        reason=None,
        meter_code=meter_code,
        usage_count=0,
        cap_value=None,
        evaluation_basis="NO_CAP_CONFIGURED",
        denial_rendering="ERROR",
        reduced_payload_action_code=None,
        period_key="2026-09",
    )


def _denied_pi_result(*, meter_code: str) -> EntitlementResult:
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


def _passing_niche_run_result() -> NicheRunEntitlementResult:
    return NicheRunEntitlementResult(passed=True, reason=None, niche_run_count=0)


def _denied_niche_run_result() -> NicheRunEntitlementResult:
    return NicheRunEntitlementResult(passed=False, reason="OVER_CAP", niche_run_count=99)


def _fake_ctx(tenant_id: uuid.UUID, *, role: str = "PARTNER", permissions: dict[str, object] | None = None) -> AuthContext:
    return AuthContext(
        app_user_id=uuid.uuid4(),
        clerk_user_id="user_test",
        email_verified=True,
        tenant_id=tenant_id,
        membership_status="ACTIVE",
        role=role,
        permissions=permissions if permissions is not None else {},
        onboarding_state="ACTIVE",
    )


def _never_call(*args, **kwargs):
    raise AssertionError("composition function must NOT be called on a denied request")


def _discover_body() -> "pi_routes.DiscoverRequest":
    return pi_routes.DiscoverRequest(niche_brief_id=uuid.uuid4(), depth="SHALLOW")


# --- pi.discover's two-key gate (agent.pi permission + research.niche_run permission) -------


def test_discover_route_denies_403_when_research_niche_run_permission_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """`require_auth(permission=AGENT_PI)` is assumed already-passed (this is a unit test of
    the handler body, not the FastAPI dependency chain) — the in-handler `research.niche_run`
    check must independently deny."""
    monkeypatch.setattr(pi_routes, "resolve_pi_entitlement", lambda *a, **k: _passing_pi_result())
    monkeypatch.setattr(pi_routes, "resolve_niche_run_entitlement", lambda *a, **k: _passing_niche_run_result())
    monkeypatch.setattr(pi_routes, "run_discovery", _never_call)

    tenant_id = uuid.uuid4()
    ctx = _fake_ctx(tenant_id, permissions={})  # agent.pi present via require_auth (bypassed here), research.niche_run absent

    with pytest.raises(HTTPException) as exc_info:
        pi_routes.post_discover(_discover_body(), ctx=ctx)

    assert exc_info.value.status_code == 403
    assert "research.niche_run" in exc_info.value.detail


def test_discover_route_denies_402_when_pi_entitlement_denied_even_with_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pi_routes, "resolve_pi_entitlement", lambda *a, **k: _denied_pi_result(meter_code="pi.discover"))
    monkeypatch.setattr(pi_routes, "resolve_niche_run_entitlement", lambda *a, **k: _passing_niche_run_result())
    monkeypatch.setattr(pi_routes, "run_discovery", _never_call)

    tenant_id = uuid.uuid4()
    ctx = _fake_ctx(tenant_id, permissions={"research.niche_run": True})

    with pytest.raises(HTTPException) as exc_info:
        pi_routes.post_discover(_discover_body(), ctx=ctx)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["meterCode"] == "pi.discover"


def test_discover_route_denies_402_when_niche_run_entitlement_denied_even_with_pi_entitlement_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither entitlement substitutes for the other — mirrors AC17b's "both must pass" for
    CFO's `agent.cfo`/`service.gst_lookup` pair."""
    monkeypatch.setattr(pi_routes, "resolve_pi_entitlement", lambda *a, **k: _passing_pi_result())
    monkeypatch.setattr(pi_routes, "resolve_niche_run_entitlement", lambda *a, **k: _denied_niche_run_result())
    monkeypatch.setattr(pi_routes, "run_discovery", _never_call)

    tenant_id = uuid.uuid4()
    ctx = _fake_ctx(tenant_id, permissions={"research.niche_run": True})

    with pytest.raises(HTTPException) as exc_info:
        pi_routes.post_discover(_discover_body(), ctx=ctx)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["service"] == "research.niche_run"


def test_discover_route_never_calls_run_discovery_when_either_gate_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sharpest version of the two tests above combined — proves the permission check runs
    BEFORE either entitlement resolution, and no entitlement function is even consulted once
    permission has already denied."""
    monkeypatch.setattr(pi_routes, "resolve_pi_entitlement", _never_call)
    monkeypatch.setattr(pi_routes, "resolve_niche_run_entitlement", _never_call)
    monkeypatch.setattr(pi_routes, "run_discovery", _never_call)

    tenant_id = uuid.uuid4()
    ctx = _fake_ctx(tenant_id, permissions={})

    with pytest.raises(HTTPException) as exc_info:
        pi_routes.post_discover(_discover_body(), ctx=ctx)

    assert exc_info.value.status_code == 403


# --- pi.supplier_lookup's single agent.pi-scoped entitlement gate --------------------------


def test_supplier_lookup_route_returns_402_and_never_looks_up_when_entitlement_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pi_routes, "resolve_pi_entitlement", lambda *a, **k: _denied_pi_result(meter_code="pi.supplier_lookup")
    )
    monkeypatch.setattr(pi_routes, "run_supplier_lookup", _never_call)

    tenant_id = uuid.uuid4()
    ctx = _fake_ctx(tenant_id)
    body = pi_routes.SupplierLookupRequest(run_id=uuid.uuid4(), candidate_ids=[uuid.uuid4()])

    with pytest.raises(HTTPException) as exc_info:
        pi_routes.post_supplier_lookup(body, ctx=ctx)

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["meterCode"] == "pi.supplier_lookup"


# --- pi.report: read-only, no entitlement gate at all (§6.8) --------------------------------


def test_report_route_returns_404_when_run_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_value_error(*args, **kwargs):
        raise ValueError("no pi_research_run for this tenant")

    monkeypatch.setattr(pi_routes, "load_report", _raise_value_error)

    tenant_id = uuid.uuid4()
    ctx = _fake_ctx(tenant_id)

    with pytest.raises(HTTPException) as exc_info:
        pi_routes.get_report(uuid.uuid4(), ctx=ctx)

    assert exc_info.value.status_code == 404
