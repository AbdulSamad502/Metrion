"""Spec agent-needs-and-shared-knowledge.md slice S1: "the description along with the GST %". The agents never call each other: the CEO runs the CMO's description and, as an
add-on from a closed catalog, the GST lookup (Route A or B chosen by code), with every check the provider has on its own. No model is called (the classifier is EMPTY)."""

from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import datetime, timezone
from fractions import Fraction

import pytest
from calc_engine.gst_lookup.types import GstLookupResult
from calc_engine.repositories import gst_lookup_repo

from backend.auth.permissions import AGENT_CEO, AGENT_CMO, INVESTIGATION_CREATE, INVESTIGATION_VIEW
from backend.ceo import needs, orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import ceo_need_repo, investigation_repo as repo
from backend.services import cfo_actions
from tests.integration.ceo_support import ctx_for, partner_ctx
from tests.integration.test_ceo_cmo_chat import payload_for
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

ASK = "give me a description for my steel water bottle along with the GST %"
TITLE = "Steel Water Bottle 1L Insulated"
DESCRIPTION = payload_for("DESCRIPTION", description="A tough 1L bottle that keeps drinks cold.", marketplace="AMAZON")


def stored(tenant):
    result = GstLookupResult(
        id=uuid.uuid4(), tenant_id=tenant, query_text=TITLE, source_url="https://example.gov/gst", retrieved_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        likely_rate_pct=Fraction("18"), alternatives=(), source_title="GST rates",
    )
    gst_lookup_repo.save(tenant, result)
    return result


@pytest.fixture
def lookup(monkeypatch, two_tenants):
    calls: list = []

    def fake(tenant_id, request):
        calls.append((tenant_id, request))
        return cfo_actions.GstLookupOutcome(result=stored(tenant_id))

    monkeypatch.setattr(cfo_actions, "run_gst_applicability_lookup", fake)
    monkeypatch.setenv("CEO_NEEDS_MAX_PER_TURN", "2")
    return calls


def registry(calls, *, fail=False):
    real = get_registry()
    r = real.get("cmo.generate_description")

    def invoke(s, ctx, leg):
        calls.setdefault("cmo.generate_description", []).append(s)
        if fail:
            raise RuntimeError("boom")
        return DESCRIPTION

    desc = ActionSpec(key=r.key, source=r.source, agent=r.agent, effect=r.effect, description=r.key, slot_model=r.slot_model, writes_own_run=False, invoke=invoke, fixed_params=r.fixed_params)
    return ActionRegistry([desc, real.get("cfo.gst_lookup"), real.get("service.gst_lookup")])


def converse(ctx, rt, inv):
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert res.clarify_for == "marketplace" and res.choices["addons"] == ["GST_RATE_FOR_PRODUCT"]  # the add-on rides on the questions
    res = orchestrator.run_turn(ctx, rt, inv, "Amazon")
    assert res.clarify_for == "seller_title" and res.choices["addons"] == ["GST_RATE_FOR_PRODUCT"]
    return orchestrator.run_turn(ctx, rt, inv, TITLE)


def needs_of(tenant, inv):
    return ceo_need_repo.list_for_investigation(tenant, inv)


def test_the_description_and_the_gst_rate_come_in_one_answer_and_the_step_is_recorded(two_tenants, app_user, lookup):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(ctx, rt)
    res = converse(ctx, rt, inv)
    assert res.status == "DELIVERED" and len(calls["cmo.generate_description"]) == 1
    [(tenant, request)] = lookup
    assert tenant == a and request.product_title == TITLE and request.category is None and request.hsn is None  # only the seller's own title; nothing from the CMO's text
    assert "A tough 1L bottle" in res.answer  # the CMO's own block, quoted
    findings = {f["action_key"]: f for f in repo.list_findings(a, inv)}
    assert set(findings) == {"cmo.generate_description", "cfo.gst_lookup"}  # separate blocks, each with its own source
    fig = findings["cfo.gst_lookup"]["presentation"]["figures"][0]
    assert (fig["value"], fig["register"]) == ("18%", "DERIVED")  # provisional, never verified
    [need] = needs_of(a, inv)
    assert (need["need_key"], need["requester_agent"], need["provider_key"], need["status"]) == ("GST_RATE_FOR_PRODUCT", "CMO", "cfo.gst_lookup", "FULFILLED")


def test_without_the_limit_configured_the_main_request_still_runs_and_the_gap_is_named(two_tenants, app_user, lookup, monkeypatch):
    a, _ = two_tenants
    monkeypatch.delenv("CEO_NEEDS_MAX_PER_TURN")
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(ctx, rt)
    res = converse(ctx, rt, inv)
    assert res.status == "DELIVERED" and "A tough 1L bottle" in res.answer and lookup == []
    assert "limit for follow-up lookups is not configured" in res.answer
    assert [n["status"] for n in needs_of(a, inv)] == ["CONFIG_MISSING"]


def test_a_member_without_the_lookup_gets_the_description_and_the_wall_never_a_rate(two_tenants, app_user, lookup):
    a, _ = two_tenants
    calls: dict = {}
    owner = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    inv = start(owner, rt)
    member = dataclasses.replace(partner_ctx(a, AGENT_CEO, AGENT_CMO, INVESTIGATION_VIEW, INVESTIGATION_CREATE), app_user_id=app_user)
    res = converse(member, rt, inv)
    assert "A tough 1L bottle" in res.answer and lookup == []  # the requester's rights grant the provider nothing
    assert "GST lookup permission" in res.answer and "18" not in res.answer
    assert [n["status"] for n in needs_of(a, inv)] == ["DENIED"]


def test_the_add_on_never_runs_when_the_main_request_did_not_complete(two_tenants, app_user, lookup):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls, fail=True))
    inv = start(ctx, rt)
    converse(ctx, rt, inv)
    assert lookup == [] and [n["status"] for n in needs_of(a, inv)] == ["DROPPED"]


def test_a_need_is_recorded_once_per_idempotency_key(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, runtime(Scripted({}), Grounded()))
    kw = dict(investigation_id=inv, turn_message_id=None, need_key="GST_RATE_FOR_PRODUCT", requester_agent="CMO", mode="PARALLEL", provider_key="cfo.gst_lookup", idempotency_key="k-1", status="FULFILLED")
    assert ceo_need_repo.record(a, **kw) is True and ceo_need_repo.record(a, **kw) is False and len(needs_of(a, inv)) == 1


def test_the_catalog_decides_what_an_add_on_can_be():
    assert needs.valid_addons("cmo.generate_description", ["GST_RATE_FOR_PRODUCT", "GST_RATE_FOR_PRODUCT", "DROP_TABLE", "CEO_READ"]) == ["GST_RATE_FOR_PRODUCT"]  # unknown and repeated: dropped
    assert needs.valid_addons("cmo.generate_hashtags", ["GST_RATE_FOR_PRODUCT"]) == []  # only the requester's own actions may carry it
    assert needs.product_text({"seller_title": "x" * 201}) is None and needs.product_text({"product_name": "Bottle"}) == "Bottle"  # too long: asked about, never truncated


# ------------------------------------------------------------------------------------------------ S2: the PI idea and competitor links are recorded
def test_the_idea_link_is_recorded_only_when_the_seller_named_a_pi_idea(two_tenants, app_user):
    from tests.integration.test_ceo_cmo_chat import registry as cmo_registry  # noqa: F401
    from tests.integration.test_ceo_decision_playbooks import recording_registry
    from tests.integration.test_ceo_pi_chat import registry as pi_registry, run_through

    a, _ = two_tenants
    calls: dict = {}
    for sku in ("Leather Formal Shoes", "Cotton Kurti Set"):  # a stored quote and budget, so only the quantity and window are asked
        cfo_actions.enter_expense(a, target_type="SKU", target_ref=sku, field="supplier.quote", value={"supplier_name": "S", "unit_cost_paise": 20000}, created_by=app_user)
    cfo_actions.enter_expense(a, target_type="ACCOUNT", target_ref=str(a), field="batch.budget", value={"amount_paise": 5000000}, created_by=app_user)
    ctx = ctx_for(a, user_id=app_user)
    both = ActionRegistry([*pi_registry(calls).specs(), *recording_registry(calls).specs()])
    rt = dataclasses.replace(runtime(Scripted({}), Grounded(), registry=both), max_candidate_prices=5)
    inv = start(ctx, rt)
    run_through(ctx, rt, inv, ["20000", "Amazon", "skip", "quick", "yes"])  # PI lists ideas
    q = orchestrator.run_turn(ctx, rt, inv, "is #2 worth stocking?")
    assert q.choices["pending"]["key"] == "NEW_PRODUCT_DECISION" and q.choices["addons"] == ["LANDED_COST_FOR_IDEA"]
    q = orchestrator.run_turn(ctx, rt, inv, "200")
    done = orchestrator.run_turn(ctx, rt, inv, "(chose an option)", clarification=orchestrator.ClarificationReply(q.message_id, q.choices["options"][0]["key"]))
    assert done.status == "DELIVERED"
    assert [(n["need_key"], n["requester_agent"], n["status"]) for n in needs_of(a, inv)] == [("LANDED_COST_FOR_IDEA", "PI", "FULFILLED")]
    inv2 = start(ctx, rt)  # a plain stock question with no PI idea behind it is not a PI link
    q2 = orchestrator.run_turn(ctx, rt, inv2, "should I stock Cotton Kurti Set?")
    q2 = orchestrator.run_turn(ctx, rt, inv2, "100")
    orchestrator.run_turn(ctx, rt, inv2, "(chose an option)", clarification=orchestrator.ClarificationReply(q2.message_id, q2.choices["options"][0]["key"]))
    assert needs_of(a, inv2) == []


def test_the_append_only_tables_cannot_be_updated_or_deleted_by_the_app_role(migrate_engine):
    from sqlalchemy import text

    with migrate_engine.connect() as c:
        for table in ("ceo_need", "agent_memory", "shared_finding"):
            for priv in ("UPDATE", "DELETE", "TRUNCATE"):
                assert c.execute(text("SELECT has_table_privilege('metrion_app', :t, :p)"), {"t": table, "p": priv}).scalar() is False, (table, priv)
            assert c.execute(text("SELECT has_table_privilege('metrion_app', :t, 'INSERT')"), {"t": table}).scalar() is True
