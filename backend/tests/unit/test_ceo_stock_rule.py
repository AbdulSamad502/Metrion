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


# --- fixes from the owner's first live run (2026-10-10): confirmations, the research report, general questions ---
def test_confirmations_are_read_by_meaning_not_by_exact_wording():
    from backend.ceo import input_session

    ok = lambda t: input_session._yes(t, None, {}) is True  # noqa: E731
    assert all(ok(t) for t in ("yes", "yes run it", "Yes, run it", "ok go ahead", "sure", "Yes please"))
    assert not any(ok(t) for t in ("no", "no don't", "yes cancel", "maybe", "not yet", "stop"))


def test_a_request_for_the_research_report_is_routed_without_asking_which_product():
    rule = next(r for r in intent_router.RULES if r.key == "pi.report")
    assert all(rule.pattern.search(t) for t in ("show me the latest product research report", "show the research report", "open the product research results"))
    assert not rule.pattern.search("find trending products in mens shoes")


def test_a_general_how_question_has_no_data_in_it_but_a_data_question_does():
    ask, data = intent_router._GENERAL_ASK, intent_router._DATA_WORDS
    assert ask.search("how should I think about pricing on Amazon?") and not data.search("how should I think about pricing on Amazon?")
    assert data.search("how can I increase my sales in September?")
    assert not ask.search("why did my profit drop?")
