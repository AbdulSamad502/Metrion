"""Routing tolerance for misspellings, description+bullets -> listing copy pack, the A/B/C news question, and the description length target."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from slim_cmo.generation.prompts import description_guidance, description_target

from backend.ceo import input_session as ins
from backend.ceo import intent_router as ir


def _first(text: str) -> str | None:
    t = " ".join(text.split())
    for rule in ir.RULES:
        if rule.pattern.search(t) and not (rule.kind == "PLAYBOOK" and not ir._slots(rule, t)):
            return rule.key
    return None


@pytest.mark.parametrize("text,key", [
    ("now give me the discription also of this product", "cmo.generate_description"),
    ("write a descripton for my steel bottle", "cmo.generate_description"),
    ("give me bulletpoints for my bottle", "cmo.generate_bullets"),
    ("write key words for my bottle", "cmo.generate_keywords"),
    ("generate hastags for my bottle", "cmo.generate_hashtags"),
    ("write titels for my bottle", "cmo.generate_title_sets"),
    ("give me description and bullet points together", "cmo.generate_listing_copy"),
    ("write bullets and description for my bottle", "cmo.generate_listing_copy"),
])
def test_misspelling_and_combined_routing(text: str, key: str) -> None:
    assert _first(text) == key


def test_a_question_about_bullets_and_descriptions_is_not_a_request() -> None:
    assert _first("what makes good bullets and a good description") != "cmo.generate_listing_copy"


@pytest.mark.parametrize("raw,kind", [("A", "NICHE"), ("niche", "NICHE"), ("b", "TRENDING"), ("everyday trending news", "TRENDING"), ("C", "BOTH"), ("both", "BOTH")])
def test_news_kind_parser(raw: str, kind: str) -> None:
    assert ins._news_kind(raw, None, {}) == kind  # type: ignore[arg-type]


def test_news_kind_rejects_other_text() -> None:
    assert isinstance(ins._news_kind("hmm", None, {}), ins.Reject)  # type: ignore[arg-type]


def test_trending_needs_no_niche_and_maps_to_generic_news_section(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ins, "_has_confirmed_niche", lambda ctx: False)
    ctx = ins.Ctx(uuid.uuid4(), date(2026, 10, 13), None)
    got = {"news_kind": "TRENDING"}
    assert ins.field_names("cmo.market_trends", ctx, got) == []
    assert ins.resume_ask("cmo.market_trends", ctx, got).inputs["sections"] == ["MARKET_NEWS"]  # type: ignore[union-attr]
    assert ins.field_names("cmo.market_trends", ctx, {"news_kind": "BOTH"}) == ["niche"]
    monkeypatch.setattr(ins, "_has_confirmed_niche", lambda ctx: True)
    assert ins.field_names("cmo.market_trends", ctx, {"news_kind": "NICHE"}) == []


def test_description_target_is_computed_from_the_limit() -> None:
    assert description_target(2000) == (1100, 1700)
    assert description_target(None) is None
    assert "1100 to 1700 characters" in description_guidance(2000) and "never more than 2000" in description_guidance(2000)
