"""backend.entitlement — the CI entitlement chokepoint (still a TEMPORARY always-pass
scaffold; no CI entitlement spec exists yet, auth.md line 5) and the CFO entitlement
chokepoint (F2's real rewrite against docs/specs/entitlement.md, §5.5's EntitlementResult
contract). CI's tests prove it's a REAL per-tenant lookup, not a bare constant. CFO's tests
prove every resolution branch named in entitlement.md §6/§5.5: no cap row ->
NO_CAP_CONFIGURED/pass; a resolved cap with usage under it -> UNDER_CAP/pass; usage at/over
it -> OVER_CAP/deny; no capability rule -> denial_rendering='ERROR'; a capability rule naming
REDUCED_PAYLOAD -> that value carried through the result untouched.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from backend.entitlement import (
    CiEntitlementResult,
    EntitlementResult,
    GstLookupEntitlementResult,
    cfo_entitlement_check_value,
    entitlement_check_value,
    gst_lookup_entitlement_check_value,
    resolve_cfo_entitlement,
    resolve_gst_lookup_entitlement,
)


def test_entitlement_check_value_maps_passed_true_to_pass_string() -> None:
    result = CiEntitlementResult(passed=True, reason=None, active_competitor_urls=3)
    assert entitlement_check_value(result) == "PASS"


def test_entitlement_check_value_maps_passed_false_to_denied_string() -> None:
    result = CiEntitlementResult(passed=False, reason="over limit", active_competitor_urls=99)
    assert entitlement_check_value(result) == "DENIED"


def test_ci_entitlement_result_is_a_real_dataclass_not_a_bare_string() -> None:
    result = CiEntitlementResult(passed=True, reason=None, active_competitor_urls=0)
    assert isinstance(result.active_competitor_urls, int)
    assert result.reason is None


def test_resolve_ci_entitlement_queries_real_per_tenant_usage(monkeypatch) -> None:
    """resolve_ci_entitlement must call through to competitor_url_repo.count_active for the
    real tenant id — not return a bare hardcoded pass with no lookup at all."""
    from backend import entitlement as entitlement_module

    calls: list[uuid.UUID] = []

    def fake_count_active(tenant_id: uuid.UUID) -> int:
        calls.append(tenant_id)
        return 7

    monkeypatch.setattr(entitlement_module.competitor_url_repo, "count_active", fake_count_active)

    tenant_id = uuid.uuid4()
    result = entitlement_module.resolve_ci_entitlement(tenant_id)

    assert calls == [tenant_id]
    assert result.active_competitor_urls == 7
    assert result.passed is True


# --- resolve_gst_lookup_entitlement (G3 — TEMPORARY always-pass scaffold, mirrors CI's) -----


def test_gst_lookup_entitlement_check_value_maps_passed_true_to_pass_string() -> None:
    result = GstLookupEntitlementResult(passed=True, reason=None, gst_lookup_count=2)
    assert gst_lookup_entitlement_check_value(result) == "PASS"


def test_gst_lookup_entitlement_check_value_maps_passed_false_to_denied_string() -> None:
    result = GstLookupEntitlementResult(passed=False, reason="over limit", gst_lookup_count=99)
    assert gst_lookup_entitlement_check_value(result) == "DENIED"


def test_gst_lookup_entitlement_result_is_a_real_dataclass_not_a_bare_string() -> None:
    result = GstLookupEntitlementResult(passed=True, reason=None, gst_lookup_count=0)
    assert isinstance(result.gst_lookup_count, int)
    assert result.reason is None


def test_resolve_gst_lookup_entitlement_queries_real_per_tenant_usage(monkeypatch) -> None:
    """resolve_gst_lookup_entitlement must call through to gst_lookup_repo.count_for_tenant for
    the real tenant id — not return a bare hardcoded pass with no lookup at all, mirroring
    `test_resolve_ci_entitlement_queries_real_per_tenant_usage` exactly."""
    from backend import entitlement as entitlement_module

    calls: list[uuid.UUID] = []

    def fake_count_for_tenant(tenant_id: uuid.UUID) -> int:
        calls.append(tenant_id)
        return 5

    monkeypatch.setattr(entitlement_module.gst_lookup_repo, "count_for_tenant", fake_count_for_tenant)

    tenant_id = uuid.uuid4()
    result = entitlement_module.resolve_gst_lookup_entitlement(tenant_id)

    assert calls == [tenant_id]
    assert result.gst_lookup_count == 5
    assert result.passed is True


def test_resolve_gst_lookup_entitlement_always_passes_today(monkeypatch) -> None:
    """TEMPORARY scaffold (see module docstring) — no numeric OP9 cap exists anywhere in any
    spec today, so this must never deny, regardless of usage count. Mocks `count_for_tenant`
    (never a real Postgres connection in this unit test file, mirroring every other test here)."""
    from backend import entitlement as entitlement_module

    monkeypatch.setattr(entitlement_module.gst_lookup_repo, "count_for_tenant", lambda _tenant_id: 999)

    result = entitlement_module.resolve_gst_lookup_entitlement(uuid.uuid4())
    assert result.passed is True
    assert result.reason is None


# --- resolve_cfo_entitlement (F2 — real rewrite against docs/specs/entitlement.md) ----------

_OCCURRED_AT = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _stub_tenant_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every CFO test below stubs the tenant-timezone DB lookup so these stay true unit
    tests (no real Postgres needed) — the resolution *logic* is what's under test here, not
    the timezone query itself (that's covered by the integration suite)."""
    from backend import entitlement as entitlement_module

    monkeypatch.setattr(entitlement_module, "_tenant_timezone", lambda tenant_id: "Asia/Kolkata")


def _patch_repo(monkeypatch, **fakes):
    from backend import entitlement as entitlement_module

    for name, fn in fakes.items():
        monkeypatch.setattr(entitlement_module.entitlement_repo, name, fn)


def test_resolve_cfo_entitlement_no_cap_row_passes_as_no_cap_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """entitlement.md E1/T1/§5.5: no entitlement_cap_config row resolves at all -> today's
    real, universal state — NO_CAP_CONFIGURED, passed=True, cap_value=None."""
    _patch_repo(
        monkeypatch,
        resolve_meter_map=lambda *a, **k: None,
        resolve_cap_config=lambda *a, **k: None,
        resolve_capability_rule=lambda *a, **k: None,
        usage_count_for_period=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    result = resolve_cfo_entitlement(
        uuid.uuid4(), direct_action_code="cfo.pricing", occurred_at=_OCCURRED_AT
    )

    assert isinstance(result, EntitlementResult)
    assert result.passed is True
    assert result.evaluation_basis == "NO_CAP_CONFIGURED"
    assert result.cap_value is None
    assert result.usage_count == 0
    assert result.meter_code == "cfo.pricing"  # E5 fallback: no meter map row
    assert result.denial_rendering == "ERROR"  # rule 9 default: no capability rule row
    assert result.reduced_payload_action_code is None
    assert cfo_entitlement_check_value(result) == "PASS"


def test_resolve_cfo_entitlement_under_cap_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """T2: a resolved cap with real usage strictly under it -> UNDER_CAP, passed=True."""
    _patch_repo(
        monkeypatch,
        resolve_meter_map=lambda *a, **k: {"meter_code": "cfo.pricing"},
        resolve_cap_config=lambda *a, **k: {"cap_value": 10, "period_unit": "MONTH"},
        resolve_capability_rule=lambda *a, **k: None,
        usage_count_for_period=lambda *a, **k: 3,
    )

    result = resolve_cfo_entitlement(
        uuid.uuid4(), direct_action_code="cfo.pricing", occurred_at=_OCCURRED_AT
    )

    assert result.evaluation_basis == "UNDER_CAP"
    assert result.passed is True
    assert result.cap_value == 10
    assert result.usage_count == 3
    assert cfo_entitlement_check_value(result) == "PASS"


def test_resolve_cfo_entitlement_over_cap_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """T3: usage at or above cap_value -> OVER_CAP, passed=False."""
    _patch_repo(
        monkeypatch,
        resolve_meter_map=lambda *a, **k: {"meter_code": "cfo.pricing"},
        resolve_cap_config=lambda *a, **k: {"cap_value": 10, "period_unit": "MONTH"},
        resolve_capability_rule=lambda *a, **k: None,
        usage_count_for_period=lambda *a, **k: 10,
    )

    result = resolve_cfo_entitlement(
        uuid.uuid4(), direct_action_code="cfo.pricing", occurred_at=_OCCURRED_AT
    )

    assert result.evaluation_basis == "OVER_CAP"
    assert result.passed is False
    assert result.reason == "OVER_CAP"
    assert cfo_entitlement_check_value(result) == "DENIED"


def test_resolve_cfo_entitlement_no_capability_rule_defaults_to_error_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 9's explicit default: absence of a capability_entitlement_rule row means
    denial_rendering='ERROR', never REDUCED_PAYLOAD by absence."""
    _patch_repo(
        monkeypatch,
        resolve_meter_map=lambda *a, **k: None,
        resolve_cap_config=lambda *a, **k: None,
        resolve_capability_rule=lambda *a, **k: None,
        usage_count_for_period=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    result = resolve_cfo_entitlement(
        uuid.uuid4(), direct_action_code="cfo.reconcile", occurred_at=_OCCURRED_AT
    )

    assert result.denial_rendering == "ERROR"
    assert result.reduced_payload_action_code is None


def test_resolve_cfo_entitlement_reduced_payload_rule_is_carried_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T10/D1: a capability_entitlement_rule row naming REDUCED_PAYLOAD and a
    reduced_payload_action_code is resolved and carried through the result verbatim."""
    _patch_repo(
        monkeypatch,
        resolve_meter_map=lambda *a, **k: None,
        resolve_cap_config=lambda *a, **k: None,
        resolve_capability_rule=lambda *a, **k: {
            "denial_rendering": "REDUCED_PAYLOAD",
            "reduced_payload_action_code": "cfo.preview",
        },
        usage_count_for_period=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    result = resolve_cfo_entitlement(
        uuid.uuid4(), direct_action_code="cfo.reconcile", occurred_at=_OCCURRED_AT
    )

    assert result.denial_rendering == "REDUCED_PAYLOAD"
    assert result.reduced_payload_action_code == "cfo.preview"


def test_resolve_cfo_entitlement_meter_map_resolution_overrides_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """meter_code is resolved through metered_event_meter_map when a row exists — never the
    raw direct_action_code in that case (rule 6: never chosen inline by the calling agent)."""
    _patch_repo(
        monkeypatch,
        resolve_meter_map=lambda *a, **k: {"meter_code": "cfo.run"},
        resolve_cap_config=lambda *a, **k: None,
        resolve_capability_rule=lambda *a, **k: None,
        usage_count_for_period=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    result = resolve_cfo_entitlement(
        uuid.uuid4(), direct_action_code="cfo.pricing", occurred_at=_OCCURRED_AT
    )

    assert result.meter_code == "cfo.run"


def test_resolve_cfo_entitlement_period_key_is_a_tenant_timezone_month_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1/rule 8: period_key defaults to a MONTH bucket in the tenant's own timezone."""
    _patch_repo(
        monkeypatch,
        resolve_meter_map=lambda *a, **k: None,
        resolve_cap_config=lambda *a, **k: None,
        resolve_capability_rule=lambda *a, **k: None,
        usage_count_for_period=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    result = resolve_cfo_entitlement(
        uuid.uuid4(), direct_action_code="cfo.pricing", occurred_at=_OCCURRED_AT
    )

    assert result.period_key == "2026-09"


def test_resolve_cfo_entitlement_result_is_a_real_dataclass() -> None:
    result = EntitlementResult(
        passed=True,
        reason=None,
        meter_code="cfo.pricing",
        usage_count=0,
        cap_value=None,
        evaluation_basis="NO_CAP_CONFIGURED",
        denial_rendering="ERROR",
        reduced_payload_action_code=None,
        period_key="2026-09",
    )
    assert isinstance(result, EntitlementResult)
    assert cfo_entitlement_check_value(result) == "PASS"
