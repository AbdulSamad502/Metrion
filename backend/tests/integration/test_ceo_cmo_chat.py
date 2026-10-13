"""Spec 6.35: the CEO runs CMO listing writing from chat. The seller says what they want, the CEO asks for what CMO needs one question at a time (every answer parsed by
code), then runs the REAL registered action with slots validated by CMO's own request model. What CMO wrote is shown quoted and labelled, never as a figure; a failed
artefact is a named gap; a detached CMO cannot be run; answering the same card twice sends the same idempotency key.

The CMO handler here is a recorder returning a payload shaped like `cmo_response.run_json` (a test double, not the generator); the generator itself is covered by the CMO tests."""

from __future__ import annotations

import dataclasses
import os

import pytest

from backend.ceo import orchestrator
from backend.ceo.contract import ActionSpec
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_state_specialists import NOW, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]


KEYS = ("cmo.generate_title_sets", "cmo.generate_hashtags", "cmo.generate_description", "cmo.generate_keywords")


def payload_for(output_type: str, **content):
    return {"runStatus": "COMPLETE", "unitsBilled": 1, "agentRunId": None, "artefacts": [{"id": "a", "outputType": output_type, "marketplace": content.pop("marketplace", None), "status": "COMPLETE", "reused": False, **content}]}


def registry(calls, reply=None):
    real, specs = get_registry(), []
    for k in KEYS:
        r = real.get(k)
        out = (reply or {}).get(k) or payload_for("HASHTAGS", hashtags=["#steelbottle", "#hydrate"])
        specs.append(ActionSpec(key=k, source=r.source, agent=r.agent, effect=r.effect, description=k, slot_model=r.slot_model, writes_own_run=False,
                                invoke=lambda s, ctx, leg, k=k, out=out: calls.setdefault(k, []).append(s) or out, fixed_params=r.fixed_params))
    return ActionRegistry(specs)


def rt_for(calls, classifier, reply=None):
    return runtime(classifier, Grounded(), registry=registry(calls, reply))


def skip_extras(ctx, rt, inv, res):
    """The optional extra-detail questions (brand, features...) that follow the required ones: each is skipped."""
    while res.status == "CLARIFIED" and str(res.choices["slot"]).startswith("fact_"):
        res = orchestrator.run_turn(ctx, rt, inv, "skip")
    return res


ASK = "give me hashtags for my steel water bottle"
ASK_ALL = "write hashtags for my steel water bottle on Amazon"
HASHTAGS = lambda **slots: decision(route="ACTION", route_key="cmo.generate_hashtags", slots=slots)  # noqa: E731


@pytest.mark.usefixtures("approval_gate_bypassed")
def test_the_ceo_asks_only_for_what_is_missing_then_runs_cmo_and_shows_what_was_written(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls, Scripted({ASK: HASHTAGS(product="steel water bottle")}))
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert q.status == "CLARIFIED" and calls == {} and "Which marketplace" in q.answer and q.answer.startswith("(2 of 4)")  # the product was already said: not asked again
    assert q.choices["kind"] == "INPUT" and q.choices["pending"]["route"] == "ACTION" and q.choices["pending"]["key"] == "cmo.generate_hashtags"
    asked = orchestrator.run_turn(ctx, rt, inv, "Amazon")  # a typed reply to the open question is the ANSWER (no classifier)
    assert asked.status == "CLARIFIED" and asked.choices["slot"] == "fact_brand" and calls == {}  # then the optional, skippable extra details
    done = skip_extras(ctx, rt, inv, asked)
    assert done.status == "DELIVERED" and done.composition_mode == "TEMPLATE"
    [slots] = calls["cmo.generate_hashtags"]
    assert slots.product_name == "steel water bottle" and slots.marketplace.value == "AMAZON" and slots.request_key.startswith("ceo-")
    assert "#steelbottle" in done.answer and "Written by the specialist" in done.answer  # quoted and labelled
    [finding] = [f for f in done.findings if f["action_key"] == "cmo.generate_hashtags"]
    assert finding["status"] == "COMPLETE" and finding["presentation"]["artefacts"][0]["items"] == ["#steelbottle", "#hydrate"]
    assert finding["presentation"]["figures"] == []  # written content is never a figure


@pytest.mark.usefixtures("approval_gate_bypassed")
def test_everything_in_the_first_message_runs_with_no_questions(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls, Scripted({ASK_ALL: HASHTAGS(product="steel water bottle", marketplace="Amazon")}))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, ASK_ALL)
    assert res.status == "CLARIFIED" and res.choices["slot"] == "fact_brand" and calls == {}  # only the optional extra details are left to ask; nothing ran yet
    res = skip_extras(ctx, rt, inv, res)
    assert res.status == "DELIVERED" and len(calls["cmo.generate_hashtags"]) == 1


@pytest.mark.usefixtures("approval_gate_bypassed")
def test_a_bad_answer_is_asked_again_and_nothing_runs(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls, Scripted({ASK: HASHTAGS(product="steel water bottle")}))
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, ASK)
    bad = orchestrator.run_turn(ctx, rt, inv, "the big one")
    assert bad.status == "CLARIFIED" and "Which marketplace" in bad.answer and calls == {}
    assert bad.choices["pending"]["collected"] == {"product_name": "steel water bottle"}


@pytest.mark.usefixtures("approval_gate_bypassed")
def test_title_sets_take_several_marketplaces_and_an_optional_category(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    ask = "write titles for my steel water bottle"
    reply = {"cmo.generate_title_sets": {"runStatus": "COMPLETE", "unitsBilled": 2, "agentRunId": None, "artefacts": [
        {"outputType": "TITLE_SET", "marketplace": "AMAZON", "status": "COMPLETE", "options": [{"text": "Steel Water Bottle 1L"}, {"text": "Insulated Bottle"}],
         "constraint": {"sourceUrl": "https://example.test/rule", "verifiedAt": "2026-09-01"}},
        {"outputType": "TITLE_SET", "marketplace": "FLIPKART", "status": "FAILED", "failure": {"code": "X", "reason": "r", "missingFacts": ["material"]}}]}}
    rt = rt_for(calls, Scripted({ask: decision(route="ACTION", route_key="cmo.generate_title_sets", slots={"product": "steel water bottle"})}), reply)
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, ask)  # asks the category
    q = orchestrator.run_turn(ctx, rt, inv, "skip")
    assert "Which marketplace" in q.answer
    res = skip_extras(ctx, rt, inv, orchestrator.run_turn(ctx, rt, inv, "Amazon and Flipkart"))
    [slots] = calls["cmo.generate_title_sets"]
    assert [m.value for m in slots.marketplaces] == ["AMAZON", "FLIPKART"] and slots.category_hint is None  # a skipped field is absent, never defaulted
    assert "Steel Water Bottle 1L" in res.answer and "example.test/rule" in res.answer
    assert "Not available: Title options for Flipkart could not be written: more detail is needed about material." in res.answer  # the failure is named, not hidden


def test_a_detached_cmo_cannot_be_run_and_nothing_is_asked(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls, Scripted({ASK: HASHTAGS(product="steel water bottle", marketplace="Amazon")}))
    inv = start(ctx, rt)
    repo.set_agent_attachment(a, inv, "CMO", attached=False, changed_by=app_user, now=NOW)
    res = orchestrator.run_turn(ctx, rt, inv, ASK)
    assert calls == {} and res.status != "DELIVERED" or "CMO" in res.answer
    assert calls == {} and res.choices is None  # not asked anything: it cannot run, so collecting inputs for it would be a lie


@pytest.mark.usefixtures("approval_gate_bypassed")
def test_the_same_answer_to_the_same_card_sends_the_same_idempotency_key(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = rt_for(calls, Scripted({ASK: HASHTAGS(product="steel water bottle")}))
    inv = start(ctx, rt)
    q = orchestrator.run_turn(ctx, rt, inv, ASK)
    reply = orchestrator.ClarificationReply(q.message_id, None)
    res = orchestrator.run_turn(ctx, rt, inv, "Amazon", clarification=reply)
    res = orchestrator.run_turn(ctx, rt, inv, "skip")  # brand
    last = orchestrator.ClarificationReply(res.message_id, None)  # the final card (key features)
    orchestrator.run_turn(ctx, rt, inv, "skip", clarification=last)
    orchestrator.run_turn(ctx, rt, inv, "skip", clarification=last)  # a retry of the same answer
    keys = [s.request_key for s in calls["cmo.generate_hashtags"]]
    assert len(keys) == 2 and keys[0] == keys[1]  # CMO treats an identical key as the same request: no second charge, same artefact


def test_cmo_content_never_enters_the_figures_or_a_model_prompt(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    comp = Grounded()
    base = rt_for(calls, Scripted({ASK_ALL: HASHTAGS(product="steel water bottle", marketplace="Amazon")}))
    rt = dataclasses.replace(base, composer=comp.model())
    orchestrator.run_turn(ctx, rt, start(ctx, rt), ASK_ALL)
    assert comp.calls == 0  # what CMO wrote is shown as written; a second model never rewords it
