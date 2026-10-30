"""CMO 3.0 M1 - the saved product profile (N-01): latest value, provenance, history, honest "not confirmed", and which questions are product questions. Pure code."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.ceo import cmo_chat, cmo_profile

D1, D2, D3 = (datetime(2026, 10, d, tzinfo=timezone.utc) for d in (10, 20, 28))
NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"


def row(kind, name, value, at=D1, photo=False):
    return {"type": kind, "name": name, "value": value, "at": at, "fromPhoto": photo}


ROWS = [
    row("ATTRIBUTE", "product_name", NAME),
    row("BRAND", None, "AquaNest"),
    row("ATTRIBUTE", "Size", "1 litre"),
    row("ATTRIBUTE", "Material", "stainless steel", D2),
    row("ATTRIBUTE", "Color", "silver", D2, photo=True),
    row("ATTRIBUTE", "Size", "1.5 litre", D3),
    row("FREE_TEXT", None, "reusable"),
]


def test_the_profile_keeps_the_latest_value_where_it_came_from_and_the_replaced_one():
    p = cmo_profile.profile_from_rows(ROWS)
    by = {a["label"]: a for a in p["attributes"]}
    assert p["name"] == NAME and by["Brand"]["value"] == "AquaNest" and by["Brand"]["source"] == "you told me"
    assert by["Size"]["value"] == "1.5 litre" and by["Size"]["history"] == [{"value": "1 litre", "at": D1}]
    assert by["Color"]["source"] == "confirmed by you from a photo reading"
    assert p["notes"][0]["value"] == "reusable"


def test_a_detail_the_seller_never_gave_is_not_confirmed_never_filled_in():
    p = cmo_profile.profile_from_rows([row("ATTRIBUTE", "product_name", NAME), row("BRAND", None, "AquaNest")])
    assert p["notConfirmed"] == ["Size", "Color", "Material"]
    assert {a["label"] for a in p["attributes"]} == {"Brand"}


def test_restating_the_same_value_is_not_a_change():
    p = cmo_profile.profile_from_rows([row("BRAND", None, "AquaNest"), row("BRAND", None, " aquanest ", D2)])
    [b] = p["attributes"]
    assert b["history"] == [] and b["at"] == D2


def test_the_text_states_every_source_and_never_claims_a_check():
    text = cmo_profile.profile_text(cmo_profile.profile_from_rows(ROWS), "x")
    assert text.startswith(f"I found your saved profile for {NAME}.") and "Metrion has not checked them" in text
    assert "Size: 1.5 litre (you told me, 2026-10-28); earlier you said 1 litre (2026-10-10)" in text
    assert "Color: silver (confirmed by you from a photo reading, 2026-10-20)" in text
    assert "insulated" not in text.casefold() and "leakproof" not in text.casefold()  # never mentioned unless the seller said it


def test_an_empty_profile_says_so():
    assert "no saved details" in cmo_profile.profile_text(cmo_profile.profile_from_rows([]), NAME)


@pytest.mark.parametrize("q,hint", [("Hi CEO, remember my AquaNest bottle?", "AquaNest bottle"), ("remember my AquaNest bottle", "AquaNest bottle"), ("What do you know about my bottle?", "bottle"),
                                    ("show me the saved profile of my steel bottle", "steel bottle"), ("Do you remember my AquaNest bottle?", "AquaNest bottle")])
def test_product_questions_are_recognised(q, hint):
    assert cmo_profile.profile_question(q) == hint


@pytest.mark.parametrize("q", ["What do you know about my business?", "what do you know about me", "remember my goal", "write titles for my bottle", "what do you know about my competitors?"])
def test_other_questions_are_not_product_questions(q):
    assert cmo_profile.profile_question(q) is None


def test_the_reply_asks_which_product_when_the_name_fits_none_or_many(monkeypatch):
    t = uuid.uuid4()
    monkeypatch.setattr(cmo_chat.cmo_chat_repo, "product_names", lambda tid: [("a-bottle", "AquaNest Bottle"), ("a-glass", "AquaNest Glass Bottle")])
    assert "Which product" in cmo_profile.profile_reply(t, "AquaNest")
    monkeypatch.setattr(cmo_chat.cmo_chat_repo, "product_names", lambda tid: [])
    assert "no saved product details" in cmo_profile.profile_reply(t, "bottle")
