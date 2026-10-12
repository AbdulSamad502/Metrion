"""Workstream A2 verification (unit): rule routing for the cases the combined campaign names. No model, no database."""

from __future__ import annotations

import pytest

from tests.unit.test_ceo_campaign_routing_rules import decide


@pytest.mark.parametrize(
    "text,key",
    [
        ("Show me the latest product research report", "pi.report"),
        ("Open the research report", "pi.report"),
        ("What did the product research find?", "QT_PRODUCT_IDEAS"),
        ("What product ideas did you find for me?", "QT_PRODUCT_IDEAS"),
        ("Find new trending products in kitchenware", "pi.discover"),
        ("Suggest products to sell on Flipkart", "pi.discover"),
    ],
)
def test_existing_research_is_read_back_and_only_a_new_request_discovers(text, key):
    rule, _ = decide(text)
    assert rule is not None and rule.key == key


@pytest.mark.parametrize(
    "text",
    [
        "Summarize my competitor's product reviews",
        "Research my competitor's best selling products",
        "What are Acme's top selling products?",
        "Which of my products sold the most last month?",
        "What are my best selling products?",
        "Which of my own products sell best?",
    ],
)
def test_competitor_specific_and_seller_specific_product_questions_never_start_market_discovery(text):
    rule, _ = decide(text)
    assert rule is None or rule.key != "pi.discover", text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Find trending products in the kitchenware niche under 1500 on Amazon", {"product": "kitchenware", "amount": "1500", "marketplace": "Amazon"}),
        ("Find products in the pet supplies category with a budget of Rs 2,000 on Flipkart", {"product": "pet supplies", "amount": "Rs 2,000", "marketplace": "Flipkart"}),
        ("My niche is yoga mats, find trending products under 999", {"product": "yoga mats", "amount": "999"}),
    ],
)
def test_the_niche_and_the_budget_are_kept_exactly_as_the_seller_said_them(text, expected):
    rule, got = decide(text)
    assert rule is not None and rule.key == "pi.discover"
    for k, v in expected.items():
        assert got.get(k) == v, (k, got)


@pytest.mark.parametrize("text", ["Find products", "Competitors?", "What about my competitors?", "Do the thing", "profit"])
def test_ambiguous_requests_are_never_turned_into_an_action_with_invented_arguments(text):
    rule, got = decide(text)
    if rule is not None:  # a rule may recognise the verb, but it must not have invented a niche, price, competitor or product
        assert set(got) <= {"marketplace"}, (text, got)
