"""CMO 3.0 M1 through the real CEO chat and Postgres (N-01, R-04): the saved profile comes back in a NEW conversation with provenance, history and honest gaps, and never crosses tenants."""

from __future__ import annotations

import os

import pytest

from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat, cmo_counts, say  # noqa: F401
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def new_conversation(c, headers=None):
    return c.client.post("/api/v1/ceo/investigations", json={"title": "Later"}, headers=headers or c.env.headers).json()["investigationId"]


def written(c):
    inv, planned = ask_for_titles(c)
    assert approve(c, inv, planned["plan"]).json()["status"] == "DELIVERED"


def test_the_profile_is_found_in_a_new_conversation_with_its_source_and_gaps(chat):
    c = chat
    written(c)
    later = new_conversation(c)
    r = say(c, later, "Hi CEO, remember my steel bottle?")
    assert r["status"] == "DELIVERED", r
    a = r["answer"]
    assert "I found your saved profile for steel bottle" in a and "Metrion has not checked them" in a
    assert "Not confirmed yet: Brand, Size, Color, Material" in a  # the seller skipped every detail: nothing is invented
    assert cmo_counts(c)["model_calls"] == 1  # only the title run: the profile came from saved facts, not a model


def test_a_changed_statement_shows_the_new_value_and_keeps_the_old_one_in_history(chat):
    c, e = chat, chat.env
    written(c)
    for brand in ("AquaKeep", "AquaNest"):
        r = e.post("title-sets", {"request_key": f"b-{brand}", "sku": "steel-bottle", "product_name": "steel bottle", "brand": brand, "marketplaces": ["AMAZON"]})
        assert r.status_code == 200, r.text
    a = say(c, new_conversation(c), "what do you know about my steel bottle?")["answer"]
    assert "Brand: AquaNest (you told me" in a and "earlier you said AquaKeep" in a


def test_another_tenant_never_sees_the_profile(chat):
    c = chat
    written(c)
    _other, headers = c.env.other_tenant()
    a = say(c, new_conversation(c, headers), "remember my steel bottle?", headers=headers)["answer"]
    assert "no saved product details" in a and "steel bottle" in a and "Brand" not in a


def test_a_question_about_the_business_is_not_a_product_profile_question(chat):
    c = chat
    written(c)
    a = say(c, new_conversation(c), "What do you know about my business?")["answer"]
    assert "saved profile" not in a
