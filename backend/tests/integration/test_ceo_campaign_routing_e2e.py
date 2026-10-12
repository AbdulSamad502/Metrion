"""Task 1 campaign: the routing matrix through the REAL `run_turn` (rules -> classifier -> plan validation -> approval gate -> dispatch).

Evidence: real-dispatcher integration + database persistence. The classifier is a fake that raises if it is consulted for a request the explicit rules should decide, and
returns a scripted verdict (what a well-behaved or a badly-behaved model might say) for the rest, so the rows below measure the CODE around the model. Handlers are spies
that record the arguments the CEO actually passed. Nothing financial is evaluated."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.ceo import orchestrator
from backend.llm.model import ScriptedModel
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_campaign_safety import spied
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")

ADVISORY = json.dumps({"route": "ADVISORY", "route_key": None, "slots": {}, "needs_agent": None, "clarify_for": None})
OUT_OF_SCOPE = json.dumps({"route": "OUT_OF_SCOPE", "route_key": None, "slots": {}, "needs_agent": None, "clarify_for": None})


def verdict(route, key=None, clarify_for=None, **slots):
    return json.dumps({"route": route, "route_key": key, "slots": slots, "needs_agent": None, "clarify_for": clarify_for})


def build(model_verdict: str | None):
    """(runtime, spy calls, model calls). With `model_verdict=None` the model is forbidden: a call fails the test."""
    registry, called = spied()
    model_calls: list[str] = []

    def script(prompt, schema):
        model_calls.append(prompt)
        if model_verdict is None:
            raise AssertionError("the model was consulted for a request the explicit rules should decide")
        return model_verdict

    base = runtime(Scripted({}), Grounded(), registry=registry, max_legs=5)
    return replace(base, classifier=ScriptedModel(script, name="matrix"), max_candidate_prices=5), called, model_calls


# (request, scripted model verdict or None when a RULE must decide, expected effective route, expected effective key, expected status, handlers expected to run)
CASES = [
    # --- product discovery / intelligence (approval-gated: refused before anything is asked or run)
    ("Find trending products in the mens shoes niche under 2000 on Amazon", None, "ADVISORY", None, "DENIED", []),
    ("What are the top selling products on Amazon?", None, "ADVISORY", None, "DENIED", []),
    ("suggest products to sell in kitchenware", None, "ADVISORY", None, "DENIED", []),
    ("Show me the latest product research report", None, "CLARIFY", None, "CLARIFIED", []),  # no finished run exists: asked, never invented
    ("What product ideas did you find?", None, "BUSINESS_STATE", "QT_PRODUCT_IDEAS", "DELIVERED", []),
    ("What did the product research find for yoga mats?", None, "BUSINESS_STATE", "QT_PRODUCT_IDEAS", "DELIVERED", []),
    # --- misrouting guards: these must NOT start a market-wide discovery run
    ("Research my competitor's product reviews", "MODEL", None, None, None, []),
    ("What are my top selling products?", "MODEL", None, None, None, []),
    # --- marketing / CMO (metered: approval-gated)
    ("Write hashtags for my steel water bottle on Amazon", None, "ADVISORY", None, "DENIED", []),
    ("Write a title for my steel bottle on Flipkart", None, "ADVISORY", None, "DENIED", []),
    ("Write a description for my yoga mat", None, "ADVISORY", None, "DENIED", []),
    ("Give me keywords for my yoga mat", None, "ADVISORY", None, "DENIED", []),
    ("What's trending in my niche?", None, "ADVISORY", None, "DENIED", []),
    ("What titles did we write?", None, "BUSINESS_STATE", "QT_LISTING_CONTENT", "DELIVERED", []),
    # --- competitors / pricing (non-financial routing only)
    ("What are my competitors charging?", None, "BUSINESS_STATE", "QT_COMPETITORS_PRICES", "DELIVERED", []),
    ("Acme dropped to Rs 499, what happens to my margin?", None, "CLARIFY", None, "CLARIFIED", []),  # no tracked competitor: asked, never guessed
    # --- GST (one action to the model, route chosen by code)
    ("What GST rate applies to steel water bottles?", None, "ACTION", "gst_lookup", "DELIVERED", ["cfo.gst_lookup"]),
    # --- decision playbook (form-driven): the CEO asks, it does not run
    ("Should I stock yoga mats?", None, "CLARIFY", None, "CLARIFIED", []),
    # --- the seller's saved facts and general guidance
    ("What have I told you about my business?", None, "BUSINESS_STATE", "QT_SELLER_FACTS", "DELIVERED", []),
    ("How should I think about pricing?", None, "ADVISORY", None, "DELIVERED", []),
    ("Where am I losing money?", None, "BUSINESS_STATE", "QT_LEAKS", "DELIVERED", []),
    # --- ambiguous / irrelevant / unsupported: the model decides; plan validation holds either way
    ("Hello", ADVISORY, "ADVISORY", None, "DELIVERED", []),
    ("asdfgh", verdict("CLARIFY", clarify_for="UNCLEAR_REQUEST"), "CLARIFY", None, "CLARIFIED", []),
    ("Delete my competitor Acme", OUT_OF_SCOPE, "OUT_OF_SCOPE", None, "DELIVERED", []),
    ("Upload my sales file", OUT_OF_SCOPE, "OUT_OF_SCOPE", None, "DELIVERED", []),
    ("Find suppliers for yoga mats", OUT_OF_SCOPE, "OUT_OF_SCOPE", None, "DELIVERED", []),
    # a model that wrongly offers something outside the catalog is stopped by code
    ("Find suppliers for yoga mats please", verdict("ACTION", "pi.supplier_lookup"), "CLARIFY", None, "CLARIFIED", []),
    ("Run research now on my uploaded screenshots", verdict("ACTION", "ci.research_now"), "CLARIFY", None, "CLARIFIED", []),
    ("Record this expense for me", verdict("ACTION", "cfo.enter_expense"), "CLARIFY", None, "CLARIFIED", []),
    ("Which area should I focus on?", verdict("CLARIFY", clarify_for="WHICH_AGENT"), "ADVISORY", None, "DELIVERED", []),  # a general question is answered, not interrogated
]


@pytest.mark.parametrize("text,model_verdict,route,key,status,expected_calls", [c for c in CASES if c[1] != "MODEL"], ids=[c[0][:60] for c in CASES if c[1] != "MODEL"])
def test_routing_matrix(text, model_verdict, route, key, status, expected_calls, two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt, called, model_calls = build(model_verdict)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, text)

    turn = repo.get_turn(a, res.turn_id)
    assert (turn["route"], turn["route_key"]) == (route, key), (turn["route"], turn["route_key"], res.answer[:120])
    assert res.status == status, (res.status, res.answer[:160])
    assert called == expected_calls
    if model_verdict is None:
        assert model_calls == [] and turn["classifier_result"]["model"] == "rules"  # decided by the explicit rule, instantly and identically every time
    # the answer never claims work that did not run
    if not called:
        low = res.answer.lower()
        assert "i ran" not in low and "succeeded" not in low
    # persistence: the question and exactly one answer are stored, in order, attached to this turn
    msgs = repo.list_messages(a, inv)
    assert [m["role"] for m in msgs] == ["USER", "CEO"] and msgs[1]["turn_id"] == res.turn_id


@pytest.mark.parametrize("text", [c[0] for c in CASES if c[1] == "MODEL"])
def test_requests_about_competitors_or_own_sales_never_start_market_discovery(text, two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt, called, _ = build(ADVISORY)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, text)
    turn = repo.get_turn(a, res.turn_id)
    assert turn["route_key"] != "pi.discover" and "approvalRequiredFor" not in (turn["classifier_result"] or {})
    assert "approved first" not in res.answer and called == []


def test_the_niche_and_budget_are_passed_as_the_seller_said_them(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt, _, _ = build(None)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Find trending products in the mens shoes niche under 2000 on Amazon")
    slots = repo.get_turn(a, res.turn_id)["slots"]
    assert slots == {"marketplace": "Amazon", "product": "mens shoes", "amount": "2000"}


def test_the_gst_lookup_receives_exactly_the_product_the_seller_named(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    seen: list = []
    registry, _ = spied()
    from backend.ceo.registry import ActionRegistry

    def capture(slots, c, leg):
        seen.append(slots.model_dump())
        return {"result": None, "noMatch": None}

    specs = [replace(s, invoke=capture) if s.key == "cfo.gst_lookup" else s for s in registry.specs()]
    rt = replace(runtime(Scripted({}), Grounded(), registry=ActionRegistry(specs), max_legs=5), classifier=ScriptedModel(lambda p, s: pytest.fail("model consulted"), name="none"))
    orchestrator.run_turn(ctx, rt, start(ctx, rt), "What GST rate applies to steel water bottles?")
    assert seen == [{"product_title": "steel water bottles"}]


# ------------------------------------------------------------------------------------------------ follow-ups and carry-over
def test_a_follow_up_uses_the_new_period_and_a_new_conversation_does_not_inherit_the_old_one(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    seen: list[dict] = []
    registry, _ = spied()
    from backend.ceo.registry import ActionRegistry

    def capture(slots, c, leg):
        seen.append({k: v for k, v in slots.model_dump().items() if k in ("period_start", "period_end")})
        return {"overallBand": None, "perMetricBands": {}, "engineResultRefs": [], "unavailableReason": "stand-in", "methods": [], "signals": []}

    specs = [replace(s, invoke=capture) if s.key.startswith("cfo.") else s for s in registry.specs()]
    first_q, second_q, third_q = "Why did my profit drop in July?", "and what about August?", "and what about that month?"
    table = {
        first_q: verdict("PLAYBOOK", "PROFIT_DIAGNOSIS", period="July"),
        second_q: verdict("PLAYBOOK", "PROFIT_DIAGNOSIS", period="August"),
        third_q: verdict("PLAYBOOK", "PROFIT_DIAGNOSIS"),  # a model that cannot name the month: nothing to carry over
    }
    cls = Scripted(table)
    rt = runtime(cls, Grounded(), registry=ActionRegistry(specs))
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, first_q)
    orchestrator.run_turn(ctx, rt, inv, second_q)
    july, august = seen[0], seen[-1]
    assert (july["period_start"].month, august["period_start"].month) == (7, 8)  # the follow-up used ITS period, not the previous turn's
    n = len(seen)
    new_inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, new_inv, third_q)
    assert len(seen) == n and res.status == "CLARIFIED" and res.clarify_for == "period"  # nothing inherited from the old conversation: the CEO asks


# ------------------------------------------------------------------------------------------------ known gaps (documented, not hidden)
def test_a_compound_request_does_not_silently_drop_its_second_half(two_tenants, app_user):
    """Was a strict xfail (known gap); fixed by hardening Fix 1: the part that is not handled is named, with its reason."""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt, called, _ = build(None)
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), "Write titles and also find trending products in kitchenware")
    assert called == [] and res.answer.count("• Not handled") == 2 and "approved plan" in res.answer


def test_a_price_scenario_request_is_not_answered_as_a_price_list(two_tenants, app_user):
    """Was a strict xfail (known gap); fixed by hardening Fix 2A: a scenario request asks for the missing competitor instead of listing prices."""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt, called, _ = build(None)
    res = orchestrator.run_turn(ctx, rt, start(ctx, rt), "Show me the competitor price scenario at 499")
    assert repo.get_turn(a, res.turn_id)["route_key"] != "QT_COMPETITORS_PRICES" and res.status == "CLARIFIED" and called == []
