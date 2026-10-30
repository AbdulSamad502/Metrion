"""CMO 3.0 M0 against a real Postgres (docs/CMO-3.0/CMO_ACCEPTANCE_TESTS.md O-04, O-06, O-10, O-15, O-18).

Real: the CMO routes and services, the Postgres store, RLS, the CEO chat's guided-input tables and the CEO's own read helpers. Faked: the model provider (the same deterministic router the
P5 tests use). The chat steps are driven through `input_session` exactly as the orchestrator drives them, and the result is posted to the SAME request model the registry's action uses."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from backend.ceo import business_state, cmo_chat
from backend.ceo import input_session as ins
from backend.ceo.registry import get_registry
from backend.repositories import cmo_chat_repo, cmo_showcase_repo
from backend.services import cmo_hints
from tests.integration.test_cmo_api import (  # noqa: F401  (fixtures + helpers)
    AMAZON,
    FLIPKART,
    PACK,
    TITLES,
    _erase_cmo_rows,
    ctx_engine,
    env,
    fake_clerk,
    seed_analysis,
)

NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"
SKU = cmo_chat.product_sku(NAME)


def titles(env, key="m0t", **extra):
    body = {"request_key": key, "sku": SKU, "product_name": NAME, "brand": "AquaNest", "attributes": [{"name": "Size", "value": "1 litre"}], "marketplaces": [AMAZON], **extra}
    r = env.post("title-sets", body)
    assert r.status_code == 200, r.text
    return r.json()["artefacts"][0]


def ctx_for(env):
    return ins.Ctx(env.tenant, date(2026, 10, 30), None)


def choose(env, text):
    first = ins.start("cmo.approve_title", ctx_for(env))
    assert isinstance(first, ins.Ask), first
    done = ins.advance(first.card, option_key=None, text=text, ctx=ctx_for(env))
    assert isinstance(done, ins.Done), done
    return done.inputs


# ---------------------------------------------------------------- M0.1 identity and saved facts
def test_what_the_seller_confirmed_is_saved_against_the_product_and_found_again_next_time(env):
    titles(env)
    answers, canonical = cmo_chat.saved_answers(env.tenant, "AquaNest bottle")  # a loose name in a later conversation
    assert canonical == NAME and answers == {"fact_brand": "AquaNest", "fact_size": "1 litre"}
    assert env.n("seller_fact", "sku = :s", s=SKU) >= 3


def test_a_chat_made_result_appears_on_the_dashboard_under_its_product(env):
    titles(env)
    [product] = cmo_showcase_repo.products(env.tenant, q=None, limit=10)
    assert product["sku"] == SKU and product["label"] == NAME and product["counts"] == {AMAZON: 1}


def test_another_tenant_sees_none_of_it(env):
    titles(env)
    other, _headers = env.other_tenant()
    assert cmo_chat.saved_answers(other, NAME) == ({}, None)
    assert cmo_chat_repo.saved_facts(other, SKU) == [] and cmo_chat_repo.product_names(other) == []
    assert cmo_chat_repo.recent_title_sets(other) == [] and cmo_chat_repo.approved_titles(other) == []


# ---------------------------------------------------------------- M0.2 choosing a title in chat
def test_the_seller_picks_option_two_and_the_copy_is_grounded_on_that_approved_title(env):
    ts = titles(env)
    [chosen_set] = cmo_chat_repo.recent_title_sets(env.tenant)
    assert chosen_set["generationId"] == ts["id"] and [o["text"] for o in chosen_set["options"]] == TITLES
    inputs = choose(env, "2")
    get_registry().get("cmo.approve_title").slot_model(**inputs)  # the very model the registry validates the action's slots with
    approved = env.post("title-approvals", inputs)
    assert approved.status_code == 200 and approved.json()["approvedText"] == TITLES[1] and approved.json()["editedBySeller"] is False and approved.json()["unitsBilled"] == 0
    [row] = cmo_chat_repo.approved_titles(env.tenant)
    assert row["text"] == TITLES[1] and row["marketplace"] == AMAZON and row["label"] == NAME
    assert cmo_chat.matching_approval(env.tenant, NAME, AMAZON, TITLES[1]) == approved.json()["approvalId"]
    assert cmo_chat.matching_approval(env.tenant, NAME, AMAZON, "Some other title the seller typed") is None
    copy = env.post("listing-copy", {"request_key": "m0c", "sku": SKU, "product_name": NAME, "marketplace": AMAZON, "approval_id": approved.json()["approvalId"]})
    assert copy.status_code == 200, copy.text
    assert env.q("SELECT grounding_basis, grounding_approval_id FROM cmo_generation WHERE output_type = 'LISTING_COPY'")[0][0] == "APPROVED_TITLE"


def test_a_title_the_seller_types_is_their_own_wording_and_is_checked_against_the_marketplace_rule(env):
    titles(env)
    inputs = choose(env, "AquaNest 1 Litre Steel Bottle in Silver for Daily Use")
    ok = env.post("title-approvals", inputs)
    assert ok.status_code == 200 and ok.json()["editedBySeller"] is True and ok.json()["optionId"] is None
    too_long = env.post("title-approvals", choose(env, "AquaNest " * 30))  # the test fixture limit is 80 characters
    assert too_long.status_code == 422 and too_long.json()["detail"]["code"] == "TITLE_INVALID"
    assert env.n("cmo_title_approval") == 1


def test_choosing_makes_no_charge_and_publishes_nothing(env):
    ts = titles(env)
    before = len(env.events())
    env.post("title-approvals", {"generation_id": ts["id"], "option_id": ts["options"][0]["id"]})
    assert len(env.events()) == before  # a choice is a record, not a billed artefact


def test_two_marketplaces_each_keep_their_own_newest_set(env):
    a = titles(env, "m0a")
    f = env.post("title-sets", {"request_key": "m0f", "sku": SKU, "product_name": NAME, "marketplaces": [FLIPKART]}).json()["artefacts"][0]
    sets = {s["marketplace"]: s["generationId"] for s in cmo_chat_repo.recent_title_sets(env.tenant)}
    assert sets == {AMAZON: a["id"], FLIPKART: f["id"]}
    first = ins.start("cmo.approve_title", ctx_for(env))
    assert isinstance(first, ins.Ask) and first.card["slot"] == "title_marketplace"


# ---------------------------------------------------------------- M0.3 a confirmed photo hint
def test_a_confirmed_photo_hint_is_recorded_once_as_the_sellers_statement_for_zero_units(env):
    attrs = [{"name": "color", "value": "silver", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}]
    analysis = seed_analysis(env.cengine, env.tenant, attrs)
    done = cmo_hints.record_confirmed_hints(env.tenant, env.user_id, analysis_id=str(analysis), sku=SKU, hints=[{"attribute": "color", "value": "silver"}])
    assert done == ["color"]
    fact = env.q("SELECT fact_type, attribute_name, fact_value, image_analysis_id FROM seller_fact WHERE sku = :s", s=SKU)
    assert [tuple(r) for r in fact] == [("ATTRIBUTE", "color", "silver", analysis)]
    assert env.q("SELECT attributes FROM product_image_analysis")[0][0] == attrs  # the reading is untouched: still an unverified hint
    assert env.events() == [] and env.n("agent_run", "trigger_ref = 'cmo.confirm_image_hint'") == 1
    again = cmo_hints.record_confirmed_hints(env.tenant, env.user_id, analysis_id=str(analysis), sku=SKU, hints=[{"attribute": "color", "value": "silver"}])
    assert again == [] and env.n("seller_fact", "sku = :s", s=SKU) == 1 and env.n("agent_run", "trigger_ref = 'cmo.confirm_image_hint'") == 1


def test_a_hint_that_cannot_be_recorded_never_blocks(env):
    assert cmo_hints.record_confirmed_hints(env.tenant, env.user_id, analysis_id=str(uuid.uuid4()), sku=SKU, hints=[{"attribute": "color", "value": "silver"}]) == []
    assert cmo_hints.record_confirmed_hints(env.tenant, env.user_id, analysis_id="not-a-uuid", sku=SKU, hints=[{"attribute": "color", "value": "x"}]) == []


# ---------------------------------------------------------------- M0.4 catalog answers and "is it dishwasher safe?"
def test_a_catalog_answer_through_the_chat_inputs_is_one_unit_and_says_how_sure_each_answer_is(env):
    titles(env)
    inputs = ins._to_inputs("cmo.catalog_answer", {"product_name": NAME, "catalog_questions": "COLOR,BRAND", "fact_brand": "AquaNest"})
    inputs["request_key"] = "m0cat"
    get_registry().get("cmo.catalog_answer").slot_model(**inputs)
    r = env.post("catalog-answers", inputs)
    assert r.status_code == 200, r.text
    by = {a["attribute"]: a for a in r.json()["artefacts"][0]["attributes"]}
    assert by["BRAND"]["basis"] == "SELLER_PROVIDED" and by["BRAND"]["value"] == "AquaNest"
    assert by["COLOR"]["basis"] in ("UNKNOWN", "ESTIMATED") and by["COLOR"]["claimEligible"] is False
    assert {e[1] for e in env.events()} >= {"cmo.catalog_answer"}


def test_an_unconfirmed_property_is_not_confirmed_and_a_confirmed_one_is_the_sellers_statement(env):
    titles(env)
    no = cmo_chat.property_reply(env.tenant, "bottle", "dishwasher safe")
    assert "has not been confirmed" in no and NAME in no
    env.post("title-sets", {"request_key": "m0care", "sku": SKU, "product_name": NAME, "attributes": [{"name": "Care", "value": "dishwasher safe, top rack, tested by me"}], "marketplaces": [AMAZON]})
    yes = cmo_chat.property_reply(env.tenant, "bottle", "dishwasher safe")
    assert "you told me" in yes and "top rack" in yes


# ---------------------------------------------------------------- M0.5 history
def test_history_lists_the_chosen_titles_with_copy_and_used_counts_and_never_calls_them_published(env):
    ts = titles(env)
    opt = ts["options"][0]
    env.post("title-approvals", {"generation_id": ts["id"], "option_id": opt["id"]})
    for kind, part in (("COPIED", "TITLE"), ("COPIED", None), ("MARKED_USED", "TITLE")):  # distinct parts: identical events inside the dedup window collapse into one (by design)
        assert cmo_showcase_repo.record_usage(env.tenant, env.user_id, generation_id=uuid.UUID(ts["id"]), option_id=uuid.UUID(opt["id"]), result_part=part, kind=kind, surface="DASHBOARD", dedup_seconds=1)
    read = business_state._load_cmo_content_latest(SimpleNamespace(tenant_id=env.tenant), None)
    title, items, note = read.artefacts[0]
    assert title == "Titles you chose" and TITLES[0] in items[0] and "copied 2 times, marked used 1 time" in items[0]
    assert "does not prove" in note
    assert any(a[0].startswith("Written by Slim CMO: title options") for a in read.artefacts[1:])  # the written options are still listed after it


def test_with_nothing_chosen_history_shows_only_what_was_written(env):
    titles(env)
    read = business_state._load_cmo_content_latest(SimpleNamespace(tenant_id=env.tenant), None)
    assert all(a[0] != "Titles you chose" for a in read.artefacts)
