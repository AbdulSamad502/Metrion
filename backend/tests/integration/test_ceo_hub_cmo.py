"""P8: CEO hub dispatch for Slim CMO and the GST routes (spec `ceo-agent-orchestration.md` §6.9; C4, C10, C11, AC18-20, T18-T27;
GST safety conditions G1-G7). Real Postgres, real permission/entitlement/metering code; providers and the GST fetcher/model faked."""

from __future__ import annotations

import ast
import json
import os
import pathlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from backend.agents import ceo_hub_cmo as hub
from backend.agents.ceo_hub_cmo import (
    CMO_DISPATCH_ACTIONS, CeoDispatchError, CeoPermissionDenied, GstBasis, GstEntitlementDenied, GstInputRefused, GstQuestion, GstRoute,
    dispatch_cmo, dispatch_cmo_market_trends_preview, dispatch_gst_lookup, select_gst_route,
)
from backend.api.v1 import cmo as cmo_api
from backend.auth.permissions import ALL_KEYS, OWNER_ROLE, PARTNER_ROLE

from .test_cmo_api import AMAZON, _erase_cmo_rows, _login, ctx_engine, env, fake_clerk, seed_cap, title_body  # noqa: F401
from .test_cmo_trends_api import Rt, config_rows, preview, run as run_trend  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

BASE = {"agent.ceo": True, "agent.cmo": True}
BACKEND_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "backend"


def runs(env, where="true"):
    return env.q(f"SELECT id, agent_id, trigger_ref, parent_run_id, status, permission_check, entitlement_check, error_reason FROM agent_run WHERE {where} ORDER BY started_at")


def dispatch(env, action, body, perms=None, role=PARTNER_ROLE):
    return dispatch_cmo(env.tenant, requested_by=env.user_id, role=role, permissions=BASE if perms is None else perms, action=action, body=body)


# ------------------------------------------------------------------------------ roster / registry
def test_cmo_is_connected_in_the_ceo_roster():
    from backend.api.v1.ceo_hub import _AGENT_STATUSES

    assert {a["id"]: a["status"] for a in _AGENT_STATUSES}["CMO"] == "CONNECTED"


def test_exactly_the_registered_cmo_actions_are_dispatchable_and_all_are_recommend_only():
    assert set(CMO_DISPATCH_ACTIONS) == {
        "cmo.generate_title_sets", "cmo.approve_title", "cmo.generate_listing_copy", "cmo.generate_description", "cmo.generate_bullets",
        "cmo.generate_keywords", "cmo.generate_backend_terms", "cmo.generate_hashtags", "cmo.catalog_answer", "cmo.confirm_image_hint",
        "cmo.suggest_niche_terms", "cmo.confirm_niche_terms", "cmo.market_trends",
    }
    banned = ("publish", "update_listing", "sync", "push", "write_back", "marketplace")
    assert not [a for a in CMO_DISPATCH_ACTIONS if any(b in a for b in banned)]
    for handler_name, extra in CMO_DISPATCH_ACTIONS.values():
        assert callable(getattr(cmo_api, handler_name)) and all(k in ALL_KEYS for k in extra)


def test_an_unregistered_action_is_refused_before_any_run(env):
    for action in ("cmo.publish_listing", "cfo.pnl", "cmo.suggest_title_for_me", "image.upload"):
        with pytest.raises(ValueError):
            dispatch(env, action, None)
    assert runs(env, "agent_id = 'CEO'") == []


# ------------------------------------------------------------------------------ permissions are enforced inside dispatch (G1 spirit, C8)
@pytest.mark.parametrize("action", sorted(CMO_DISPATCH_ACTIONS))
def test_every_cmo_action_needs_agent_ceo_and_agent_cmo_and_a_denial_is_audited_with_no_side_effects(env, action):
    for perms in ({"agent.cmo": True}, {"agent.ceo": True}, {}):
        with pytest.raises(CeoPermissionDenied) as err:
            dispatch(env, action, None, perms)
        assert "agent.ceo" in err.value.missing or "agent.cmo" in err.value.missing
    rows = runs(env, "agent_id = 'CEO'")
    assert len(rows) == 3 and all(r[4] == "DENIED" and r[5] == "DENIED" and r[2] == f"ceo_hub.{action}" for r in rows)
    assert env.n("cmo_generation") == 0 and env.provider.calls == 0 and env.events() == [] and runs(env, "agent_id = 'CMO'") == []


def test_actions_with_an_extra_key_need_it_too(env):
    for action, extra in (("cmo.suggest_niche_terms", "catalog.view"), ("cmo.market_trends", "research.market_trends")):
        with pytest.raises(CeoPermissionDenied) as err:
            dispatch(env, action, None, BASE)
        assert extra in err.value.missing
        with pytest.raises(CeoPermissionDenied):
            dispatch(env, action, None, {**BASE, "files.view": True})  # files.view is not a substitute for catalog.view


def test_owner_holds_every_permission_implicitly(env):
    r = dispatch(env, "cmo.generate_title_sets", cmo_api.TitleSetsBody(**title_body("o1")), {}, role=OWNER_ROLE)
    assert r.payload["runStatus"] and env.n("cmo_generation") == 1


# ------------------------------------------------------------------------------ one call = one action, parent/child linkage, billing unchanged
def test_a_dispatched_action_links_the_cmo_run_to_the_ceo_turn_and_bills_exactly_like_the_direct_path(env):
    r = dispatch(env, "cmo.generate_title_sets", cmo_api.TitleSetsBody(**title_body("d1")))
    ceo = runs(env, "agent_id = 'CEO'")
    cmo = runs(env, "agent_id = 'CMO'")
    assert len(ceo) == 1 and ceo[0][0] == r.ceo_agent_run_id and ceo[0][4] == "COMPLETE" and ceo[0][2] == "ceo_hub.cmo.generate_title_sets"
    assert ceo[0][5] == "PASS" and ceo[0][6] == "NOT_EVALUATED" and ceo[0][3] is None  # the CEO turn unit (D5) is not modelled: stated, not faked
    assert len(cmo) == 1 and cmo[0][2] == "cmo.generate_title_sets" and cmo[0][3] == r.ceo_agent_run_id
    assert len(env.events()) == 1 and r.payload["unitsBilled"] == 1  # one artefact, one CMO unit; nothing extra for the dispatch


def test_a_direct_path_call_has_no_parent_run(env):
    assert env.post("title-sets", title_body("direct1")).status_code == 200
    assert runs(env, "agent_id = 'CMO'")[0][3] is None


def test_the_parent_link_does_not_leak_into_the_next_direct_call(env):
    dispatch(env, "cmo.generate_title_sets", cmo_api.TitleSetsBody(**title_body("p1")))
    env.post("title-sets", title_body("p2"))
    parents = [r[3] for r in runs(env, "agent_id = 'CMO'")]
    assert parents[0] is not None and parents[1] is None


def test_quota_denial_through_dispatch_is_a_402_failed_ceo_turn_with_nothing_delivered(env):
    seed_cap(env.engine, "cmo.generate_title_sets", 0)
    with pytest.raises(CeoDispatchError) as err:
        dispatch(env, "cmo.generate_title_sets", cmo_api.TitleSetsBody(**title_body("q1")))
    assert err.value.status_code == 402
    ceo = runs(env, "agent_id = 'CEO'")
    assert ceo[0][4] == "FAILED" and ceo[0][7] == "402"
    assert env.n("cmo_generation") == 0 and env.events() == [] and env.provider.calls == 0


def test_approve_title_needs_an_explicit_option_or_the_sellers_own_text_ceo_cannot_choose(env):
    ts = dispatch(env, "cmo.generate_title_sets", cmo_api.TitleSetsBody(**title_body("a1"))).payload
    gen = ts["artefacts"][0]["id"]
    with pytest.raises(CeoDispatchError) as err:
        dispatch(env, "cmo.approve_title", cmo_api.ApprovalBody(generation_id=gen))  # neither an option nor edited text: no default pick
    assert err.value.status_code == 422 and env.n("cmo_title_approval") == 0
    opt = ts["artefacts"][0]["options"][1]["id"]
    ok = dispatch(env, "cmo.approve_title", cmo_api.ApprovalBody(generation_id=gen, option_id=uuid.UUID(opt)))
    assert ok.payload["unitsBilled"] == 0 and env.n("cmo_title_approval") == 1


def test_request_bodies_are_the_declared_models_so_nothing_extra_can_ride_along(env):
    for extra in ({"tenant_id": str(uuid.uuid4())}, {"sales_report": "all my orders"}, {"customer_emails": ["a@b.c"]}, {"cost_price": 120}):
        with pytest.raises(ValidationError):
            cmo_api.TitleSetsBody(**title_body("x"), **extra)
        with pytest.raises(ValidationError):
            cmo_api.TrendRunBody(request_key="k", plan_digest="a" * 64, **extra)  # T25/E19: no way to include a sales report in research


# ------------------------------------------------------------------------------ the trend workflow, as separate single-action turns (T23, AC18)
def test_trend_workflow_suggest_confirm_preview_run_are_four_separate_turns(env, tmp_path):
    config_rows(env)
    rt = Rt(env)
    rt.install()
    full = {**BASE, "catalog.view": True, "research.market_trends": True}
    with env.cengine.begin() as conn:  # a tiny catalog so there is something to suggest
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
    s = dispatch(env, "cmo.suggest_niche_terms", None, full)
    assert s.payload["status"] in ("OK", "UNAVAILABLE") and rt.tavily.calls == [] and rt.youtube.calls == []  # AC18: suggesting sends nothing
    c = dispatch(env, "cmo.confirm_niche_terms", cmo_api.NicheConfirmBody(new_terms=["steel water bottle"]), full)
    assert [t["term"] for t in c.payload["confirmed"]] == ["steel water bottle"] and rt.tavily.calls == []
    pv = dispatch_cmo_market_trends_preview(env.tenant, requested_by=env.user_id, role=PARTNER_ROLE, permissions=full, body=cmo_api.TrendPreviewBody())
    assert any("steel water bottle" in q["query"] for q in pv.payload["queries"]) and rt.tavily.calls == []  # the exact queries are shown first
    done = dispatch(env, "cmo.market_trends", cmo_api.TrendRunBody(request_key="w1", plan_digest=pv.payload["digest"]), full)
    assert done.payload["status"] == "COMPLETE" and done.payload["unitsBilled"] == {"cmo": 1, "shared": 1}
    ceo_rows = runs(env, "agent_id = 'CEO'")
    assert [r[2] for r in ceo_rows] == ["ceo_hub.cmo.suggest_niche_terms", "ceo_hub.cmo.confirm_niche_terms", "ceo_hub.cmo.market_trends.preview", "ceo_hub.cmo.market_trends"]
    trend_run = runs(env, "trigger_ref = 'cmo.market_trends'")
    assert trend_run[0][3] == done.ceo_agent_run_id  # the report's own run is a child of the CEO turn
    sent = {c["query"] for c in rt.tavily.calls + rt.youtube.calls}
    assert sent == {q["query"] for q in pv.payload["queries"]}  # exactly what the seller was shown: fixed templates + the confirmed term


def test_a_stale_preview_digest_through_dispatch_is_a_409_and_nothing_is_sent(env):
    config_rows(env)
    rt = Rt(env)
    rt.install()
    full = {**BASE, "research.market_trends": True}
    dispatch(env, "cmo.confirm_niche_terms", cmo_api.NicheConfirmBody(new_terms=["steel water bottle"]), full)
    pv = dispatch_cmo_market_trends_preview(env.tenant, requested_by=env.user_id, role=PARTNER_ROLE, permissions=full, body=cmo_api.TrendPreviewBody())
    dispatch(env, "cmo.confirm_niche_terms", cmo_api.NicheConfirmBody(new_terms=["added later"]), full)
    with pytest.raises(CeoDispatchError) as err:
        dispatch(env, "cmo.market_trends", cmo_api.TrendRunBody(request_key="w2", plan_digest=pv.payload["digest"]), full)
    assert err.value.status_code == 409 and rt.tavily.calls == [] and env.n("cmo_generation") == 0


def test_missing_trend_config_is_relayed_as_config_missing_with_no_unit_and_no_call_E21(env):
    config_rows(env, drop=("news_window_days",))
    rt = Rt(env)
    rt.install()
    full = {**BASE, "research.market_trends": True}
    with pytest.raises(CeoDispatchError) as err:
        dispatch(env, "cmo.market_trends", cmo_api.TrendRunBody(request_key="w3", plan_digest="a" * 64), full)
    assert err.value.status_code == 503 and err.value.detail["code"] == "CONFIG_MISSING" and "news_window_days" in err.value.detail["missing"]
    assert rt.tavily.calls == [] and env.events() == [] and env.reservations() == []


# ------------------------------------------------------------------------------ star topology (C4, C6)
def _imports(path: pathlib.Path, *, top_level_only: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = tree.body if top_level_only else list(ast.walk(tree))
    out: set[str] = set()
    for n in nodes:
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


def test_cmo_code_never_imports_cfo_pi_or_ci_and_the_hub_imports_them_only_inside_the_gst_function():
    forbidden = ("cfo", "product_intelligence", "competitor_intelligence")
    for f in ("services/cmo_actions.py", "services/cmo_trends.py", "services/cmo_runtime.py", "services/cmo_images.py", "api/v1/cmo.py"):
        mods = _imports(BACKEND_SRC / f, top_level_only=False)
        assert not [m for m in mods if any(m == k or m.startswith(k + ".") or m.startswith("backend.services.cfo") or m.startswith("backend.api.v1.cfo") for k in forbidden)], f
    hub_top = _imports(BACKEND_SRC / "agents/ceo_hub_cmo.py", top_level_only=True)
    assert not [m for m in hub_top if "cfo" in m or "product_intelligence" in m or "competitor_intelligence" in m]


def test_the_hub_never_touches_the_calculation_acceptance_path():
    src = (BACKEND_SRC / "agents/ceo_hub_cmo.py").read_text(encoding="utf-8")
    code_names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    assert not {"accept_gst_lookup_result", "gst_rate_override", "manual_adjustment", "AcceptGstLookupRequest"} & code_names  # G4 by omission


# ------------------------------------------------------------------------------ GST (C4/C11, G1-G7, T18/T18b/T19)
ONLY_B = {"agent.ceo": True, "service.gst_lookup": True}
ROUTE_A = {"agent.ceo": True, "agent.cfo": True, "service.gst_lookup": True}


def fake_result(rate="18", status="PROVISIONAL"):
    return SimpleNamespace(
        id=uuid.uuid4(), query_text="Steel water bottle", sku=None, query_hsn=None, likely_rate_pct=Decimal(rate), likely_hsn="7323",
        likely_category="Steel table, kitchen or other household articles", ambiguity_note="Rate depends on exact classification.",
        alternatives=[{"rate_pct": Decimal("12"), "hsn": "7323", "category": "Other"}], source_url="https://cbic.example.gov.in/rates", source_title="Rate schedule",
        retrieved_at=datetime(2026, 10, 4, tzinfo=UTC), status=status, disclaimer="Provisional; confirm with your CA.",
    )


class Lookup:
    def __init__(self, result=None, no_match=None, boom=False):
        self.calls, self.result, self.no_match, self.boom = [], result if result is not None else fake_result(), no_match, boom

    def __call__(self, tenant_id, request):
        self.calls.append(request)
        if self.boom:
            raise RuntimeError("fetch failed")
        return SimpleNamespace(result=None if self.no_match else self.result, no_match=self.no_match, from_cache=False)


def gst(env, perms, question=None, lookup=None, role=PARTNER_ROLE):
    q = question or GstQuestion("Steel water bottle", GstBasis.SELLER_PROVIDED, "kitchenware", GstBasis.SELLER_PROVIDED)
    return dispatch_gst_lookup(env.tenant, requested_by=env.user_id, role=role, permissions=perms, question=q, lookup=lookup)


def test_the_route_is_chosen_by_permissions_only():
    assert select_gst_route(PARTNER_ROLE, ROUTE_A) is GstRoute.A_CFO
    assert select_gst_route(PARTNER_ROLE, ONLY_B) is GstRoute.B_SHARED
    assert select_gst_route(PARTNER_ROLE, {"agent.ceo": True, "agent.cfo": True}) is None  # CFO alone, no service key: the wall
    assert select_gst_route(PARTNER_ROLE, {"service.gst_lookup": True, "agent.cfo": True}) is None  # no agent.ceo
    assert select_gst_route(OWNER_ROLE, {}) is GstRoute.A_CFO


def test_T18_route_a_delegates_to_cfo_lookup_with_basis_labels_and_never_invokes_cmo(env):
    lk = Lookup()
    out = gst(env, ROUTE_A, lookup=lk)
    assert out.route is GstRoute.A_CFO and len(lk.calls) == 1 and lk.calls[0].product_title == "Steel water bottle" and lk.calls[0].category == "kitchenware"
    assert out.result["likelyRatePct"] == "18" and out.result["status"] == "PROVISIONAL" and out.result["sourceUrl"] and out.result["retrievedAt"] and out.result["disclaimer"]
    assert out.result["ambiguityNote"] and out.result["alternatives"]
    assert env.n("cmo_generation") == 0 and env.provider.calls == 0 and runs(env, "agent_id = 'CMO'") == []


def test_T18b_route_b_is_provisional_only_and_consumes_only_the_shared_gst_meter(env):
    with env.engine.begin() as conn:  # a CFO cap of zero must not matter: Route B never touches the CFO meter (G2)
        conn.execute(text("INSERT INTO entitlement_cap_config (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version) "
                          "VALUES (:id, NULL, 'CFO', 'cfo.gst_lookup', 'TENANT', 'MONTH', 0, '2026-01-01', 1)"), {"id": str(uuid.uuid4())})
    out = gst(env, ONLY_B, lookup=Lookup())
    assert out.route is GstRoute.B_SHARED and out.result["status"] == "PROVISIONAL"
    assert env.events() == [] and env.n("cmo_generation") == 0  # no CFO, CMO or CEO-extra unit recorded
    with pytest.raises(GstEntitlementDenied) as err:
        gst(env, ROUTE_A, lookup=Lookup())  # Route A does check CFO's own cap
    assert err.value.service == "cfo"


def test_T19_without_service_gst_lookup_the_wall_stands_and_no_lookup_or_model_knowledge_answer_exists(env):
    lk = Lookup()
    for perms in ({"agent.ceo": True}, {"agent.ceo": True, "agent.cfo": True}, {"agent.ceo": True, "agent.cmo": True}, {"service.gst_lookup": True}, {}):
        with pytest.raises(CeoPermissionDenied):
            gst(env, perms, lookup=lk)
    assert lk.calls == []
    rows = runs(env, "agent_id = 'CEO'")
    assert len(rows) == 5 and all(r[4] == "DENIED" and r[5] == "DENIED" for r in rows)


def test_G2_an_exhausted_shared_gst_meter_is_an_entitlement_denial_on_both_routes(env, monkeypatch):
    monkeypatch.setattr(hub, "resolve_gst_lookup_entitlement", lambda t: SimpleNamespace(passed=False, reason="GST cap reached", gst_lookup_count=9))
    for perms in (ROUTE_A, ONLY_B):
        lk = Lookup()
        with pytest.raises(GstEntitlementDenied) as err:
            gst(env, perms, lookup=lk)
        assert err.value.service == "gst_lookup" and lk.calls == []
    assert {r[4] for r in runs(env, "agent_id = 'CEO'")} == {"FAILED"}


def test_G3_a_route_b_result_is_never_verified_and_carries_source_date_ambiguity_and_disclaimer(env):
    out = gst(env, ONLY_B, lookup=Lookup())
    assert out.result["status"] == "PROVISIONAL" and out.result["status"] != "SELLER_VERIFIED"
    for field in ("sourceUrl", "sourceTitle", "retrievedAt", "ambiguityNote", "alternatives", "disclaimer", "likelyRatePct"):
        assert out.result[field]
    with pytest.raises(RuntimeError):
        gst(env, ONLY_B, lookup=Lookup(result=fake_result(status="SELLER_VERIFIED")))  # defensive: Route B cannot present a verified result


def test_G4_a_member_without_cfo_and_financials_adjust_cannot_turn_a_route_b_result_into_an_override(env):
    out = gst(env, ONLY_B, lookup=Lookup())
    rid = out.result["id"]
    body = {"gst_lookup_result_id": rid, "sku": "SKU1"}
    from fastapi.testclient import TestClient

    from backend.main import app

    c = TestClient(app)
    only_b, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions=ONLY_B)
    cfo_no_adjust, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cfo": True, "service.gst_lookup": True})
    assert c.post("/api/v1/cfo/gst-lookup/accept", json=body, headers=only_b).status_code == 403  # no agent.cfo
    r = c.post("/api/v1/cfo/gst-lookup/accept", json=body, headers=cfo_no_adjust)
    assert r.status_code == 403  # no financials.adjust
    assert env.n("manual_adjustment") == 0


def test_G5_the_result_contains_only_the_lookup_result_nothing_from_cfo_analysis_or_seller_financials(env):
    out = gst(env, ONLY_B, lookup=Lookup())
    assert set(out.result) == {"id", "queryText", "sku", "queryHsn", "likelyRatePct", "likelyHsn", "likelyCategory", "ambiguityNote", "alternatives",
                               "sourceUrl", "sourceTitle", "retrievedAt", "status", "disclaimer"}
    assert out.no_match is None and "pnl" not in json.dumps(out.result).lower()


def test_G6_an_unverified_image_hint_is_never_passed_as_a_category_and_estimates_are_flagged(env):
    lk = Lookup()
    out = gst(env, ONLY_B, GstQuestion("Steel water bottle", GstBasis.SELLER_PROVIDED, "drinkware", GstBasis.UNVERIFIED_HINT), lk)
    assert lk.calls[0].category is None and any("unverified image hint" in n for n in out.uncertainty_notes)
    lk2 = Lookup()
    out2 = gst(env, ONLY_B, GstQuestion("Steel water bottle", GstBasis.SELLER_PROVIDED, "drinkware", GstBasis.ESTIMATED), lk2)
    assert lk2.calls[0].category == "drinkware" and any("estimate" in n for n in out2.uncertainty_notes)
    lk3 = Lookup()
    out3 = gst(env, ONLY_B, GstQuestion("Steel water bottle", GstBasis.SELLER_PROVIDED, "drinkware", None), lk3)
    assert lk3.calls[0].category is None  # a category with no stated basis is not trusted either
    with pytest.raises(GstInputRefused):
        gst(env, ONLY_B, GstQuestion("a bottle", GstBasis.UNVERIFIED_HINT), Lookup())
    with pytest.raises(GstInputRefused):
        gst(env, ONLY_B, GstQuestion("   ", GstBasis.SELLER_PROVIDED), Lookup())


def test_G7_every_lookup_writes_a_child_agent_run_under_the_ceo_turn(env):
    b = gst(env, ONLY_B, lookup=Lookup())
    a = gst(env, ROUTE_A, lookup=Lookup())
    rows = {r[0]: r for r in runs(env)}
    for out, ref, agent in ((b, "service.gst_lookup", "CEO"), (a, "cfo.gst_lookup", "CFO")):
        child, ceo = rows[out.lookup_agent_run_id], rows[out.ceo_agent_run_id]
        assert child[2] == ref and child[1] == agent and child[3] == out.ceo_agent_run_id and child[4] == "COMPLETE"
        assert ceo[2] == "ceo_hub.gst_lookup" and ceo[1] == "CEO" and ceo[3] is None and ceo[4] == "COMPLETE"


def test_a_failed_lookup_fails_both_runs_and_raises(env):
    with pytest.raises(RuntimeError):
        gst(env, ONLY_B, lookup=Lookup(boom=True))
    assert {r[4] for r in runs(env)} == {"FAILED"}


def test_no_match_is_reported_as_no_match_never_as_a_guessed_rate(env):
    nm = SimpleNamespace(query_text="x", attempted_urls=["https://a.example"], reason="no reliable source")
    out = gst(env, ONLY_B, lookup=Lookup(no_match=nm))
    assert out.result is None and out.no_match["reason"] == "no reliable source"


def test_cmo_never_answers_gst_there_is_no_cmo_gst_dispatch_or_route():
    assert not [a for a in CMO_DISPATCH_ACTIONS if "gst" in a]
    assert not [r.path for r in cmo_api.router.routes if "gst" in r.path]  # type: ignore[attr-defined]
