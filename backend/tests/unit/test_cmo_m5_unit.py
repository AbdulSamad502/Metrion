"""CMO 3.0 M5 (pure code): which messages ask for buyer questions / readiness, how a seller's own answer is read, and the chat sentence."""

from __future__ import annotations

import pytest

from backend.services import cmo_readiness


@pytest.mark.parametrize("text", ["What questions will buyers ask?", "what questions will customers ask about my bottle", "Show me the buyer questions for my AquaNest bottle", "what will customers want to know",
                                  "What questions might shoppers ask?"])
def test_these_ask_for_buyer_questions(text):
    assert cmo_readiness.request_kind(text) == "questions", text


@pytest.mark.parametrize("text", ["Is my AquaNest bottle ready to list?", "is my steel bottle ready to sell", "Show my listing readiness", "readiness checklist please", "What's missing before I list my bottle?",
                                  "Can I list my AquaNest bottle?", "listing readiness score"])
def test_these_ask_for_readiness(text):
    assert cmo_readiness.request_kind(text) == "readiness", text


@pytest.mark.parametrize("text", ["write buyer questions for my bottle", "generate a readiness checklist", "show my listing preview", "what do you know about my bottle", "compare these titles", "is my profit up?",
                                  "how many questions did I ask"])
def test_these_do_not(text):
    assert cmo_readiness.request_kind(text) is None, text


def test_the_product_words_are_taken_from_the_request_and_business_words_are_not_products():
    assert cmo_readiness.product_hint("Is my AquaNest bottle ready to list?") == "AquaNest bottle"
    assert cmo_readiness.product_hint("What's missing before I list my steel bottle?") == "steel bottle"
    assert cmo_readiness.product_hint("What questions will buyers ask?") is None
    assert cmo_readiness.product_hint("show my listing readiness") is None


def test_the_sellers_own_answer_must_name_a_product_and_a_known_question():
    assert cmo_readiness.parse_statement("For my AquaNest bottle, dishwasher safe is: yes, top rack, tested") == ("AquaNest bottle", "Dishwasher safe", "yes, top rack, tested")
    assert cmo_readiness.parse_statement("for my steel bottle, Warranty is: 1 year from the seller") == ("steel bottle", "Warranty", "1 year from the seller")
    assert cmo_readiness.parse_statement("For my bottle, the colour of the moon is: blue") is None  # not a known question: nothing is saved
    assert cmo_readiness.parse_statement("dishwasher safe is: yes") is None and cmo_readiness.parse_statement("What is it made of") is None


def test_the_confirmation_says_it_is_the_sellers_own_unchecked_statement_and_a_not_known_answer_is_not_claimed():
    yes = cmo_readiness.saved_text("Dishwasher safe", "yes, tested")
    assert "your own statement" in yes and "has not checked it" in yes and "exactly as you said it" in yes
    no = cmo_readiness.saved_text("Insulated", "not tested")
    assert "will not claim it" in no and "not confirmed" in no


def test_the_chat_sentence_states_counts_the_marketplace_score_with_its_coverage_and_the_verdict():
    card = {"view": "readiness", "defaultMarketplace": "AMAZON", "questions": {"counts": {"CONFIRMED": 4, "NOT_CONFIRMED": 9, "SELLER_UNKNOWN": 1}, "questions": [0] * 14},
            "readiness": {"marketplaces": [{"marketplace": "AMAZON", "score": {"status": "ASSESSED", "score": 62, "assessablePoints": 95}, "verdictText": "Not ready: some requirements are still missing."}]}}
    t = cmo_readiness.chat_text(card)
    assert "4 of 14 questions are answered" in t and "9 are NOT CONFIRMED" in t and "readiness 62/100 on 95 of 100 assessable points" in t and "Not ready" in t and "Nothing is used up and nothing is published" in t
    card["readiness"]["marketplaces"][0]["score"] = {"status": "NOT_ASSESSED", "assessablePoints": 20}
    assert "no readiness score yet" in cmo_readiness.chat_text(card)
