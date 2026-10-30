"""CMO 3.0 M4 (pure code): which messages ask for the listing preview, the chat sentences, and the details a title should keep visible."""

from __future__ import annotations

import pytest

from backend.ceo import classifier, intent_router, question_types
from backend.ceo.plans import ACTIONS, PLAYBOOKS
from backend.services import cmo_preview


@pytest.mark.parametrize("text", ["Show my listing preview", "show me my listing preview", "Can you show a mobile preview?", "preview my titles", "show the title preview", "I want a desktop preview",
                                  "how will my titles look in search?", "How would my listing look on mobile", "Show the search preview of my listing"])
def test_these_ask_for_the_preview(text):
    assert cmo_preview.is_preview_request(text), text


@pytest.mark.parametrize("text", ["write titles for my bottle", "write a preview of my product launch", "compare these titles", "use option 2", "what do you know about my bottle", "show my profit",
                                  "generate a listing preview text", "show my selected title"])
def test_these_do_not(text):
    assert not cmo_preview.is_preview_request(text), text


def test_asking_for_the_preview_does_not_change_how_the_other_cmo_requests_route():
    cat = classifier.build_catalog(list(ACTIONS), list(PLAYBOOKS), question_types.descriptions())
    for text, key in (("write 5 titles for my bottle on amazon", "cmo.generate_title_sets"), ("compare these titles", "cmo.analyze_titles"), ("use option 2", "cmo.approve_title")):
        d = intent_router.route(text, cat)
        assert d is not None and d.key == key


def test_no_saved_titles_says_so_and_nothing_is_used_up():
    t = cmo_preview.chat_text(None)
    assert "no saved titles to preview" in t and "Nothing was used up" in t


def test_the_chat_sentence_names_the_marketplaces_that_have_titles_and_the_ones_that_do_not():
    t = cmo_preview.chat_text({"marketplaces": ["AMAZON", "FLIPKART"], "missingMarketplaces": ["MEESHO"]})
    assert "illustrative simulation" in t and "not the real marketplace page" in t and "Amazon, Flipkart" in t and "No saved titles exist yet for Meesho" in t and "Nothing is sent again" in t


def test_important_details_come_only_from_the_sellers_own_confirmed_facts():
    from slim_cmo.generation.facts import FactInput, build_fact_context
    from slim_cmo.types import SellerFactType

    ctx = build_fact_context([FactInput(SellerFactType.BRAND, "AquaNest"), FactInput(SellerFactType.ATTRIBUTE, "1 litre", "Size"), FactInput(SellerFactType.ATTRIBUTE, "steel", "Material"),
                              FactInput(SellerFactType.ATTRIBUTE, "yes", "Insulated")])
    assert cmo_preview.details_of(ctx) == {"Brand": "AquaNest", "Size": "1 litre", "Material": "steel"}
    assert cmo_preview.details_of(build_fact_context([])) == {}
