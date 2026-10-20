"""Approval workflow, pure parts (ceo-approval-workflow.md 6.2, 5.3, AC-A7): the canonical form and hash, the plan builder's refusals, constants and the config switch.

No database: a plan is built from the REAL registry with fake identities, so what is pinned here is exactly what production freezes."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend import config
from backend.auth.context import AuthContext
from backend.ceo import approval
from backend.ceo.registry import get_registry
from backend.ceo.runtime import CeoRuntime

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
HASHTAGS = {"request_key": "ceo-x", "product_name": "Steel bottle", "marketplace": "AMAZON"}
TRENDS = {"request_key": "ceo-y", "plan_digest": "a" * 64, "marketplaces": ["AMAZON"]}


def ids() -> dict:
    return {"plan_id": uuid.uuid4(), "tenant_id": uuid.uuid4(), "investigation_id": uuid.uuid4(), "requested_by": uuid.uuid4(), "expires_at": T0 + timedelta(seconds=1800)}


def ctx() -> AuthContext:
    return AuthContext(app_user_id=uuid.uuid4(), clerk_user_id="u", email_verified=True, tenant_id=uuid.uuid4(), membership_status="ACTIVE", role="OWNER", permissions={}, onboarding_state="ACTIVE")


def rt(**kw) -> CeoRuntime:
    base = dict(classifier=object(), composer=None, leg_timeout_seconds=30, max_legs=5, clock=lambda: T0, registry=get_registry())
    return CeoRuntime(**{**base, **kw})


def build(legs=None, **kw):
    return approval.build_plan(ctx(), rt(**kw.pop("rt", {})), investigation_id=uuid.uuid4(), route="ACTION", route_key="cmo.generate_hashtags", legs=legs or [("cmo.generate_hashtags", HASHTAGS)],
                               now=T0, **kw)


# ------------------------------------------------------------------------------------------------ the canonical form
def test_the_ttl_is_the_owner_decided_constant():
    assert approval.PLAN_TTL_SECONDS == 1800  # C6 / Q-A9: a constant, not a setting
    assert not hasattr(config, "ceo_plan_ttl_seconds")


def test_canonical_json_is_key_order_independent_and_compact():
    a = approval.canonical_json({"b": 1, "a": [{"y": 2, "x": 1}]})
    assert a == approval.canonical_json({"a": [{"x": 1, "y": 2}], "b": 1}) == '{"a":[{"x":1,"y":2}],"b":1}'


def test_canonical_json_normalises_uuids_and_timestamps_and_refuses_floats():
    u = uuid.uuid4()
    assert approval.canonical_json({"u": u}) == '{"u":"%s"}' % str(u).lower()
    # the same instant in two zones is one canonical timestamp
    ist = datetime(2026, 10, 12, 14, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert approval.canonical_json(ist) == approval.canonical_json(datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)) == '"2026-10-12T09:00:00.000000Z"'
    for bad in (1.5, {"x": 0.1}, Decimal("1"), {1: "k"}, datetime(2026, 1, 1), object(), {"a": {1, 2}}):
        with pytest.raises(TypeError):
            approval.canonical_json(bad)


def test_the_hash_is_stable_across_a_database_round_trip_shape():
    base = ids()
    plan = {"plan_version": 1, "legs": [{"slots": {"n": 3, "t": "x"}}]}
    h = approval.compute_hash(plan=plan, **base)
    assert h == approval.compute_hash(plan={"legs": [{"slots": {"t": "x", "n": 3}}], "plan_version": 1}, **base)  # jsonb reorders keys
    assert len(h) == 64 and h == h.lower()
    # a timestamp read back in another zone is the same instant, so the same hash
    shifted = {**base, "expires_at": base["expires_at"].astimezone(timezone(timedelta(hours=-5)))}
    assert approval.compute_hash(plan=plan, **shifted) == h


@pytest.mark.parametrize("field", ["plan_id", "tenant_id", "investigation_id", "requested_by"])
def test_the_hash_is_bound_to_every_identity(field):
    base = ids()
    plan = {"plan_version": 1}
    assert approval.compute_hash(plan=plan, **base) != approval.compute_hash(plan=plan, **{**base, field: uuid.uuid4()})  # not replayable on another plan / tenant / investigation / user


def test_the_hash_is_bound_to_the_expiry():
    base = ids()
    assert approval.compute_hash(plan={}, **base) != approval.compute_hash(plan={}, **{**base, "expires_at": base["expires_at"] + timedelta(microseconds=1)})


def test_any_material_change_to_the_plan_changes_the_hash():
    built = build()
    base = dict(plan_id=built.plan_id, tenant_id=uuid.uuid4(), investigation_id=uuid.uuid4(), requested_by=uuid.uuid4(), expires_at=built.expires_at)
    original = approval.compute_hash(plan=built.plan, **base)

    def changed(mutate):
        import copy

        p = copy.deepcopy(built.plan)
        mutate(p)
        return approval.compute_hash(plan=p, **base)

    mutations = {
        "a slot value": lambda p: p["legs"][0]["slots"].update(product_name="Other"),
        "a meter's units": lambda p: p["legs"][0]["meters"][0].update(units=2),
        "a meter code": lambda p: p["legs"][0]["meters"][0].update(meter_code="x"),
        "a destination": lambda p: p["legs"][0]["destinations"].append("Elsewhere"),
        "the leg set": lambda p: p["legs"].append(p["legs"][0]),
        "the leg order": lambda p: p["legs"].extend([{"action_key": "a"}, {"action_key": "b"}]) or p["legs"].reverse(),
        "data basis": lambda p: p["data_basis"].append({"kind": "NICHE_BRIEF", "id": "1", "as_of": "", "fingerprint": "f"}),
        "integrations": lambda p: p["integrations"].append({"code": "Tavily", "status": "AVAILABLE", "required": True}),
        "limits": lambda p: p["limits"].update(max_legs=99),
        "the route": lambda p: p.update(route="PLAYBOOK"),
        "the route key": lambda p: p.update(route_key="cmo.market_trends"),
        "the prior attempt": lambda p: p.update(prior_attempt={"plan_id": "x", "outcome": "UNKNOWN"}),
        "the summary": lambda p: p.update(summary_text="different"),
        "the version": lambda p: p.update(plan_version=2),
    }
    for what, mutate in mutations.items():
        assert changed(mutate) != original, f"changing {what} did not change the hash"


def test_the_client_value_is_only_compared_never_trusted():
    h = "a" * 64
    assert approval.hashes_match(h, h, recomputed=h)
    assert not approval.hashes_match(h, "b" * 64, recomputed=h)  # client differs
    assert not approval.hashes_match("b" * 64, h, recomputed=h)  # stored differs from the recomputation (a tampered row)
    assert not approval.hashes_match(h, "", recomputed=h)
    assert not approval.hashes_match(h, None, recomputed=h)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ the builder
def test_a_plan_is_built_by_code_from_the_registry_and_freezes_the_effects_metadata():
    built = build()
    leg = built.plan["legs"][0]
    fx = get_registry().get("cmo.generate_hashtags").effects
    assert built.plan["plan_version"] == 1 and built.plan["route"] == "ACTION" and built.plan["route_key"] == "cmo.generate_hashtags"
    assert leg["requires_approval"] is True and leg["agent"] == "CMO" and leg["external"] == fx.external.value
    assert leg["meters"] == [{"meter_code": "cmo.generate_hashtags", "units": 1}]
    assert built.plan["limits"] == {"max_legs": 5, "leg_timeout_seconds": 30}
    assert built.expires_at - built.created_at == timedelta(seconds=1800) and built.created_at == T0
    assert "Nothing has run yet" in built.plan["summary_text"] and "Steel bottle" in built.plan["summary_text"]
    assert built.plan["prior_attempt"] is None and built.plan["data_basis"] == []


def test_the_idempotency_key_of_a_metered_leg_is_derived_from_the_plan_not_from_the_caller():
    built = build()
    assert built.plan["legs"][0]["slots"]["request_key"] == f"ceo-plan-{built.plan_id}" != HASHTAGS["request_key"]


def test_the_plan_contains_no_float_and_round_trips_through_canonical_json():
    built = build()
    approval.canonical_json(built.plan)
    assert built.plan == approval._norm(built.plan)


def test_slots_with_a_float_are_refused_and_nothing_is_built():
    with pytest.raises(approval.PlanNotBuildable) as e:
        build(legs=[("cmo.generate_hashtags", {**HASHTAGS, "target_price_paise": 499.5})])
    assert e.value.code == "BAD_SLOTS"


def test_slots_the_action_refuses_are_not_frozen():
    with pytest.raises(approval.PlanNotBuildable) as e:
        build(legs=[("cmo.generate_hashtags", {**HASHTAGS, "tenant_id": str(uuid.uuid4())})])
    assert e.value.code == "BAD_SLOTS"
    with pytest.raises(approval.PlanNotBuildable):
        build(legs=[("cmo.generate_hashtags", {"marketplace": "NOWHERE", "request_key": "k"})])


def test_missing_execution_limits_fail_closed():
    for kw in ({"leg_timeout_seconds": None}, {"max_legs": None}):
        with pytest.raises(approval.PlanNotBuildable) as e:
            build(rt=kw)
        assert e.value.code == "CONFIG_MISSING"


def test_more_legs_than_the_limit_is_refused():
    with pytest.raises(approval.PlanNotBuildable) as e:
        build(legs=[("cmo.generate_hashtags", HASHTAGS)] * 2, rt={"max_legs": 1})
    assert e.value.code == "TOO_MANY_LEGS"


@pytest.fixture
def keys(monkeypatch):
    """Set / unset the provider keys. The config readers are cached, so the cache is cleared around the change (and restored afterwards)."""
    def apply(**values):
        for env, v in values.items():
            monkeypatch.delenv(env, raising=False) if v is None else monkeypatch.setenv(env, v)
        for fn in (config.tavily_api_key, config.youtube_api_key, config.google_places_api_key):
            fn.cache_clear()

    yield apply
    monkeypatch.undo()
    for fn in (config.tavily_api_key, config.youtube_api_key, config.google_places_api_key):
        fn.cache_clear()


def test_an_unconfigured_data_sending_integration_means_no_plan(keys):
    keys(TAVILY_API_KEY=None, YOUTUBE_API_KEY=None)
    with pytest.raises(approval.PlanNotBuildable) as e:
        build(legs=[("cmo.market_trends", TRENDS)])
    assert e.value.code == "INTEGRATION_UNAVAILABLE" and "Tavily" in e.value.text
    keys(TAVILY_API_KEY="k", YOUTUBE_API_KEY="k")
    built = build(legs=[("cmo.market_trends", TRENDS)])
    assert {i["code"]: i["status"] for i in built.plan["integrations"]} == {"Tavily": "AVAILABLE", "YouTube Data API": "AVAILABLE"}
    assert {i["required"] for i in built.plan["integrations"]} == {True}
    assert built.plan["legs"][0]["egress"] == ["CONFIRMED_NICHE_TERMS"]
    assert [m["meter_code"] for m in built.plan["legs"][0]["meters"]] == ["cmo.market_trends", "research.market_trends"]


def test_an_unknown_integration_label_is_unavailable_never_assumed():
    assert approval.integration_status("Some Other Service") == "UNAVAILABLE"
    assert approval.integration_status("Public GST reference pages") == "AVAILABLE"


def test_an_unclassified_action_cannot_be_planned():
    import dataclasses

    from backend.ceo.registry import ActionRegistry

    reg = get_registry()
    bare = dataclasses.replace(reg.get("cmo.generate_hashtags"), effects=None)
    with pytest.raises(approval.PlanNotBuildable) as e:
        build(legs=[("cmo.generate_hashtags", HASHTAGS)], rt={"registry": ActionRegistry([bare])})
    assert e.value.code == "UNCLASSIFIED_ACTION"


def test_a_prior_uncertain_attempt_is_part_of_the_plan_and_changes_it():
    plain = build()
    warned = build(prior_attempt={"plan_id": str(uuid.uuid4()), "outcome": "UNKNOWN"})
    assert warned.plan["prior_attempt"]["outcome"] == "UNKNOWN" and any("may already have been sent" in a for a in warned.plan["assumptions"])
    assert "may already have been sent" in warned.plan["summary_text"] and "may already" not in plain.plan["summary_text"]


# ------------------------------------------------------------------------------------------------ the switch
def test_chat_plan_creation_is_off_by_default_and_strict(monkeypatch):
    monkeypatch.delenv("CEO_APPROVAL_ENABLED", raising=False)
    assert config.ceo_approval_enabled() is False
    for on in ("true", "TRUE", "1", "yes"):
        monkeypatch.setenv("CEO_APPROVAL_ENABLED", on)
        assert config.ceo_approval_enabled() is True
    for off in ("", "false", "0", "no"):
        monkeypatch.setenv("CEO_APPROVAL_ENABLED", off)
        assert config.ceo_approval_enabled() is False
    monkeypatch.setenv("CEO_APPROVAL_ENABLED", "maybe")
    with pytest.raises(ValueError):
        config.ceo_approval_enabled()


def test_the_classifier_and_api_expose_no_way_to_approve():
    """CD11: the classifier has no approve intent and no plan-id slot; the chat turn body cannot carry an approval."""
    from backend.api.v1.ceo import TurnBody, UiActionBody
    from backend.ceo import classifier
    from backend.ceo.plans import SLOT_VOCAB

    assert not any("approv" in s or "plan" in s for s in SLOT_VOCAB)
    assert not any("approv" in f.lower() or "plan_" in f.lower() for f in TurnBody.model_fields) and not any("approv" in f.lower() for f in UiActionBody.model_fields)
    assert not any('APPROV' in r for r in classifier.ROUTES) and not any('APPROV' in r for r in classifier.UI_ACTION_ROUTES)
