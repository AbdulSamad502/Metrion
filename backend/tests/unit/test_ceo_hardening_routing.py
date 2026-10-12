"""Hardening Fix 2 (unit): a price SCENARIO is not a competitor price LIST, and a question ABOUT hashtags is not a request to GENERATE them.

Deterministic, no model, no database. `decide` is what `intent_router.route` does with the rules alone (no catalog filtering, which is a separate, tested layer)."""

from __future__ import annotations

import pytest

from backend.ceo import intent_router as ir
from tests.unit.test_ceo_campaign_routing_rules import decide


# ---- A. price scenario vs competitor price list -------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,slots",
    [
        ("Show me the competitor price scenario at 499", {"amount": "499"}),
        ("Show me a price scenario for Acme at 499", {"competitor": "Acme", "amount": "499"}),
        ("Run a price scenario against Acme at Rs 1,299", {"competitor": "Acme", "amount": "Rs 1,299"}),
        ("What would my price positioning look like versus Acme at ₹750?", {"competitor": "Acme", "amount": "₹750"}),
        ("competitor price scenario", {}),  # essential inputs missing: nothing is invented, the plan asks
    ],
)
def test_a_price_scenario_request_routes_to_the_scenario_action_with_only_what_was_said(text, slots):
    rule, got = decide(text)
    assert rule is not None and rule.key == "ci.request_price_scenario"
    assert got == slots


@pytest.mark.parametrize(
    "text",
    [
        "What are my competitors charging?",
        "Show me competitor prices",
        "How much are my competitors charging for steel bottles?",
        "What's the competitors' price on yoga mats?",
    ],
)
def test_the_competitor_price_list_questions_still_read_the_saved_prices(text):
    rule, _ = decide(text)
    assert rule is not None and rule.key == "QT_COMPETITORS_PRICES"


def test_a_scenario_with_a_margin_is_still_the_price_impact_playbook():
    rule, _ = decide("Acme dropped to Rs 499, what happens to my margin?")
    assert rule is not None and rule.key == "COMPETITOR_PRICE_IMPACT"


# ---- B. hashtags: explicit generation only ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Generate hashtags for my product.",
        "Give me 20 hashtags for this product.",
        "Write hashtags for my steel water bottle on Amazon",
        "Suggest some hashtags for my yoga mat",
        "I need hashtags for my new bottle",
        "hashtags for my yoga mat",
    ],
)
def test_explicit_hashtag_requests_route_to_generation(text):
    rule, _ = decide(text)
    assert rule is not None and rule.key == "cmo.generate_hashtags"


@pytest.mark.parametrize(
    "text",
    [
        "Tell me about hashtags.",
        "What makes a good product hashtag?",
        "What is a hashtag?",
        "How do hashtags help my listing?",
        "Why should I use hashtags?",
        "Explain how hashtags work on Instagram",
        "Were those hashtags any good?",  # an ambiguous follow-up about earlier output
        "Are the hashtags you suggested relevant?",
    ],
)
def test_informational_or_follow_up_hashtag_questions_never_start_generation(text):
    rule, _ = decide(text)
    assert rule is None or rule.key != "cmo.generate_hashtags", text


@pytest.mark.parametrize("text", ["Tell me about hashtags.", "What makes a good product hashtag?", "Explain how hashtags work on Instagram"])
def test_an_informational_question_is_answered_as_general_guidance(text):
    from backend.ceo import classifier, question_types
    from backend.ceo.plans import ACTIONS, PLAYBOOKS

    cat = classifier.build_catalog(list(ACTIONS), list(PLAYBOOKS), question_types.descriptions())
    d = ir.route(text, cat)
    assert d is not None and d.route == "ADVISORY" and "RULE_ROUTED" in d.flags


def test_earlier_hashtags_can_still_be_read_back():
    rule, _ = decide("Show me the hashtags you wrote earlier")
    assert rule is not None and rule.key == "QT_LISTING_CONTENT"
