"""backend.entitlement — the CI entitlement chokepoint. No entitlement spec exists yet
(auth.md line 5), so this always passes; what's tested here is that it's a REAL per-tenant
lookup (not a bare constant) and that the PASS/DENIED mapping matches agent_run's column
contract.
"""

from __future__ import annotations

import uuid

from backend.entitlement import CiEntitlementResult, entitlement_check_value


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
