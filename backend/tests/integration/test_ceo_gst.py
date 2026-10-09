"""B4: the GST lookup from chat (spec C11, G1-G7). One action to the model; CODE picks Route A (CFO's lookup) or Route B (the shared service) from the
member's permissions and the attached agents. The result is PROVISIONAL (DERIVED, never verified), cited by a ref that re-resolves, and carries the
stored disclaimer verbatim. Nothing from chat can apply it to a calculation, and a member without the lookup permission gets a wall, never an answer
from general knowledge."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from fractions import Fraction

import pytest
from calc_engine.gst_lookup.types import GstLookupResult
from calc_engine.repositories import gst_lookup_repo

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, INVESTIGATION_CREATE, INVESTIGATION_VIEW, SERVICE_GST_LOOKUP
from backend.ceo import orchestrator, plans, provenance
from backend.ceo.contract import Register
from backend.ceo.evidence import EvidenceCollector
from backend.repositories import investigation_repo as repo
from backend.services import cfo_actions
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for, partner_ctx
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

MSG = "Which GST rate applies to my steel water bottle?"
ASK = decision(route="ACTION", route_key="gst_lookup", slots={"product": "steel water bottle"})
KEYS = (AGENT_CEO, INVESTIGATION_VIEW, INVESTIGATION_CREATE, SERVICE_GST_LOOKUP)


def _stored(tenant, rate="18", alternatives=()):
    result = GstLookupResult(
        id=uuid.uuid4(), tenant_id=tenant, query_text="steel water bottle", source_url="https://example.gov/gst", retrieved_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        likely_rate_pct=Fraction(rate), alternatives=tuple(alternatives), source_title="GST rates",
    )
    gst_lookup_repo.save(tenant, result)
    return result


@pytest.fixture
def fake_lookup(monkeypatch):
    calls: list = []

    def install(outcome):
        def fake(tenant_id, request):
            calls.append((tenant_id, request))
            return outcome

        monkeypatch.setattr(cfo_actions, "run_gst_applicability_lookup", fake)

    install.calls = calls
    return install


def _turn(a, ctx, rt, inv):
    return orchestrator.run_turn(ctx, rt, inv, MSG)


# --------------------------------------------------------------------------------------------- route selection (pure)
def test_route_a_is_preferred_when_available_else_route_b_else_none():
    assert plans.gst_route_key(frozenset({"cfo.gst_lookup", "service.gst_lookup"})) == "cfo.gst_lookup"
    assert plans.gst_route_key(frozenset({"service.gst_lookup"})) == "service.gst_lookup"
    assert plans.gst_route_key(frozenset({"cfo.financial_health"})) is None


def test_the_model_sees_one_gst_action_never_the_two_routes():
    assert "gst_lookup" in plans.ACTIONS and not {"cfo.gst_lookup", "service.gst_lookup"} & set(plans.ACTIONS)


@pytest.mark.parametrize("raw,shown", [("18", "18%"), ("5", "5%"), ("1/4", "0.25%"), ("9/2", "4.5%"), ("x", None), ("", None)])
def test_a_stored_rate_is_shown_exactly_and_never_through_a_float(raw, shown):
    assert EvidenceCollector._rate_text(raw) == shown


# --------------------------------------------------------------------------------------------- Route B (no agent.cfo)
def test_route_b_member_without_cfo_gets_a_provisional_cited_rate_and_the_stored_disclaimer(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    stored = _stored(a, "18", alternatives=({"rate_pct": Fraction(12), "hsn": None, "category": None},))
    fake_lookup(cfo_actions.GstLookupOutcome(result=stored))
    ctx = partner_ctx(a, *KEYS)
    rt = runtime(Scripted({MSG: ASK}), Grounded())
    inv = start(ctx, rt)
    res = _turn(a, ctx, rt, inv)
    assert res.status == "DELIVERED" and res.route_key == "gst_lookup"
    (finding,) = repo.list_findings(a, inv)
    assert (finding["source"], finding["action_key"]) == ("GST_LOOKUP", "service.gst_lookup")  # Route B: no CFO unit, no CFO source
    fig = finding["presentation"]["figures"][0]
    assert (fig["value"], fig["register"]) == ("18%", "DERIVED") and fig["ref"]["source"] == "gst_lookup_result"  # provisional, never VERIFIED
    assert "12%" in repr(finding["presentation"]["facts"])
    assert stored.disclaimer in res.answer  # the stored text, placed by code
    (tenant, request), = fake_lookup.calls
    assert tenant == a and request.product_title == "steel water bottle" and request.category is None and request.hsn is None  # G6: only what the seller typed
    assert any("steel water bottle" in n for n in res.notes)  # the reading is echoed


def test_the_rate_is_never_labelled_verified(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    fake_lookup(cfo_actions.GstLookupOutcome(result=_stored(a)))
    ctx = partner_ctx(a, *KEYS)
    rt = runtime(Scripted({MSG: ASK}), Grounded())
    inv = start(ctx, rt)
    _turn(a, ctx, rt, inv)
    (finding,) = repo.list_findings(a, inv)
    assert all(f["register"] != Register.VERIFIED.value for f in finding["presentation"]["figures"])


# --------------------------------------------------------------------------------------------- Route A (agent.cfo attached)
def test_route_a_runs_through_cfo_when_cfo_is_permitted_and_attached(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    fake_lookup(cfo_actions.GstLookupOutcome(result=_stored(a)))
    ctx = ctx_for(a, user_id=app_user)  # OWNER: every key
    rt = runtime(Scripted({MSG: ASK}), Grounded())
    inv = start(ctx, rt)
    _turn(a, ctx, rt, inv)
    (finding,) = repo.list_findings(a, inv)
    assert (finding["source"], finding["action_key"]) == ("CFO", "cfo.gst_lookup")


def test_with_cfo_detached_the_same_question_uses_route_b(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    fake_lookup(cfo_actions.GstLookupOutcome(result=_stored(a)))
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({MSG: ASK}), Grounded())
    inv = start(ctx, rt)
    repo.set_agent_attachment(a, inv, "CFO", attached=False, changed_by=app_user, now=T0)
    _turn(a, ctx, rt, inv)
    (finding,) = repo.list_findings(a, inv)
    assert finding["action_key"] == "service.gst_lookup"  # attachment is the seller's choice and it selects the route; the model never does


# --------------------------------------------------------------------------------------------- the wall and the non-results
def test_a_member_without_the_lookup_permission_gets_a_wall_and_no_lookup_runs(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    fake_lookup(cfo_actions.GstLookupOutcome(result=_stored(a)))
    owner = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({MSG: ASK}), Grounded())
    inv = start(owner, rt)
    member = partner_ctx(a, AGENT_CEO, INVESTIGATION_VIEW, AGENT_CFO)  # agent.cfo but NOT service.gst_lookup
    res = _turn(a, member, rt, inv)
    assert fake_lookup.calls == [] and repo.list_findings(a, inv) == []  # nothing ran, nothing was answered from general knowledge
    assert res.status == "CLARIFIED"  # the closed catalog does not offer the action to this member, so the model's pick is refused
    assert "18" not in res.answer and "%" not in res.answer


def test_a_ui_action_cannot_reach_the_lookup_without_the_permission(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    fake_lookup(cfo_actions.GstLookupOutcome(result=_stored(a)))
    owner = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded())
    inv = start(owner, rt)
    member = partner_ctx(a, AGENT_CEO, INVESTIGATION_VIEW)
    res = orchestrator.run_turn(member, rt, inv, "GST rate", ui_action=orchestrator.UiAction("ACTION", "gst_lookup", {"product": "steel water bottle"}))
    assert res.status == "DENIED" and fake_lookup.calls == []


def test_no_reliable_source_is_a_named_gap_with_no_rate_and_no_disclaimer_block(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    from calc_engine.gst_lookup.types import GstLookupNoMatch

    fake_lookup(cfo_actions.GstLookupOutcome(no_match=GstLookupNoMatch(query_text="steel water bottle", attempted_urls=("https://example.gov/x",))))
    ctx = partner_ctx(a, *KEYS)
    rt = runtime(Scripted({MSG: ASK}), Grounded())
    inv = start(ctx, rt)
    res = _turn(a, ctx, rt, inv)
    (finding,) = repo.list_findings(a, inv)
    assert finding["presentation"]["figures"] == [] and any("No GST rate could be found" in g for g in finding["presentation"]["gaps"])
    assert "%" not in res.answer.replace("Figures as of", "")


def test_an_empty_or_overlong_product_is_asked_about_not_looked_up(two_tenants, app_user, fake_lookup):
    a, _ = two_tenants
    fake_lookup(cfo_actions.GstLookupOutcome(result=_stored(a)))
    ctx = partner_ctx(a, *KEYS)
    for slots in ({"product": "   "}, {"product": "x" * 201}):
        table = {MSG: decision(route="ACTION", route_key="gst_lookup", slots=slots)}
        rt = runtime(Scripted(table), Grounded())
        inv = start(ctx, rt)
        res = _turn(a, ctx, rt, inv)
        assert res.status == "CLARIFIED" and res.clarify_for == "product"
    assert fake_lookup.calls == []


# --------------------------------------------------------------------------------------------- isolation and provenance
def test_another_tenants_lookup_ref_does_not_resolve(two_tenants):
    a, b = two_tenants
    stored = _stored(a)
    from backend.ceo.contract import Ref, RefKind

    ref = Ref(RefKind.AGENT_REPORT_FIELD, stored.id, source="gst_lookup_result")
    assert provenance.resolve_ref(a, ref).found is True
    assert provenance.resolve_ref(b, ref).found is False  # RLS: tenant B cannot verify (or show) tenant A's lookup


def test_nothing_in_the_registry_can_apply_a_lookup_to_a_calculation():
    from backend.ceo.registry import FORBIDDEN_ACTION_KEYS, get_registry

    assert not any("override" in k or "adjust" in k for k in get_registry().keys())
    assert FORBIDDEN_ACTION_KEYS  # the closed list of keys chat can never reach stays non-empty (G4: acceptance remains CFO's flow)
