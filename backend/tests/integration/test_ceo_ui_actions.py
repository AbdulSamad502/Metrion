"""B5: quick actions that skip the classifier (spec §6.26 L2, R14, C21), and the Hub's health and flow endpoints (§6.27).

A UI action is the seller choosing with a deterministic control. It must be FASTER (no classifier call) but never WEAKER: the same closed catalog
(attached ∩ permitted ∩ entitled), slot resolution, per-leg checks, choke point, gate and persistence apply. Asserted here by spying that no model
is called, and by trying to use a quick action to reach what a classified message could not.
"""

from __future__ import annotations

import os
import uuid

import pytest

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, INVESTIGATION_CREATE, INVESTIGATION_VIEW, PARTNER_ROLE
from backend.ceo import orchestrator
from backend.repositories import agent_run_repo, investigation_repo as repo
from tests.integration.ceo_support import ctx_for, partner_ctx, row_counts, save_metric, seed_platform_cap
from tests.integration.test_ceo_api import api, clerk, login, start as api_start  # noqa: F401  (fixtures + helpers)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, health_config, runtime, seed_books, start  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

UI = orchestrator.UiAction


def _spy_runtime(**kw):
    cls, comp = Scripted({}), Grounded()  # an EMPTY classifier table: any classifier call would raise KeyError and fail the turn
    return cls, comp, runtime(cls, comp, **kw)


# ------------------------------------------------------------------------------------------- faster, never weaker
def test_a_state_read_quick_action_calls_no_model_at_all(two_tenants, app_user):
    a, _ = two_tenants
    seed_books(a)
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Latest profit & loss", ui_action=UI("BUSINESS_STATE", "BS_PNL_LATEST"))
    assert (res.status, res.route, res.route_key, res.composition_mode) == ("DELIVERED", "BUSINESS_STATE", "BS_PNL_LATEST", "TEMPLATE")
    assert cls.calls == 0 and comp.calls == 0  # neither the classifier nor the composer was called
    assert "₹482,150.00" in res.answer
    turn = repo.get_turn(a, res.turn_id)
    assert turn["route_source"] == "UI_ACTION" and turn["classifier_result"]["model"] == "none (UI action)"
    stages = res.timings["stages"]
    assert "route_resolution" in stages and "classification" not in stages and "classificationModelMs" not in res.timings.get("notes", {})


def test_a_playbook_quick_action_uses_one_composition_and_no_classification(two_tenants, app_user, health_config):
    a, _ = two_tenants
    seed_books(a)
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Why did profit drop?", ui_action=UI("PLAYBOOK", "PROFIT_DIAGNOSIS", {"period": "September"}))
    assert res.status == "DELIVERED" and res.composition_mode == "LLM" and cls.calls == 0 and comp.calls == 1
    kids = agent_run_repo.list_children(a, repo.get_turn(a, res.turn_id)["agent_run_id"])
    assert sorted(k["trigger_ref"] for k in kids) == ["cfo.anomaly_check", "cfo.financial_health", "cfo.strategic_briefing"]


def test_a_missing_required_slot_is_a_clarification_with_no_model_and_no_dispatch(two_tenants, app_user):
    a, _ = two_tenants
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Why did profit drop?", ui_action=UI("PLAYBOOK", "PROFIT_DIAGNOSIS"))
    assert res.status == "CLARIFIED" and res.clarify_for == "period" and cls.calls == 0 and comp.calls == 0
    assert repo.list_findings(a, inv) == []  # nothing was dispatched, nothing defaulted


def test_the_date_picker_period_satisfies_a_quick_action(two_tenants, app_user, health_config):
    from datetime import date

    a, _ = two_tenants
    seed_books(a)
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Health check", period=(date(2026, 9, 1), date(2026, 9, 30)), ui_action=UI("ACTION", "cfo.financial_health"))
    assert res.status == "DELIVERED" and cls.calls == 0
    assert any("2026-09-01" in n for n in res.notes)  # the picked range is echoed back (AC17)


# ------------------------------------------------------------------------------------------- never weaker
def test_a_quick_action_for_a_detached_agent_is_refused_and_dispatches_nothing(two_tenants, app_user):
    a, _ = two_tenants
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    repo.set_agent_attachment(a, inv, "CFO", attached=False, changed_by=app_user)
    res = orchestrator.run_turn(ctx, rt, inv, "Health check", ui_action=UI("ACTION", "cfo.financial_health", {"period": "September"}))
    assert res.status == "DENIED" and "not available for this investigation" in res.answer
    assert repo.list_findings(a, inv) == [] and cls.calls == 0
    anchor = agent_run_repo.get_run(a, repo.get_turn(a, res.turn_id)["agent_run_id"])
    assert anchor["status"] == "DENIED" and agent_run_repo.list_children(a, anchor["id"]) == []


def test_a_quick_action_for_an_agent_the_member_lacks_is_refused(two_tenants, app_user):
    a, _ = two_tenants
    cls, comp, rt = _spy_runtime()
    owner_ctx = ctx_for(a, user_id=app_user)
    inv = start(owner_ctx, rt)
    member = partner_ctx(a, AGENT_CEO, INVESTIGATION_VIEW)  # no agent.cfo
    res = orchestrator.run_turn(member, rt, inv, "Latest profit & loss", ui_action=UI("BUSINESS_STATE", "BS_PNL_LATEST"))
    assert res.status == "DENIED" and repo.list_findings(a, inv) == []


@pytest.mark.parametrize("key", ["cfo.enter_expense", "cfo.pricing", "cmo.approve_title", "cmo.market_trends", "cfo.gst_lookup", "service.gst_lookup", "not.a.real.key", "ci.research_now"])
def test_a_quick_action_cannot_reach_anything_outside_the_closed_catalog(two_tenants, app_user, key):
    """Write-class (C21), registry-but-not-chat-supported, unwired and nonexistent keys all fail identically: nothing is dispatched."""
    a, _ = two_tenants
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    before = row_counts(a, "agent_run", "manual_adjustment", "metered_event")
    res = orchestrator.run_turn(ctx, rt, inv, "do it", ui_action=UI("ACTION", key, {"period": "September"}))
    assert res.status == "DENIED" and repo.list_findings(a, inv) == []
    after = row_counts(a, "agent_run", "manual_adjustment", "metered_event")
    assert after["manual_adjustment"] == before["manual_adjustment"] and after["metered_event"] == before["metered_event"]
    children = agent_run_repo.list_children(a, repo.get_turn(a, res.turn_id)["agent_run_id"])
    assert children == []  # not even a refused leg: the key never reached the choke point


def test_a_wrong_route_for_a_key_is_refused(two_tenants, app_user):
    a, _ = two_tenants
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "x", ui_action=UI("PLAYBOOK", "cfo.financial_health"))  # an action key under the PLAYBOOK route
    assert res.status == "CLARIFIED" and repo.list_findings(a, inv) == []


def test_a_non_executing_route_is_not_a_quick_action(two_tenants, app_user):
    a, _ = two_tenants
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "x", ui_action=UI("ADVISORY", None))
    assert res.status == "CLARIFIED" and comp.calls == 0


def test_the_ceo_cap_still_applies_to_a_quick_action(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="CEO", meter_code="ceo.chat_turn", cap_value=0)
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Latest profit & loss", ui_action=UI("BUSINESS_STATE", "BS_PNL_LATEST"))
    assert res.status == "DENIED" and repo.list_findings(a, inv) == []


def test_a_delivered_quick_action_consumes_one_ceo_unit_a_refused_one_none(two_tenants, app_user):
    a, _ = two_tenants
    seed_books(a)
    cls, comp, rt = _spy_runtime()
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, "Latest profit & loss", ui_action=UI("BUSINESS_STATE", "BS_PNL_LATEST"))
    assert row_counts(a, "metered_event") == {"metered_event": 1}
    orchestrator.run_turn(ctx, rt, inv, "do it", ui_action=UI("ACTION", "cfo.enter_expense"))
    assert row_counts(a, "metered_event") == {"metered_event": 1}


# ------------------------------------------------------------------------------------------- over HTTP
def _turn(client, headers, inv, **body):
    return client.post(f"/api/v1/ceo/investigations/{inv}/turns", json=body, headers=headers)


def test_the_http_action_body_is_strictly_validated(api):  # noqa: F811
    client, owner, _, a, _ = api
    inv = api_start(client, owner)
    bad = [
        {"message": "x", "action": {"kind": "ADVISORY"}},  # not an executing route
        {"message": "x", "action": {"kind": "ACTION"}},  # a key is required
        {"message": "x", "action": {"kind": "SYNTHESIZE", "key": "k"}},  # SYNTHESIZE takes none
        {"message": "x", "action": {"kind": "ACTION", "key": "cfo.financial_health", "slots": {"tenant_id": str(uuid.uuid4())}}},
        {"message": "x", "action": {"kind": "ACTION", "key": "cfo.financial_health", "slots": {"period": "x" * 65}}},
        {"message": "x", "action": {"kind": "ACTION", "key": "cfo.financial_health", "slots": {"sql": "DROP TABLE tenant"}}},
        {"message": "x", "action": {"kind": "ACTION", "key": "k" * 65}},
        {"message": "x", "action": "cfo.financial_health"},
    ]
    for body in bad:
        r = _turn(client, owner, inv, **body)
        assert r.status_code == 422, (body, r.status_code)
    assert repo.list_turns(a, inv) == [] and repo.list_messages(a, inv) == []


def test_a_quick_action_over_http_reports_its_route_source_and_presents_findings(api):  # noqa: F811
    client, owner, _, a, _ = api
    seed_books(a)
    inv = api_start(client, owner)
    r = _turn(client, owner, inv, message="Latest profit & loss", action={"kind": "BUSINESS_STATE", "key": "BS_PNL_LATEST"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["routeSource"], body["compositionMode"]) == ("DELIVERED", "UI_ACTION", "TEMPLATE")
    assert body["findings"][0]["presentation"]["figures"][0]["value"].startswith("₹")
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=owner).json()
    assert detail["turns"][0]["route_source"] == "UI_ACTION" and detail["findings"][0]["presentation"] == body["findings"][0]["presentation"]


def test_a_classified_message_reports_its_route_source(api):  # noqa: F811
    client, owner, _, a, _ = api
    inv = api_start(client, owner)
    r = _turn(client, owner, inv, message="hello")
    assert r.status_code == 200 and r.json()["routeSource"] == "CLASSIFIER"


# ------------------------------------------------------------------------------------------- the health strip
def test_health_strip_for_an_empty_tenant_says_why_and_shows_no_figure(api):  # noqa: F811
    client, owner, _, a, _ = api
    r = client.get("/api/v1/ceo/state/health", headers=owner)
    assert r.status_code == 200
    entries = {e["key"]: e for e in r.json()["entries"]}
    assert set(entries) == {"BS_HEALTH_BANDS", "BS_PNL_LATEST"}
    for e in entries.values():
        assert e["status"] == "UNAVAILABLE" and e["presentation"]["figures"] == [] and e["presentation"]["gaps"]  # never a zero, never a made-up band


def test_health_strip_shows_the_latest_saved_pnl_as_verified_figures(api):  # noqa: F811
    client, owner, _, a, _ = api
    seed_books(a)
    e = {x["key"]: x for x in client.get("/api/v1/ceo/state/health", headers=owner).json()["entries"]}["BS_PNL_LATEST"]
    assert e["status"] == "AVAILABLE" and e["period"] == "2026-09-01/2026-09-30" and e["asOf"]
    values = {f["label"]: f["value"] for f in e["presentation"]["figures"]}
    assert values["Contribution profit"] == "₹61,320.00"
    assert not any("score" in f["label"].lower() for f in e["presentation"]["figures"])  # CP1-U1: no composite score


def test_health_strip_never_leaks_cfo_figures_to_a_member_without_the_cfo_permission(api, clerk):  # noqa: F811
    client, owner, _, a, _ = api
    seed_books(a)
    member = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_VIEW: True})  # no agent.cfo
    r = client.get("/api/v1/ceo/state/health", headers=member)
    assert r.status_code == 200
    for e in r.json()["entries"]:
        assert e["status"] == "NOT_PERMITTED" and e["presentation"]["figures"] == [] and "61,320" not in str(e)


def test_health_strip_offers_the_preview_when_the_plan_lacks_cfo(api, migrate_engine):  # noqa: F811
    client, owner, _, a, _ = api
    seed_books(a)
    seed_platform_cap(migrate_engine, agent_code="CFO", meter_code="cfo.business_state_read", cap_value=0)
    e = client.get("/api/v1/ceo/state/health", headers=owner).json()["entries"][0]
    assert e["status"] == "NOT_ENTITLED" and e["previewHint"] == "cfo.preview" and e["presentation"]["figures"] == []


def test_health_strip_is_tenant_scoped_and_needs_both_keys(api, clerk):  # noqa: F811
    client, owner_a, owner_b, a, b = api
    seed_books(a)
    mine = {x["key"]: x for x in client.get("/api/v1/ceo/state/health", headers=owner_a).json()["entries"]}
    theirs = {x["key"]: x for x in client.get("/api/v1/ceo/state/health", headers=owner_b).json()["entries"]}
    assert mine["BS_PNL_LATEST"]["status"] == "AVAILABLE" and theirs["BS_PNL_LATEST"]["status"] == "UNAVAILABLE"
    for grid in ({AGENT_CEO: True}, {INVESTIGATION_VIEW: True}, {}):
        h = login(clerk, a, role=PARTNER_ROLE, permissions=grid)
        assert client.get("/api/v1/ceo/state/health", headers=h).status_code == 403


# ------------------------------------------------------------------------------------------- show flow
def test_show_flow_lists_the_ceo_turn_and_every_leg_it_fanned_out_to(api, health_config):  # noqa: F811
    client, owner, _, a, _ = api
    seed_books(a)
    inv = api_start(client, owner)
    t = _turn(client, owner, inv, message="Why did profit drop?", action={"kind": "PLAYBOOK", "key": "PROFIT_DIAGNOSIS", "slots": {"period": "September"}}).json()
    flow = client.get(f"/api/v1/ceo/investigations/{inv}/turns/{t['turnId']}/flow", headers=owner)
    assert flow.status_code == 200, flow.text
    body = flow.json()
    assert (body["route"], body["routeKey"], body["routeSource"], body["status"]) == ("PLAYBOOK", "PROFIT_DIAGNOSIS", "UI_ACTION", "DELIVERED")
    assert body["ceo"]["agentId"] == "CEO" and sorted(l["triggerRef"] for l in body["legs"]) == ["cfo.anomaly_check", "cfo.financial_health", "cfo.strategic_briefing"]
    assert all(l["agentId"] == "CFO" and l["status"] in ("COMPLETE", "PARTIAL") for l in body["legs"]) and "stages" in body["timings"]


def test_show_flow_includes_a_refused_leg_with_its_reason(api, migrate_engine, health_config):  # noqa: F811
    client, owner, _, a, _ = api
    seed_books(a)
    inv = api_start(client, owner)
    seed_platform_cap(migrate_engine, agent_code="CFO", meter_code="cfo.anomaly_check", cap_value=0)  # an optional leg of the playbook is refused
    t = _turn(client, owner, inv, message="Why did profit drop?", action={"kind": "PLAYBOOK", "key": "PROFIT_DIAGNOSIS", "slots": {"period": "September"}}).json()
    legs = {l["triggerRef"]: l for l in client.get(f"/api/v1/ceo/investigations/{inv}/turns/{t['turnId']}/flow", headers=owner).json()["legs"]}
    refused = legs["cfo.anomaly_check"]
    assert (refused["status"], refused["entitlementCheck"]) == ("DENIED", "DENIED:cfo.anomaly_check") and refused["reason"]
    assert legs["cfo.financial_health"]["status"] in ("COMPLETE", "PARTIAL") and legs["cfo.financial_health"]["reason"] is None


def test_show_flow_is_tenant_scoped_and_checks_the_turn_belongs_to_the_investigation(api, clerk):  # noqa: F811
    client, owner_a, owner_b, a, _ = api
    inv, other = api_start(client, owner_a), api_start(client, owner_a)
    t = _turn(client, owner_a, inv, message="hello").json()["turnId"]
    assert client.get(f"/api/v1/ceo/investigations/{inv}/turns/{t}/flow", headers=owner_b).status_code == 404  # another tenant
    assert client.get(f"/api/v1/ceo/investigations/{other}/turns/{t}/flow", headers=owner_a).status_code == 404  # right tenant, wrong investigation
    assert client.get(f"/api/v1/ceo/investigations/{inv}/turns/{uuid.uuid4()}/flow", headers=owner_a).status_code == 404
    for grid in ({AGENT_CEO: True}, {INVESTIGATION_VIEW: True}):
        h = login(clerk, a, role=PARTNER_ROLE, permissions=grid)
        assert client.get(f"/api/v1/ceo/investigations/{inv}/turns/{t}/flow", headers=h).status_code == 403
