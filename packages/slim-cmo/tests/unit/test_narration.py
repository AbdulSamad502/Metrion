"""narration: the mechanical honesty checks run on every generated string (spec §7, evals 1-6)."""

from __future__ import annotations

import pytest

from slim_cmo import narration as nr
from slim_cmo.claims import Attribute, EligibilityReason as R, partition
from slim_cmo.types import AttributeBasis as B, TrustState as T

SELLER = Attribute("capacity", "750 ml", B.SELLER_PROVIDED)
COLD = Attribute("claim", "keeps drinks cold for 12 hours", B.SELLER_PROVIDED)
EST_WEIGHT = Attribute("weight", "300 g", B.ESTIMATED)
HINT = Attribute("material", "ceramic", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT)


def copy_check(text, attrs=(SELLER, COLD, EST_WEIGHT, HINT), extra=("Alpha Steel Bottle",)):
    p = partition(attrs)
    return nr.check_copy_prose(text, eligible=p.eligible, ineligible=p.ineligible, extra_allowed_text=extra)


def kinds(findings):
    return {f.kind for f in findings}


class TestCopyProse:
    def test_clean_grounded_copy_passes(self):
        assert copy_check("Alpha Steel Bottle holds 750 ml and keeps drinks cold for 12 hours.") == ()

    def test_every_forbidden_category_is_reported_with_its_rule(self):
        out = copy_check("Best price, GST included, a bestseller. Call 9876543210.")
        rules = {f.rule for f in out if f.kind == "FORBIDDEN"}
        assert {"PRICE:price_claim", "TAX:tax_acronym", "DEMAND_CLAIM:bestseller", "CONTACT:phone_digits"} <= rules

    def test_invented_numbers_are_caught(self):
        out = copy_check("Holds 750 ml; trusted by 10000 customers.")
        assert [(f.kind, f.rule) for f in out if f.kind == "UNSUPPORTED_NUMBER"] == [("UNSUPPORTED_NUMBER", "10000")]

    def test_an_estimated_value_stated_as_fact_is_caught(self):
        out = copy_check("Only 300 g and 750 ml.")
        # caught twice, by independent detectors: the number appears in no input, AND it is the
        # value of an ESTIMATED attribute
        assert ("UNSUPPORTED_NUMBER", "300") in {(f.kind, f.rule) for f in out}
        assert ("INELIGIBLE_ATTRIBUTE", "weight") in {(f.kind, f.rule) for f in out}

    def test_an_unverified_image_hint_stated_as_fact_is_caught(self):
        out = copy_check("A beautiful ceramic finish.")
        assert ("INELIGIBLE_ATTRIBUTE", "material") in {(f.kind, f.rule) for f in out}

    def test_the_same_value_stated_by_the_seller_is_fine(self):
        attrs = (HINT, Attribute("material", "ceramic", B.SELLER_PROVIDED))
        p = partition(attrs)
        assert nr.check_copy_prose("A ceramic bottle", eligible=p.eligible, ineligible=p.ineligible) == ()

    def test_the_sellers_own_regulated_claim_is_allowed_but_not_an_invented_one(self):
        attrs = (Attribute("note", "certified food grade steel", B.SELLER_PROVIDED),)
        p = partition(attrs)
        assert nr.check_copy_prose("Certified food grade steel", eligible=p.eligible) == ()
        out = nr.check_copy_prose("Certified food grade steel, 100% guaranteed", eligible=p.eligible)
        assert any(f.rule == "REGULATED:guarantee" for f in out)

    def test_findings_carry_rule_ids_not_seller_text(self):
        out = copy_check("SecretBrandXYZ GST 424242")
        assert all("SecretBrand" not in f.rule for f in out)

    def test_no_attributes_means_no_numbers_are_supported(self):
        assert nr.check_copy_prose("12 hours", eligible=[])[0].kind == "UNSUPPORTED_NUMBER"


class TestTrendProse:
    @pytest.mark.parametrize(
        "text,rule",
        [
            ("These bottles are selling well", "selling_claim"), ("sells like crazy", "selling_claim"), ("flying off the shelves", "selling_claim"),
            ("demand is growing", "demand_claim"), ("There is high demand", "demand_claim"), ("surging demand", "demand_claim"),
            ("the bestseller of the month", "bestseller"), ("a top-selling item", "bestseller"),
            ("this is trending", "trending_as_fact"), ("trends now", "trending_as_fact"),
            ("a popular choice", "popularity"), ("a must-have", "popularity"),
            ("a profitable niche", "profit_promise"), ("guaranteed profit", "profit_promise"), ("a lucrative idea", "profit_promise"),
            ("it will sell", "outcome_promise"), ("sure-shot hit", "outcome_promise"), ("proven to work", "outcome_promise"),
            ("this proves demand", "proof_claim"), ("proof of sales", "proof_claim"),
        ],
    )
    def test_banned_phrasing(self, text, rule):
        assert rule in {f.rule for f in nr.check_trend_prose(text)}, text

    @pytest.mark.parametrize(
        "text",
        [
            "Attracting attention in a video published 2 October",
            "Several independent sources mention it, but no sales data was available",
            "Reported by one blog; unverified",
            "Worth investigating with Product Intelligence",
            "A GST rule change was announced",  # tax words are legitimate in news
        ],
    )
    def test_honest_phrasing_is_not_flagged(self, text):
        assert nr.check_trend_prose(text) == ()

    def test_obfuscation_cannot_hide_a_banned_phrase(self):
        assert nr.check_trend_prose("sell​ing we​ll")
        assert nr.check_trend_prose("T​rending")
        assert nr.check_trend_prose("Тrending")  # Cyrillic Т

    def test_all_matching_rules_are_returned(self):
        rules = {f.rule for f in nr.check_trend_prose("A popular, profitable bestseller")}
        assert rules == {"popularity", "profit_promise", "bestseller"}
