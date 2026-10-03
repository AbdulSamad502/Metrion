"""Slim CMO's entitlement plumbing, no database (docs/specs/slim-cmo-agent.md §8,
entitlement.md A3 / rules 3-6): the resolvers delegate to the real F2 mechanism under the right
agent codes, the metering key is namespaced, and `record_metered_event` degrades gracefully."""

from __future__ import annotations

import logging
import uuid

import pytest

from backend import config, entitlement
from backend.auth import permissions
from backend.entitlement import (
    MARKET_TRENDS_AGENT_CODE,
    MARKET_TRENDS_EVENT_KIND,
    cmo_metering_key,
    record_metered_event,
    resolve_cmo_entitlement,
    resolve_market_trends_entitlement,
)


def test_cmo_resolver_delegates_with_the_cmo_agent_code(monkeypatch):
    seen = {}

    def fake(tenant_id, **kwargs):
        seen.update(kwargs, tenant_id=tenant_id)
        return "sentinel"

    monkeypatch.setattr(entitlement, "resolve_cfo_entitlement", fake)
    tenant = uuid.uuid4()
    assert resolve_cmo_entitlement(tenant, direct_action_code="cmo.generate_title_sets") == "sentinel"
    assert seen["agent_code"] == "CMO"
    assert seen["direct_action_code"] == "cmo.generate_title_sets"
    assert seen["tenant_id"] == tenant


def test_market_trends_resolver_uses_the_shared_meter_not_cmos(monkeypatch):
    seen = {}
    monkeypatch.setattr(entitlement, "resolve_cfo_entitlement", lambda t, **kw: seen.update(kw) or "sentinel")
    assert resolve_market_trends_entitlement(uuid.uuid4()) == "sentinel"
    assert seen["agent_code"] == MARKET_TRENDS_AGENT_CODE == "SHARED"
    assert seen["direct_action_code"] == MARKET_TRENDS_EVENT_KIND == "research.market_trends"


def test_cmo_and_trend_meters_are_distinct():
    """Two independent meters (spec §6.8.9, AC17): same event kind/agent pair must never collide."""
    assert MARKET_TRENDS_AGENT_CODE != "CMO"
    assert not MARKET_TRENDS_EVENT_KIND.startswith("cmo.")


def test_metering_key_is_namespaced_and_stable():
    generation = uuid.uuid4()
    assert cmo_metering_key(generation) == f"cmo:{generation}"
    assert cmo_metering_key(generation) == cmo_metering_key(generation)
    assert cmo_metering_key(generation) != cmo_metering_key(uuid.uuid4())


def test_record_metered_event_swallows_failures_and_logs(monkeypatch, caplog):
    """D4: an accounting failure must never block a delivered result."""

    def boom(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(entitlement.entitlement_repo, "resolve_meter_map", boom)
    with caplog.at_level(logging.ERROR, logger="backend.entitlement"):
        result = record_metered_event(
            uuid.uuid4(), agent_code="CMO", event_kind="cmo.generate_title_sets", idempotency_key="cmo:x"
        )
    assert result is None
    assert any("needs reconciliation" in rec.getMessage() for rec in caplog.records)


def test_record_metered_event_resolves_meter_and_period_before_writing(monkeypatch):
    captured = {}
    monkeypatch.setattr(entitlement.entitlement_repo, "resolve_meter_map", lambda *a, **k: {"meter_code": "mapped_meter"})
    monkeypatch.setattr(entitlement.entitlement_repo, "resolve_cap_config", lambda *a, **k: {"period_unit": "DAY"})
    monkeypatch.setattr(entitlement, "_tenant_timezone", lambda t: "Asia/Kolkata")
    monkeypatch.setattr(entitlement.entitlement_repo, "insert_metered_event", lambda t, **kw: captured.update(kw) or uuid.UUID(int=7))

    from datetime import datetime, timezone

    when = datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc)  # 01:30 on the 4th in Asia/Kolkata
    out = record_metered_event(
        uuid.uuid4(), agent_code="CMO", event_kind="cmo.generate_listing_copy",
        idempotency_key="cmo:y", occurred_at=when,
    )
    assert out == uuid.UUID(int=7)
    assert captured["meter_code"] == "mapped_meter"      # never chosen by the caller (rule 6)
    assert captured["period_key"] == "2026-10-04"        # DAY bucket in the TENANT's timezone (A1)
    assert captured["quantity"] == 1
    assert captured["idempotency_key"] == "cmo:y"


def test_record_metered_event_falls_back_to_event_kind_and_month_bucket(monkeypatch):
    captured = {}
    monkeypatch.setattr(entitlement.entitlement_repo, "resolve_meter_map", lambda *a, **k: None)
    monkeypatch.setattr(entitlement.entitlement_repo, "resolve_cap_config", lambda *a, **k: None)
    monkeypatch.setattr(entitlement, "_tenant_timezone", lambda t: "UTC")
    monkeypatch.setattr(entitlement.entitlement_repo, "insert_metered_event", lambda t, **kw: captured.update(kw) or uuid.uuid4())

    from datetime import datetime, timezone

    record_metered_event(
        uuid.uuid4(), agent_code="CMO", event_kind="cmo.generate_hashtags",
        idempotency_key="cmo:z", occurred_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )
    assert captured["meter_code"] == "cmo.generate_hashtags"  # E5 explicit 1:1 fallback
    assert captured["period_key"] == "2026-10"


# --- permission key -------------------------------------------------------------------------


def test_market_trends_key_is_in_the_grid_and_owner_holds_it_implicitly():
    key = permissions.RESEARCH_MARKET_TRENDS
    assert key == "research.market_trends"
    assert key in permissions.ALL_KEYS
    assert permissions.has_permission(role=permissions.OWNER_ROLE, permissions={}, key=key) is True


def test_market_trends_key_is_deny_by_default_for_partners_and_independent_of_agent_cmo():
    key = permissions.RESEARCH_MARKET_TRENDS
    assert permissions.has_permission(role=permissions.PARTNER_ROLE, permissions={}, key=key) is False
    only_agent = {permissions.AGENT_CMO: True}
    assert permissions.has_permission(role=permissions.PARTNER_ROLE, permissions=only_agent, key=key) is False
    assert permissions.has_permission(role=permissions.PARTNER_ROLE, permissions={key: True}, key=permissions.AGENT_CMO) is False


# --- config: no silent defaults for the decisions that are yours ----------------------------


@pytest.fixture
def fresh_config():
    for fn in (config.cmo_image_max_bytes, config.cmo_image_allowed_types, config.cmo_llm_model, config.cmo_image_storage_dir):
        fn.cache_clear()
    yield
    for fn in (config.cmo_image_max_bytes, config.cmo_image_allowed_types, config.cmo_llm_model, config.cmo_image_storage_dir):
        fn.cache_clear()


def test_image_limits_have_no_default(monkeypatch, fresh_config):
    monkeypatch.delenv("CMO_IMAGE_MAX_BYTES", raising=False)
    monkeypatch.delenv("CMO_IMAGE_ALLOWED_TYPES", raising=False)
    assert config.cmo_image_max_bytes() is None
    assert config.cmo_image_allowed_types() == frozenset()


def test_image_limits_read_from_environment(monkeypatch, fresh_config):
    monkeypatch.setenv("CMO_IMAGE_MAX_BYTES", "2048")
    monkeypatch.setenv("CMO_IMAGE_ALLOWED_TYPES", " image/JPEG , image/png ,, ")
    assert config.cmo_image_max_bytes() == 2048
    assert config.cmo_image_allowed_types() == frozenset({"image/jpeg", "image/png"})


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_non_positive_image_limit_is_a_loud_error(monkeypatch, fresh_config, bad):
    monkeypatch.setenv("CMO_IMAGE_MAX_BYTES", bad)
    with pytest.raises(ValueError, match="CMO_IMAGE_MAX_BYTES"):
        config.cmo_image_max_bytes()


def test_blank_image_limit_is_treated_as_unset(monkeypatch, fresh_config):
    monkeypatch.setenv("CMO_IMAGE_MAX_BYTES", "   ")
    assert config.cmo_image_max_bytes() is None


def test_llm_model_is_required_with_no_default_and_read_from_the_environment(monkeypatch, fresh_config):
    # P5 decision 3 (supersedes the earlier dev default): a model is an operator decision, never a hidden fallback.
    monkeypatch.delenv("CMO_LLM_MODEL", raising=False)
    with pytest.raises(config.MissingConfig):
        config.cmo_llm_model()
    monkeypatch.setenv("CMO_LLM_MODEL", "qwen3:4b")
    assert config.cmo_llm_model() == "qwen3:4b"
