"""Owner-test fixes for the CEO -> CMO chat: the marketplace is always asked, the high-value optional details are asked one at a time (skippable, inside the 8-question limit),
details given earlier are carried and not re-asked, the plan card is compact while the stored plan stays complete, a test-fixture length rule is never presented as a real one,
a failed artefact says why, trend items carry their source and date, and news phrasings reach the market-research flow. Pure code: no model, no database."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.ceo import approval, evidence
from backend.ceo import cmo_delegation as cd
from backend.ceo import input_session as ins
from backend.ceo import intent_router as ir

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
CTX = ins.Ctx(uuid.uuid4(), T0.date(), None)


def ask_for(key, **prefill):
    out = ins.start(key, CTX, prefill=prefill)
    assert isinstance(out, ins.Ask), out
    return out


# ------------------------------------------------------------------------------------------------ problem 2: the marketplace is asked, never guessed
NOUNS = [
    ("cmo.generate_title_sets", "titles", "marketplaces"),
    ("cmo.generate_description", "a description", "marketplace"),
    ("cmo.generate_bullets", "bullets", "marketplace"),
    ("cmo.generate_keywords", "keywords", "marketplace"),
    ("cmo.generate_hashtags", "hashtags", "marketplace"),
]


@pytest.mark.parametrize(("key", "noun", "slot"), NOUNS)
def test_no_marketplace_in_the_message_asks_exactly_that_question(key, noun, slot):
    out = ask_for(key, product="steel water bottle")
    if key == "cmo.generate_title_sets":  # the category (skippable) is asked before the marketplace
        assert out.card["slot"] == "category_hint"
        out = ins.advance(out.card, option_key=None, text="skip", ctx=CTX)
    assert out.card["slot"] == slot
    assert f"Which marketplace do you want {noun} for (Amazon, Flipkart, Meesho)?" in out.text
    assert "marketplace" not in out.card["pending"]["collected"] and "marketplaces" not in out.card["pending"]["collected"]  # nothing defaulted


@pytest.mark.parametrize(("key", "noun", "slot"), NOUNS)
def test_a_marketplace_the_seller_named_skips_the_question(key, noun, slot):
    out = ask_for(key, product="steel water bottle", marketplace="Amazon")
    assert out.card["slot"] != slot
    assert "Which marketplace" not in out.text


# ------------------------------------------------------------------------------------------------ problem 3c: optional high-value details
def walk(key, answers, prefill):
    out = ask_for(key, **prefill)
    slots = []
    for a in answers:
        slots.append(out.card["slot"])
        out = ins.advance(out.card, option_key=None, text=a, ctx=CTX)
        if not isinstance(out, ins.Ask):
            break
    return slots, out


def test_titles_ask_the_five_details_one_at_a_time_each_skippable():
    slots, out = walk("cmo.generate_title_sets", ["skip"] * 8, {"product": "steel water bottle", "marketplace": "Amazon"})
    assert slots[:6] == ["category_hint", "fact_brand", "fact_size", "fact_key_features", "fact_main_use", "fact_search_keywords"]
    assert isinstance(out, ins.Done) and "brand" not in out.inputs and "attributes" not in out.inputs  # skipped = absent, never a default


def test_every_detail_question_offers_skip():
    out = ask_for("cmo.generate_title_sets", product="steel water bottle", marketplace="Amazon")
    out = ins.advance(out.card, option_key=None, text="skip", ctx=CTX)  # category
    for slot in ("fact_brand", "fact_size", "fact_key_features", "fact_main_use", "fact_search_keywords"):
        assert out.card["slot"] == slot
        assert any(o["label"] == "Skip" for o in out.card["options"])
        out = ins.advance(out.card, option_key=None, text="skip", ctx=CTX) if slot != "fact_search_keywords" else out


def test_answered_details_become_the_sellers_own_statements():
    _, out = walk("cmo.generate_title_sets", ["skip", "Acme", "1 litre", "double wall, wide mouth", "gym", "steel bottle, flask"], {"product": "steel water bottle", "marketplace": "Amazon"})
    assert isinstance(out, ins.Done)
    assert out.inputs["brand"] == "Acme"
    assert {"name": "Size", "value": "1 litre"} in out.inputs["attributes"]
    assert {"name": "Key Features", "value": "double wall, wide mouth"} in out.inputs["attributes"]
    assert {"name": "Main Use", "value": "gym"} in out.inputs["attributes"]
    assert {"name": "Search Keywords", "value": "steel bottle, flask"} in out.inputs["attributes"]


def test_details_count_inside_the_question_limit_and_never_stop_a_task_at_it(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "4")
    first = cd.begin(ask_for("cmo.generate_title_sets"), action_key="cmo.generate_title_sets", now=T0)  # 1 product
    steps = [("steel water bottle", None), ("skip", None), ("Amazon", None)]  # 2 category, 3 marketplaces
    ask = first
    for text, _ in steps:
        ask = cd.advance(ask.card, option_key=None, text=text, ctx=CTX, now=T0)
        assert isinstance(ask, ins.Ask)
    assert ask.card["slot"] == "fact_brand"  # the 4th and last question allowed
    out = cd.advance(ask.card, option_key=None, text="Acme", ctx=CTX, now=T0)
    assert isinstance(out, ins.Done) and out.inputs["brand"] == "Acme"  # only skippable details remain: go on, do not stop


def test_a_required_question_still_stops_at_the_limit(monkeypatch):
    monkeypatch.setenv("CMO_DELEGATION_MAX_QUESTIONS", "2")
    ask = cd.begin(ask_for("cmo.generate_bullets"), action_key="cmo.generate_bullets", now=T0)
    ask = cd.advance(ask.card, option_key=None, text="steel water bottle", ctx=CTX, now=T0)
    out = cd.advance(ask.card, option_key=None, text="Amazon", ctx=CTX, now=T0)  # the seller's title is required and would be the 3rd question
    assert isinstance(out, ins.Ask) and out.card["delegation"]["status"] == "LIMIT"


def test_bullets_ask_for_brand_size_and_features_after_the_title():
    slots, out = walk("cmo.generate_bullets", ["Steel Water Bottle 1L", "skip", "skip", "skip"], {"product": "steel water bottle", "marketplace": "Amazon"})
    assert slots == ["seller_title", "fact_brand", "fact_size", "fact_key_features"] and isinstance(out, ins.Done)


# ------------------------------------------------------------------------------------------------ problem 4b: confirmed earlier, not asked again
def earlier_plan(**slots):
    return {"plan": {"legs": [{"action_key": "cmo.generate_title_sets", "slots": {"product_name": "Steel Water Bottle", **slots}}]}}


def test_details_given_for_the_same_product_are_carried_and_not_asked_again():
    plans = [earlier_plan(brand="Acme", attributes=[{"name": "Size", "value": "1 litre"}, {"name": "Key Features", "value": "double wall"}], seller_title="Acme Bottle 1L")]
    carry = cd.carried_facts("cmo.generate_bullets", "steel water bottle", plans)
    assert carry == {"fact_brand": "Acme", "fact_size": "1 litre", "fact_key_features": "double wall", "seller_title": "Acme Bottle 1L"}
    out = ins.start("cmo.generate_bullets", CTX, prefill={"product": "steel water bottle", "marketplace": "Amazon"}, carry=carry)
    assert isinstance(out, ins.Done) and out.inputs["brand"] == "Acme" and out.inputs["seller_title"] == "Acme Bottle 1L"


def test_a_different_product_carries_nothing():
    assert cd.carried_facts("cmo.generate_bullets", "yoga mat", [earlier_plan(brand="Acme")]) == {}
    assert cd.carried_facts("cmo.market_trends", "steel water bottle", [earlier_plan(brand="Acme")]) == {}
    assert cd.carried_facts("cmo.generate_bullets", None, [earlier_plan(brand="Acme")]) == {}


# ------------------------------------------------------------------------------------------------ problem 1: compact card, complete stored plan
SLOTS = {"product_name": "Steel Water Bottle", "marketplaces": ["AMAZON"], "brand": "Acme", "attributes": [{"name": "Size", "value": "1 litre"}]}


def test_the_compact_card_is_three_to_five_short_lines():
    lines = cd.compact_lines("cmo.generate_title_sets", SLOTS)
    assert 3 <= len(lines) <= 5 and all(len(l) <= 160 for l in lines)
    text = " ".join(lines)
    assert "Write listing titles for Steel Water Bottle on Amazon" in text and "Brand: Acme" in text and "Size: 1 litre" in text
    assert "Cost: 1 CMO unit, only if it completes." in text and "Valid for 30 minutes." in text
    assert "recommend-only" not in text and "Typing" not in text and "yes" not in text.lower().replace("youtube", "")  # the long wording and the yes-warning are not repeated here


def test_a_two_marketplace_title_set_says_two_units():
    assert "Cost: 2 CMO units" in " ".join(cd.compact_lines("cmo.generate_title_sets", {**SLOTS, "marketplaces": ["AMAZON", "FLIPKART"]}))


def test_the_full_details_stay_complete():
    details, units = cd.plan_extras("cmo.generate_title_sets", SLOTS)
    text = "\n".join(details)
    assert "recommend-only" in text and "Product facts you confirmed" in text and "Quota effect: 1 CMO unit" in text and units == {"cmo.generate_title_sets": 1}


def test_thin_input_is_flagged_on_the_card_and_in_the_details():
    thin = {"product_name": "Steel Water Bottle", "marketplaces": ["AMAZON"]}
    lines = cd.compact_lines("cmo.generate_title_sets", thin)
    assert any("Thin input - add brand/size/features for stronger titles." in l for l in lines) and len(lines) <= 5
    assert "Thin input - add brand/size/features for stronger titles." in cd.plan_extras("cmo.generate_title_sets", thin)[0]
    assert not any("Thin input" in l for l in cd.compact_lines("cmo.generate_title_sets", SLOTS))


def test_the_approval_note_is_one_short_line_with_the_plan_title():
    plan = {"title": cd.plan_title("cmo.generate_title_sets", SLOTS), "summary_text": "Plan: run X.\n" + "long " * 200}
    note = approval.approved_note(plan)
    assert note == "You approved: Write listing titles for Steel Water Bottle on Amazon" and "\n" not in note
    assert approval.approved_note({}) == approval.APPROVED_NOTE


def test_the_chat_lead_states_the_approve_rule_once_and_briefly():
    assert "Nothing runs until you press Approve" in approval.PLAN_MESSAGE_LEAD and "typing yes does not approve" in approval.PLAN_MESSAGE_LEAD
    assert len(approval.PLAN_MESSAGE_LEAD) < 140


# ------------------------------------------------------------------------------------------------ problem 3a/4a: honest result wording
def test_a_test_fixture_rule_is_never_presented_as_a_marketplace_rule():
    fixture = {"constraint": {"sourceUrl": "https://example.invalid/test-fixture-dev", "verifiedAt": "2026-10-13T00:00:00+00:00", "ruleKind": "TEST_FIXTURE"}}
    note = evidence._cmo_rule_note(fixture)
    assert "NOT a verified marketplace rule" in note and "Fitted to the marketplace rule" not in note
    legacy = {"constraint": {"sourceUrl": "https://example.invalid/test-fixture-dev", "verifiedAt": "2026-10-13T00:00:00+00:00", "ruleKind": None}}  # stored before the kind was recorded
    assert "NOT a verified marketplace rule" in evidence._cmo_rule_note(legacy)
    real = {"constraint": {"sourceUrl": "https://sellercentral.amazon.in/rules", "verifiedAt": "2026-10-13T00:00:00+00:00", "ruleKind": "VERIFIED"}}
    assert evidence._cmo_rule_note(real) == "Fitted to the marketplace rule from https://sellercentral.amazon.in/rules, checked 2026-10-13T00:00:00+00:00"


def test_thin_input_warning_is_in_the_result():
    note = evidence._cmo_rule_note({"outputType": "TITLE_SET", "thinInput": True, "constraint": {}})
    assert note == "Thin input - add brand/size/features for stronger titles."


@pytest.mark.parametrize(("code", "needle"), [
    ("VALIDATION_FAILED", "without adding things you did not tell me"), ("UNPARSEABLE_OUTPUT", "could not be read"), ("PROVIDER_ERROR", "did not answer"),
    ("CONSTRAINT_BLOCKED", "no verified marketplace rule"), ("OUTPUT_TOO_LARGE", "unusably large"),
])
def test_a_failed_artefact_says_why_without_internals(code, needle):
    text = evidence._cmo_failure_text("Bullet points", " for Amazon", {"code": code, "reason": "attempts=2 violations={'TOO_FEW': 1}", "missingFacts": []})
    assert text.startswith("Bullet points for Amazon could not be written: ") and needle in text
    assert "attempt" not in text and "TOO_FEW" not in text


def test_missing_facts_are_still_named():
    assert evidence._cmo_failure_text("Title options", " for Flipkart", {"code": "NEEDS_FACTS", "missingFacts": ["material"]}) == "Title options for Flipkart could not be written: more detail is needed about material."


def test_trend_items_carry_their_source_and_publication_date():
    f = {"sources": [{"url": "https://news.example/a", "title": "Fee change", "published_at": "2026-10-09T08:00:00+00:00"}, {"url": "https://news.example/b", "title": "", "published_at": None}]}
    text = evidence._trend_sources(f)
    assert "Fee change - https://news.example/a (published 2026-10-09)" in text and "https://news.example/b (published date not given)" in text
    assert evidence._trend_sources({"sources": []}) == ""


# ------------------------------------------------------------------------------------------------ problem 4c: news reaches market research
def decide(text: str):
    t = " ".join(text.split())
    for rule in ir.RULES:
        if rule.pattern.search(t) and not (rule.kind == "PLAYBOOK" and not ir._slots(rule, t)):
            return rule.key
    return None


@pytest.mark.parametrize("text", [
    "tell me the current news of the ecommerce", "latest news", "what is happening in ecommerce", "ecommerce updates", "Amazon news", "Flipkart news today",
    "any news on Meesho", "market news", "what's going on in Amazon", "latest ecommerce news please", "news about online sellers in india",
])
def test_news_phrasings_start_the_market_research_flow(text):
    assert decide(text) == "cmo.market_trends"


@pytest.mark.parametrize(("text", "expected"), [
    ("What titles did we write?", "QT_LISTING_CONTENT"), ("Where am I losing money?", "QT_LEAKS"), ("Write hashtags for my steel water bottle on Amazon", "cmo.generate_hashtags"),
    ("Write a title for my steel bottle on Flipkart", "cmo.generate_title_sets"), ("what's my profit last month", "QT_PROFIT_BY_PERIOD"), ("any updates?", None),
    ("amazon update my listing", None),
])
def test_news_routing_does_not_take_over_other_requests(text, expected):
    assert decide(text) == expected
