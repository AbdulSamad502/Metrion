"""Spec 6.36: the stock-question rule names the product (or the numbered idea already expanded to its name) and never guesses one."""

from __future__ import annotations

import pytest

from backend.ceo import intent_router

RULE = next(r for r in intent_router.RULES if r.key == "NEW_PRODUCT_DECISION")


@pytest.mark.parametrize(
    "text,product",
    [
        ("is Leather Formal Shoes worth stocking?", "Leather Formal Shoes"),
        ("Is the Bamboo Toothbrush Pack worth buying", "Bamboo Toothbrush Pack"),
        ("Should I stock the Cotton Kurti Set or not?", "Cotton Kurti Set"),
        ("should I import yoga mats?", "yoga mats"),
    ],
)
def test_a_named_product_is_taken_as_the_sku_text(text, product):
    assert RULE.pattern.search(text) and intent_router._slots(RULE, text) == {"product": product}


@pytest.mark.parametrize("text", ["find products worth stocking", "is this worth stocking?", "should I stock it?", "what are products worth buying"])
def test_no_named_product_means_the_rule_does_not_decide(text):
    assert intent_router._slots(RULE, text) == {}
