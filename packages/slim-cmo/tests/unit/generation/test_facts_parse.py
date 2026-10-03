"""facts.py (decision 2) and parse.py (untrusted provider output)."""

from __future__ import annotations

import json

import pytest

from slim_cmo.claims import Attribute, EligibilityReason
from slim_cmo.generation.facts import FactInput, build_fact_context, image_attributes
from slim_cmo.generation.parse import ParseFailure, Parsed, parse_reply
from slim_cmo.generation.safety import screen_fact_names
from slim_cmo.generation.safety_limits import PARSE_SAFETY_MAX_LIST_ITEMS
from slim_cmo.types import AttributeBasis as B
from slim_cmo.types import SellerFactType as F
from slim_cmo.types import TrustState as T

from .helpers import at


def names(ctx):
    return {a.name: a.value for a in ctx.eligible}


class TestFactSelection:
    def test_target_price_and_niche_never_feed_copy_and_the_price_value_is_not_read(self):
        ctx = build_fact_context([
            FactInput(F.TARGET_PRICE, "49900"), FactInput(F.NICHE, "water bottles"), FactInput(F.BRAND, "AquaKeep"),
        ])
        assert names(ctx) == {"brand": "AquaKeep"}
        assert "49900" not in ctx.allowed_context and "49900" not in " ".join(ctx.notes)
        assert {e.split(":")[0] for e in ctx.excluded} == {"TARGET_PRICE", "NICHE"}

    def test_latest_row_wins_per_type_and_attribute_name(self):
        ctx = build_fact_context([
            FactInput(F.ATTRIBUTE, "plastic", "Material", provided_at=at(1)),
            FactInput(F.ATTRIBUTE, "steel", " material ", provided_at=at(5)),
            FactInput(F.ATTRIBUTE, "copper", "material", provided_at=at(3)),
            FactInput(F.ATTRIBUTE, "red", "colour", provided_at=at(1)),
        ])
        assert names(ctx) == {"material": "steel", "colour": "red"}

    def test_a_dated_row_beats_an_undated_one_and_ties_go_to_the_later_row(self):
        ctx = build_fact_context([FactInput(F.BRAND, "Old", provided_at=None), FactInput(F.BRAND, "New", provided_at=at(2))])
        assert names(ctx) == {"brand": "New"}
        ctx = build_fact_context([FactInput(F.BRAND, "First"), FactInput(F.BRAND, "Second")])
        assert names(ctx) == {"brand": "Second"}

    def test_free_text_is_context_only_never_a_structured_attribute(self):
        ctx = build_fact_context([FactInput(F.FREE_TEXT, "my customers love it, holds 900 ml"), FactInput(F.FREE_TEXT, "gift ready")])
        assert ctx.eligible == () and set(ctx.notes) == {"my customers love it, holds 900 ml", "gift ready"}
        assert ctx.allowed_context == ""  # so a number that exists only in a note is an UNSUPPORTED number

    def test_free_text_with_price_tax_or_contact_content_is_dropped(self):
        ctx = build_fact_context([
            FactInput(F.FREE_TEXT, "only Rs. 499 today"), FactInput(F.FREE_TEXT, "18% GST included"),
            FactInput(F.FREE_TEXT, "call me on 9876543210"), FactInput(F.FREE_TEXT, "sturdy and light"),
        ])
        assert ctx.notes == ("sturdy and light",)
        assert sum(1 for e in ctx.excluded if e.endswith("BLOCKED_CONTENT")) == 3

    def test_price_named_attributes_are_excluded(self):
        ctx = build_fact_context([FactInput(F.ATTRIBUTE, "499", "price"), FactInput(F.ATTRIBUTE, "600", "MRP"), FactInput(F.ATTRIBUTE, "steel", "material")])
        assert names(ctx) == {"material": "steel"}

    def test_ineligible_attributes_are_kept_only_for_leak_detection(self):
        hint = Attribute("color", "matte blue", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT)
        est = Attribute("weight", "350 g", B.ESTIMATED)
        passed = Attribute("shape", "round", B.IMAGE_OBSERVED, T.EVAL_PASSED)
        ctx = build_fact_context([FactInput(F.BRAND, "AquaKeep")], [hint, est, passed])
        assert {a.name for a in ctx.eligible} == {"brand", "shape"}
        assert {a.name: r for a, r in ctx.ineligible} == {
            "color": EligibilityReason.UNVERIFIED_IMAGE_HINT, "weight": EligibilityReason.ESTIMATED}

    def test_image_attributes_fail_closed_on_an_unrecognised_basis(self):
        attrs = image_attributes([{"name": "x", "value": "y", "basis": "TOTALLY_NEW", "trust_state": "EVAL_PASSED"}])
        ctx = build_fact_context([], attrs)
        assert ctx.eligible == () and ctx.ineligible[0][1] is EligibilityReason.UNRECOGNISED_BASIS

    def test_deterministic_attribute_order(self):
        a = build_fact_context([FactInput(F.BRAND, "B"), FactInput(F.ATTRIBUTE, "x", "zeta"), FactInput(F.ATTRIBUTE, "y", "alpha")])
        b = build_fact_context([FactInput(F.ATTRIBUTE, "y", "alpha"), FactInput(F.ATTRIBUTE, "x", "zeta"), FactInput(F.BRAND, "B")])
        assert [x.name for x in a.eligible] == [x.name for x in b.eligible]


class TestParse:
    CT = {"titles": list}

    def test_plain_json_and_code_fences_are_accepted(self):
        body = json.dumps({"titles": ["a", "b"]})
        for raw in (body, f"```json\n{body}\n```", f"```\n{body}\n```", f"﻿  {body}  "):
            parsed = parse_reply(raw, self.CT)
            assert isinstance(parsed, Parsed) and parsed.payload == {"titles": ["a", "b"]}

    @pytest.mark.parametrize("raw", [
        'Sure! Here you go: {"titles": ["a"]}', '{"titles": ["a"]} hope that helps', "not json", "[1,2]", '{"titles": ["a"]',
        '{"titles": NaN}', '{"titles": Infinity}', "", "{}", '{"titles": "a"}', '{"titles": true}',
    ])
    def test_anything_else_is_a_parse_failure_and_nothing_is_salvaged(self, raw):
        assert isinstance(parse_reply(raw, self.CT), ParseFailure)

    def test_non_text_reply_fails(self):
        assert isinstance(parse_reply(None, self.CT), ParseFailure)
        assert isinstance(parse_reply(b"{}", self.CT), ParseFailure)

    def test_extra_keys_are_ignored_not_used(self):
        parsed = parse_reply('{"titles": ["a"], "price": 499, "note": "x"}', self.CT)
        assert isinstance(parsed, Parsed) and parsed.payload == {"titles": ["a"]}

    def test_needs_facts_instead_of_content(self):
        parsed = parse_reply('{"needs_facts": ["material", "capacity", 7]}', self.CT)
        assert isinstance(parsed, Parsed) and parsed.payload is None and parsed.needs_facts == ("material", "capacity")

    def test_a_malformed_needs_facts_declaration_is_ignored(self):
        assert isinstance(parse_reply('{"needs_facts": "material"}', self.CT), ParseFailure)

    def test_item_level_garbage_flows_on_to_the_validators(self):
        parsed = parse_reply('{"titles": ["ok", 5, null, {"a": 1}]}', self.CT)
        assert isinstance(parsed, Parsed) and len(parsed.payload["titles"]) == 4

    def test_ceilings_make_a_reply_unusable_not_truncated(self):
        too_many = json.dumps({"titles": ["t"] * (PARSE_SAFETY_MAX_LIST_ITEMS + 1)})
        out = parse_reply(too_many, self.CT)
        assert isinstance(out, ParseFailure) and out.too_large
        ok = json.dumps({"titles": ["t"] * PARSE_SAFETY_MAX_LIST_ITEMS})
        assert isinstance(parse_reply(ok, self.CT), Parsed)
        assert parse_reply("x" * 70_000, self.CT).too_large  # type: ignore[union-attr]
        assert parse_reply(json.dumps({"titles": ["x" * 6000]}), self.CT).too_large  # type: ignore[union-attr]
        assert parse_reply(json.dumps({"description": "x" * 21_000}), {"description": str}).too_large  # type: ignore[union-attr]


class TestScreenFactNames:
    def test_short_names_pass(self):
        assert screen_fact_names(["Material", "capacity", "country of origin", "pack-size"]) == (
            "Material", "capacity", "country of origin", "pack-size")

    @pytest.mark.parametrize("bad", [
        "capacity 750", "750 ml", "x" * 41, "https://evil.example", "a@b.com", "price", "GST rate",
        "", "   ", "<script>", "weight; DROP", "₹499",
    ])
    def test_sentences_numbers_symbols_and_forbidden_words_are_dropped(self, bad):
        assert screen_fact_names([bad]) == ()

    def test_whitespace_is_normalised_never_multiline(self):
        assert screen_fact_names(["line\nbreak"]) == ("line break",)

    def test_dedupes_and_bounds(self):
        assert screen_fact_names(["Material", "material", "MATERIAL "]) == ("Material",)
        assert len(screen_fact_names([f"name {chr(97 + i)}" for i in range(26)])) == 10

    def test_non_strings_are_ignored(self):
        assert screen_fact_names([None, 5, "colour"]) == ("colour",)  # type: ignore[list-item]
