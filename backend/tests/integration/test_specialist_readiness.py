"""Task 4 — specialist readiness for CEO testing. Drives EVERY action of the REAL registry through the REAL choke point (`ceo.dispatch.dispatch`) against a
real Postgres, as the CEO would, with the REAL `AuthContext`. No model, network, marketplace or paid call is made: approval-gated actions are refused before
their handler runs, and the one model-bearing action that is not approval-gated (GST lookup) gets a fake provider.

What this proves is the CALLER-VISIBLE CONTRACT (status, denial, run rows, persistence, isolation); each specialist's own arithmetic is proven by its package tests."""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.ceo import orchestrator  # noqa: F401  (import order: the registry must be importable the way production imports it)
from backend.ceo.contract import ActionSpec, Denial, InvalidSlots, LegStatus, UnregisteredAction
from backend.ceo.dispatch import dispatch, open_turn
from backend.ceo.effects import ACTION_EFFECTS
from backend.ceo.plans import ACTIONS, PLAYBOOK_LEG_SLOTS
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import agent_run_repo, investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for, partner_ctx, row_counts

D = {"period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01"}
REG = get_registry()
WIRED = tuple(s.key for s in REG.specs() if s.wired)
APPROVAL_GATED = tuple(k for k in WIRED if ACTION_EFFECTS[k].requires_approval)


def _open(tenant, user, ctx, *, attached=ALL_AGENTS):
    inv = repo.create_investigation(tenant, created_by=user, attached_agents=tuple(attached), detached_agents=(), now=T0)
    msg = repo.append_message(tenant, inv, role="USER", content="readiness", created_by=user, now=T0)
    turn = open_turn(ctx, investigation_id=inv, now=T0)
    turn.turn_id = repo.create_turn(tenant, inv, user_message_id=msg, agent_run_id=turn.anchor_run_id, route="ACTION", route_key="x", now=T0)
    return inv, turn


def _count(tenant, table):
    with tenant_scope(tenant) as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


# ------------------------------------------------------------------------------------------------ inventory pins
def test_inventory_is_exactly_what_the_report_states():
    assert len(REG.specs()) == 49 and len(WIRED) == 48  # +1 cfo.query (CFO 2.0 planner), wired
    assert [s.key for s in REG.specs() if not s.wired] == ["ci.research_now"]  # intentionally unwired; must stay so
    assert set(APPROVAL_GATED) == {
        "pi.discover", "pi.supplier_lookup", "ci.discover_competitors", "cmo.generate_title_sets", "cmo.generate_listing_copy", "cmo.generate_description", "cmo.generate_bullets",
        "cmo.generate_keywords", "cmo.generate_backend_terms", "cmo.generate_hashtags", "cmo.catalog_answer", "cmo.market_trends", "cmo.analyze_attachment",
    }


def test_every_ceo_plan_and_playbook_leg_names_a_wired_registered_action():
    planned = {k for k in ACTIONS if k != "gst_lookup"} | {k for _, k in PLAYBOOK_LEG_SLOTS} | {"cfo.gst_lookup", "service.gst_lookup"}
    for key in planned:
        assert key in REG and REG.get(key).wired, key


def test_research_now_stays_unwired_and_refuses_if_forced(two_tenants, app_user):
    a, _ = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    before = _count(a, "agent_run")
    leg = dispatch(turn, "ci.research_now", {"image_refs": ["x"]}, now=T0)
    assert (leg.status, leg.denial, leg.payload) == (LegStatus.UNAVAILABLE, Denial.NOT_WIRED, None)
    assert _count(a, "agent_run") == before + 1  # exactly the logged refusal; nothing ran
    assert "ci.research_now" not in REG.catalog_for(ctx_for(a), attached=ALL_AGENTS)


# ------------------------------------------------------------------------------------------------ every action: authorization at the choke point
@pytest.mark.parametrize("key", [k for k in WIRED if k not in APPROVAL_GATED])
def test_a_member_without_the_specialists_own_key_is_refused_and_nothing_runs(key, two_tenants, app_user):
    a, _ = two_tenants
    from backend.auth.permissions import AGENT_CEO, INVESTIGATION_VIEW

    _, turn = _open(a, app_user, partner_ctx(a, AGENT_CEO, INVESTIGATION_VIEW))  # agent.ceo only
    before = row_counts(a, "metric_result", "agent_data_request", "metered_event")
    leg = dispatch(turn, key, {}, now=T0)
    assert leg.status is LegStatus.DENIED and leg.denial is Denial.PERMISSION and leg.payload is None
    assert row_counts(a, "metric_result", "agent_data_request", "metered_event") == before


@pytest.mark.parametrize("key", [k for k in WIRED if REG.get(k).agent is not None and k not in APPROVAL_GATED])
def test_an_unattached_agent_is_refused_for_every_action(key, two_tenants, app_user):
    a, _ = two_tenants
    agent = REG.get(key).agent.value
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user), attached=ALL_AGENTS - {agent})
    leg = dispatch(turn, key, {}, now=T0)
    assert leg.denial is Denial.NOT_ATTACHED and leg.payload is None


@pytest.mark.parametrize("key", APPROVAL_GATED)
def test_metered_and_seller_data_out_actions_never_reach_their_handler(key, two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    spec = REG.get(key)

    def boom(*_a, **_k):  # a handler that runs would call a model, a search provider or a meter
        raise AssertionError(f"{key} handler was invoked")

    guarded = ActionRegistry([replace(spec, invoke=boom)])
    before = row_counts(a, "metered_event", "agent_run")
    leg = dispatch(turn, key, {}, registry=guarded, now=T0)
    assert leg.status is LegStatus.DENIED and leg.denial is Denial.APPROVAL_REQUIRED
    after = row_counts(a, "metered_event", "agent_run")
    assert after["metered_event"] == before["metered_event"] and after["agent_run"] == before["agent_run"] + 1  # only the DENIED child row


@pytest.mark.parametrize("name", ["tenant_id", "tenantId", "requested_by", "permissions", "role", "entitlement_check"])
@pytest.mark.parametrize("key", [k for k in WIRED if REG.get(k).slot_model is not None and k not in APPROVAL_GATED])
def test_identity_cannot_be_smuggled_through_any_slot(key, name, two_tenants, app_user):
    a, b = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    before = row_counts(a, "metric_result", "agent_data_request")
    with pytest.raises(InvalidSlots):
        dispatch(turn, key, {name: str(b)}, now=T0)
    assert row_counts(a, "metric_result", "agent_data_request") == before
    assert row_counts(b, "metric_result", "agent_data_request") == {"metric_result": 0, "agent_data_request": 0}


def test_an_unregistered_or_write_class_key_is_never_dispatchable(two_tenants, app_user):
    a, _ = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    for key in ("cfo.enter_expense", "cfo.ingest", "ci.competitor_url_create", "cmo.image_upload", "cfo.nope", "", "CFO.FINANCIAL_HEALTH"):
        with pytest.raises(UnregisteredAction):
            dispatch(turn, key, {}, now=T0)


# ------------------------------------------------------------------------------------------------ honest results on an empty tenant (missing input is not zero)
def test_cfo_reads_on_an_empty_tenant_say_unavailable_and_never_invent_a_value(two_tenants, app_user):
    a, _ = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))

    health = dispatch(turn, "cfo.financial_health", D, now=T0)
    assert health.status is LegStatus.COMPLETE and health.payload["overallBand"] is None and health.payload["perMetricBands"] == {} and health.payload["unavailableReason"]

    cash = dispatch(turn, "cfo.cash_reconciliation", {**D, "marketplace": "FLIPKART"}, now=T0)
    for field in ("cashReceived", "cashExpected", "cashVariance"):
        metric = cash.payload[field]
        assert metric["isAvailable"] is False and metric["valuePaise"] is None and metric["unavailableReason"]  # not 0
        assert metric["engineResultRef"]  # and it is traceable

    anomaly = dispatch(turn, "cfo.anomaly_check", {**D, "target_ref": str(a), "include_narration": False}, now=T0)
    assert anomaly.payload["seriesLength"] == 0 and all(m["flag"] is None for m in anomaly.payload["methods"])  # no flag from no data

    brief = dispatch(turn, "cfo.strategic_briefing", D, now=T0)
    assert brief.payload["signals"] == [] and brief.payload["narrative"] is None  # CEO composes; CFO never narrates a second time

    recon = dispatch(turn, "cfo.reconcile", {**D, "marketplace": "FLIPKART"}, now=T0)
    assert recon.payload["findings"] == [] and recon.payload["matchCount"] == 0 and recon.payload["exceptionCount"] == 0


def test_a_missing_supplier_quote_is_a_data_request_not_a_guess(two_tenants, app_user):
    a, _ = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    before = _count(a, "agent_data_request")
    landed = dispatch(turn, "cfo.landed_cost", {"sku": "S1", "supplier_quote_target_type": "SKU", "supplier_quote_target_ref": "S1", "quantity": 10, "as_of_date": "2026-10-01"}, now=T0)
    assert landed.status is LegStatus.PARTIAL and landed.payload["result"] is None and landed.payload["dataRequestId"]
    ranking = dispatch(turn, "cfo.supplier_ranking", {"sku": "S1", "quantity": 10, "as_of_date": "2026-10-01"}, now=T0)
    assert ranking.status is LegStatus.PARTIAL and ranking.payload["ranked"] in ([], None) and ranking.payload["dataRequestId"]
    assert _count(a, "agent_data_request") == before + 2


def test_specialists_with_nothing_to_report_are_unavailable_legs_not_errors(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    for key, slots in (
        ("pi.report", {"run_id": str(uuid.uuid4())}),
        ("ci.request_price_scenario", {"competitor_url_id": str(uuid.uuid4()), "seller_price_paise": 49900}),
    ):
        leg = dispatch(turn, key, slots, now=T0)
        assert leg.status is LegStatus.UNAVAILABLE and leg.reason == "unavailable" and leg.payload is None, key
    # every leg left a settled child row (none stuck RUNNING) and a finding
    children = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert len(children) == 2 and all(c["status"] == "FAILED" and c["finished_at"] is not None for c in children)
    assert len(repo.list_findings(a, inv, turn_id=turn.turn_id)) == 2
    # the competitor search sends the seller's product terms to a search provider, so it is approval-gated: without an approved plan it is refused, never run, never "unavailable"
    refused = dispatch(turn, "ci.discover_competitors", {"product_id": "NO-SUCH-PRODUCT"}, now=T0)
    assert refused.status is LegStatus.DENIED and refused.denial is Denial.APPROVAL_REQUIRED and refused.payload is None


# ------------------------------------------------------------------------------------------------ cross-tenant / forged ids
def test_another_tenants_real_ids_resolve_to_nothing_but_work_for_their_owner(two_tenants, app_user):
    from competitor_intelligence.repositories import competitor_url_repo
    from competitor_intelligence.types import Marketplace
    from product_intelligence.repositories import niche_brief_repo, pi_research_run_repo

    a, b = two_tenants
    brief = niche_brief_repo.create_draft(a, created_by=app_user, category_text="steel water bottle")
    run_id = pi_research_run_repo.create_run(a, niche_brief_id=brief, depth="SHALLOW", trigger="DIRECT_UI", candidate_cap=5)
    url_id = competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url="https://www.amazon.in/dp/B000TEST01", added_by=app_user, label="Rival")

    _, turn_a = _open(a, app_user, ctx_for(a, user_id=app_user))
    _, turn_b = _open(b, app_user, ctx_for(b, user_id=app_user))
    forged = (("pi.report", {"run_id": str(run_id)}), ("ci.request_price_scenario", {"competitor_url_id": str(url_id), "seller_price_paise": 1000}))
    for key, slots in forged:
        leg = dispatch(turn_b, key, slots, now=T0)
        assert leg.status is LegStatus.UNAVAILABLE and leg.payload is None, key  # indistinguishable from "does not exist"
    # the owner's identical call is not unavailable for the same reason (the id is real for them)
    own = dispatch(turn_a, "ci.request_price_scenario", dict(forged[1][1]), now=T0)
    assert own.status is LegStatus.COMPLETE and own.payload["pricePositioning"][0]["isAvailable"] is False  # real id works for its owner; no prices -> UNAVAILABLE, not 0
    assert row_counts(b, "agent_run")["agent_run"] >= 3  # tenant B only wrote its own anchor and refusal rows


def test_derived_results_land_in_the_callers_tenant_only(two_tenants, app_user):
    a, b = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    dispatch(turn, "cfo.cash_reconciliation", {**D, "marketplace": "FLIPKART"}, now=T0)
    dispatch(turn, "cfo.reconcile", {**D, "marketplace": "FLIPKART"}, now=T0)
    assert _count(a, "metric_result") > 0
    assert row_counts(b, "metric_result", "agent_data_request", "agent_run") == {"metric_result": 0, "agent_data_request": 0, "agent_run": 0}


# ------------------------------------------------------------------------------------------------ failure semantics seen by the caller (real DB rows)
@pytest.mark.parametrize(
    "exc,status,denial,child_status",
    [
        (HTTPException(402, "x"), LegStatus.NOT_ENTITLED, Denial.ENTITLEMENT, "DENIED"),
        (HTTPException(403, "x"), LegStatus.DENIED, Denial.PERMISSION, "DENIED"),
        (HTTPException(404, "x"), LegStatus.UNAVAILABLE, None, "FAILED"),
        (HTTPException(503, "model down"), LegStatus.UNAVAILABLE, None, "FAILED"),
        (HTTPException(409, "x"), LegStatus.FAILED, None, "FAILED"),
        (HTTPException(422, "x"), LegStatus.FAILED, None, "FAILED"),
        (RuntimeError("secret connection string postgresql://u:p@h/db"), LegStatus.FAILED, None, "FAILED"),
        (TimeoutError("read timed out"), LegStatus.FAILED, None, "FAILED"),
    ],
)
def test_a_specialist_failure_becomes_an_honest_settled_leg_without_internals(exc, status, denial, child_status, two_tenants, app_user, caplog):
    a, _ = two_tenants
    inv, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    base = REG.get("cfo.financial_health")

    def fails(*_a, **_k):
        raise exc

    leg = dispatch(turn, "cfo.financial_health", D, registry=ActionRegistry([replace(base, invoke=fails)]), now=T0)
    assert leg.status is status and leg.denial is denial and leg.payload is None and not leg.figure_refs
    assert "secret" not in repr(leg) and "postgresql" not in repr(leg)  # nothing internal reaches the caller or the composer
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert child["status"] == child_status and child["finished_at"] is not None  # never left RUNNING
    finding = repo.list_findings(a, inv, turn_id=turn.turn_id)[0]
    assert finding["status"] == status.value and "secret" not in str(finding)


def test_a_failed_leg_does_not_stop_the_next_one(two_tenants, app_user):
    a, _ = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    base = REG.get("cfo.financial_health")
    bad = ActionRegistry([replace(base, invoke=lambda *_a: (_ for _ in ()).throw(RuntimeError("x")))])
    assert dispatch(turn, "cfo.financial_health", D, registry=bad, now=T0).status is LegStatus.FAILED
    assert dispatch(turn, "cfo.financial_health", D, now=T0).status is LegStatus.COMPLETE
    assert turn.derive_status() == "PARTIAL"


def test_the_gst_lookup_with_the_model_down_is_an_unavailable_leg_and_stores_no_result(two_tenants, app_user, monkeypatch, caplog):
    from calc_engine.gst_lookup.fetcher import RawPage
    from cfo.reasoning.ollama_provider import OllamaUnavailable

    from backend.services import cfo_actions

    class Fetcher:
        def fetch(self, url):
            return RawPage(url=url, status_code=200, body="page", fetched_at=datetime.now(timezone.utc))

    class DownLlm:
        def __init__(self, *a, **k):
            pass

        def complete(self, *, model, prompt):
            raise OllamaUnavailable("down")

    monkeypatch.setattr(cfo_actions, "HttpxGstFetcher", lambda: Fetcher())
    monkeypatch.setattr(cfo_actions, "OllamaLlmProvider", DownLlm)
    a, _ = two_tenants
    _, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    leg = dispatch(turn, "cfo.gst_lookup", {"product_title": "steel water bottle"}, now=T0)
    # Same meaning as the direct route's 503 (C20: one function, two entry paths): a dependency is down, not a server bug and not a result.
    assert leg.status is LegStatus.UNAVAILABLE and leg.reason == "unavailable" and leg.payload is None
    assert not [r for r in caplog.records if r.levelname == "ERROR"]  # an expected outage is not logged as an unhandled exception
    assert not leg.payload or not leg.payload.get("likelyRatePct")  # no rate is produced from a dead model
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM gst_lookup_result")).scalar_one() == 0


# ------------------------------------------------------------------------------------------------ concurrency and duplicates
def test_parallel_legs_from_one_tenant_each_get_their_own_settled_row(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    _, turn = _open(a, app_user, ctx)
    results: list = []
    errors: list = []

    def run():
        try:
            results.append(dispatch(turn, "cfo.financial_health", D, now=T0).status)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and results.count(LegStatus.COMPLETE) == 6
    children = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert len(children) == 6 and all(c["status"] == "COMPLETE" for c in children)


def test_two_tenants_dispatching_at_once_do_not_cross(two_tenants, app_user):
    a, b = two_tenants
    turns = {t: _open(t, app_user, ctx_for(t, user_id=app_user))[1] for t in (a, b)}
    out: dict = {}

    def run(t):
        out[t] = dispatch(turns[t], "cfo.cash_reconciliation", {**D, "marketplace": "FLIPKART"}, now=T0)

    th = [threading.Thread(target=run, args=(t,)) for t in (a, b)]
    [t.start() for t in th]
    [t.join() for t in th]
    refs = {t: {m["engineResultRef"] for m in out[t].payload.values() if isinstance(m, dict) and "engineResultRef" in m} for t in (a, b)}
    assert refs[a] and refs[b] and not (refs[a] & refs[b])
    for t in (a, b):
        with tenant_scope(t) as conn:
            ids = {str(r[0]) for r in conn.execute(text("SELECT id FROM metric_result"))}
        assert refs[t] <= ids  # every cited ref resolves in its own tenant
        other = b if t == a else a
        assert not (refs[other] & ids)
