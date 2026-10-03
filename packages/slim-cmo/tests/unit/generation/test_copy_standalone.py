"""Listing copy pack (atomic, T9, T22, T25, T26), standalone artefacts (T27, T28, T14), the parse-safety
ceiling (decision 7) and Flipkart structured fields (decision 9)."""

from __future__ import annotations

import json

import pytest

from slim_cmo.config import ConfigMissing, HashtagConfig, load_hashtag_config
from slim_cmo.constraints import ConstraintUnavailable, UnavailableReason, resolve_constraint
from slim_cmo.generation import standalone as sa
from slim_cmo.generation.copy import generate_listing_copy, shared_text_diagnostics
from slim_cmo.generation.facts import FactInput, build_fact_context
from slim_cmo.generation.outcomes import Delivered, Failed, FailureCode
from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.generation.safety_limits import PARSE_SAFETY_MAX_LIST_ITEMS
from slim_cmo.types import Marketplace as M
from slim_cmo.types import OutputType as O
from slim_cmo.types import SellerFactType as F

from ..factories import NOW, constraint
from .helpers import ANCHOR, GOOD_PACK, MODEL, ctx, j, resolved


def pack(replies, *, mp=M.AMAZON, facts=None, retry_bound=2, anchor=ANCHOR, **limits):
    p = ScriptedLlmProvider(replies)
    out = generate_listing_copy(provider=p, model=MODEL, marketplace=mp, resolved=resolved(mp, O.LISTING_COPY, **limits),
                                facts=facts or ctx(), anchor_title=anchor, retry_bound=retry_bound)
    return out, p


class TestListingCopyPack:
    def test_a_valid_pack_is_delivered_with_its_constraint_cited(self):
        out, p = pack([GOOD_PACK])
        assert isinstance(out, Delivered) and out.output_type is O.LISTING_COPY
        assert set(out.structured) >= {"description", "bullets", "keywords", "constraint", "unverified_limits"}
        assert out.structured["constraint"]["source_url"] and out.structured["constraint"]["verified_at"]
        assert p.calls == 1

    def test_atomic_one_bad_field_fails_the_whole_pack_with_nothing_partial(self):
        bad_desc = j(description="Only Rs. 499 with GST.", bullets=["Stainless steel build", "750 ml capacity", "Easy to carry"], keywords=["steel bottle"])
        out, _ = pack([bad_desc], retry_bound=0)
        assert isinstance(out, Failed)
        assert not hasattr(out, "structured")

    def test_t25_sixth_bullet_price_and_gst_are_never_delivered(self):
        bad = j(description="Great bottle at Rs. 499 with 18% GST.", bullets=["a one", "b two", "c three", "d four"], keywords=["steel bottle"])
        out, _ = pack([bad, bad], retry_bound=1)
        assert isinstance(out, Failed) and out.failure.code is FailureCode.VALIDATION_FAILED
        v = out.failure.detail["violations"]
        assert "TOO_MANY" in v and any(k.startswith("FORBIDDEN:PRICE") for k in v) and any(k.startswith("FORBIDDEN:TAX") for k in v)

    def test_a_retry_regenerates_the_whole_pack_never_stitching_fields_across_attempts(self):
        first = j(description="A 750 ml stainless steel bottle from AquaKeep.", bullets=["Stainless steel build", "750 ml capacity"], keywords=["steel bottle"])
        second = j(description="Steel bottle by AquaKeep, 750 ml, for daily use.", bullets=["Stainless steel", "750 ml", "Easy to carry"], keywords=["bottle"])
        out, p = pack([first, second])
        assert isinstance(out, Delivered) and out.structured["description"].startswith("Steel bottle by")
        assert out.structured["bullets"] == ["Stainless steel", "750 ml", "Easy to carry"]
        assert "bullets: TOO_FEW" in p.prompts[1]

    def test_numbers_in_the_approved_title_are_grounded_but_other_numbers_are_not(self):
        anchor = "AquaKeep Steel Bottle 750 ml Keeps Cold 12 Hours"
        ok = j(description="Keeps drinks cold for 12 hours in a 750 ml steel bottle.", bullets=["Stainless steel build", "750 ml", "Cold 12 hours"], keywords=["steel bottle"])
        out, _ = pack([ok], anchor=anchor, retry_bound=0)
        assert isinstance(out, Delivered)
        out, _ = pack([ok], anchor=ANCHOR, retry_bound=0)  # 12 is in no input here
        assert isinstance(out, Failed)

    def test_estimated_and_unverified_values_never_reach_a_delivered_pack(self):
        leaky = j(description="A 350 g stainless steel bottle in matte blue.", bullets=["Stainless steel", "750 ml", "Matte blue finish"], keywords=["steel bottle"])
        out, _ = pack([leaky], retry_bound=0)
        assert isinstance(out, Failed) and set(out.failure.missing_facts) == {"weight", "color"}

    def test_t26_sparse_facts_return_needs_facts_and_invent_nothing(self):
        sparse = build_fact_context([FactInput(F.BRAND, "AquaKeep")])
        out, p = pack([j(needs_facts=["material", "capacity"])], facts=sparse)
        assert isinstance(out, Failed) and out.failure.code is FailureCode.NEEDS_FACTS
        assert out.failure.missing_facts == ("material", "capacity") and p.calls == 1

    def test_flipkart_never_pretends_structured_fields_are_filled_or_enforced(self):
        flip = j(description="Steel bottle by AquaKeep, 750 ml.", bullets=["Stainless steel", "750 ml"], keywords=["steel bottle"])
        out, _ = pack([flip], mp=M.FLIPKART, bullet_count=2)
        assert isinstance(out, Delivered)
        assert out.structured["structured_fields"]["state"] == "NEEDS_SELLER_INPUT" and out.structured["structured_fields"]["fields"] == []
        assert out.structured["description_type"] == "plain"
        amazon, _ = pack([GOOD_PACK])
        assert isinstance(amazon, Delivered) and "structured_fields" not in amazon.structured

    def test_unstated_limits_are_reported_unverified_not_guessed(self):
        out, _ = pack([GOOD_PACK], keywords_max_count=None, bullet_max_chars=None)
        assert isinstance(out, Delivered)
        assert {"keywords_max_count", "bullet_max_chars"} <= set(out.structured["unverified_limits"])


class TestMarketplaceIsolation:
    def test_a_marketplace_prompt_contains_no_other_marketplace_output(self):
        amazon, pa = pack([GOOD_PACK])
        assert isinstance(amazon, Delivered)
        flip = j(description="Steel bottle by AquaKeep, 750 ml.", bullets=["Stainless steel", "750 ml"], keywords=["steel bottle"])
        out, pf = pack([flip], mp=M.FLIPKART, bullet_count=2, anchor="AquaKeep Flip 750 ml")
        assert isinstance(out, Delivered)
        for text in (amazon.structured["description"], *amazon.structured["bullets"]):
            assert text not in pf.prompts[0]
        assert "AMAZON" not in pf.prompts[0] and "FLIPKART" in pf.prompts[0]

    def test_shared_text_is_recorded_diagnostically_and_never_fails_a_pack(self):
        a, _ = pack([GOOD_PACK])
        same = j(description="A 750 ml stainless steel bottle from AquaKeep for everyday use.", bullets=["Stainless steel build", "750 ml"], keywords=["steel bottle"])
        b, _ = pack([same], mp=M.FLIPKART, bullet_count=2)
        assert isinstance(a, Delivered) and isinstance(b, Delivered)  # both delivered despite identical text
        kinds = {d["kind"] for d in shared_text_diagnostics({M.AMAZON: a, M.FLIPKART: b})}
        assert kinds == {"description", "bullet"}


class TestParseSafetyCeilingIsNotAMarketplaceRule:
    def test_it_does_not_enforce_a_missing_limit_below_the_ceiling(self):
        many = j(description="A 750 ml steel bottle by AquaKeep.", bullets=["Stainless steel build", "750 ml capacity", "Easy to carry"],
                 keywords=[f"steel bottle {chr(97 + i % 26)}{chr(97 + i // 26)}" for i in range(150)])
        out, _ = pack([many], keywords_max_count=None, keywords_max_chars=None)
        assert isinstance(out, Delivered) and len(out.structured["keywords"]) == 150  # limit unstated => not enforced
        assert "keywords_max_count" in out.structured["unverified_limits"]

    def test_beyond_the_ceiling_the_reply_is_unusable_and_the_limit_stays_unverified(self):
        huge = j(description="x", bullets=["a"] * 3, keywords=["k"] * (PARSE_SAFETY_MAX_LIST_ITEMS + 1))
        out, _ = pack([huge], retry_bound=0, keywords_max_count=None)
        assert isinstance(out, Failed) and out.failure.code is FailureCode.OUTPUT_TOO_LARGE
        assert "TOO_MANY" not in json.dumps(out.failure.structured())  # not reported as a marketplace limit

    def test_it_never_appears_in_delivered_constraint_data(self):
        out, _ = pack([GOOD_PACK], keywords_max_count=None)
        blob = json.dumps(out.structured)  # type: ignore[union-attr]
        assert str(PARSE_SAFETY_MAX_LIST_ITEMS) not in blob and "ceiling" not in blob.lower()

    def test_a_missing_required_limit_still_blocks_regardless_of_the_ceiling(self):
        r = resolve_constraint([constraint(M.AMAZON, bullet_count=None)], marketplace=M.AMAZON, category=None,
                               output_type=O.LISTING_COPY, now=NOW, max_age_days=30)
        assert isinstance(r, ConstraintUnavailable) and r.reason is UnavailableReason.MISSING_REQUIRED_LIMIT


def comp(fn, replies, *, mp=M.AMAZON, out=O.BULLETS, retry_bound=1, **limits):
    p = ScriptedLlmProvider(replies)
    result = fn(provider=p, model=MODEL, marketplace=mp, resolved=resolved(mp, out, **limits), facts=ctx(), anchor_title=ANCHOR, retry_bound=retry_bound)
    return result, p


class TestStandaloneArtefacts:
    def test_description(self):
        out, _ = comp(sa.generate_description, [j(description="A 750 ml stainless steel bottle by AquaKeep.")], out=O.DESCRIPTION)
        assert isinstance(out, Delivered) and out.output_type is O.DESCRIPTION and out.output_text

    def test_bullets_enforce_the_marketplace_count(self):
        out, _ = comp(sa.generate_bullets, [j(bullets=["Stainless steel", "750 ml"])] * 2)
        assert isinstance(out, Failed)
        out, _ = comp(sa.generate_bullets, [j(bullets=["Stainless steel", "750 ml", "Easy to carry"])])
        assert isinstance(out, Delivered) and out.output_type is O.BULLETS

    def test_keywords(self):
        out, _ = comp(sa.generate_keywords, [j(keywords=["steel bottle", "750 ml"])], out=O.KEYWORDS)
        assert isinstance(out, Delivered) and out.structured["keywords"] == ["steel bottle", "750 ml"]

    def test_backend_terms_are_amazon_only_and_byte_capped(self):
        with pytest.raises(ValueError):
            comp(sa.generate_backend_terms, [j(terms=["steel"])], mp=M.FLIPKART, out=O.KEYWORDS)
        out, _ = comp(sa.generate_backend_terms, [j(terms=["steel flask", "water bottle"])], out=O.BACKEND_TERMS)
        assert isinstance(out, Delivered) and out.structured["byte_count"] <= 50 and out.structured["max_bytes"] == 50
        out, _ = comp(sa.generate_backend_terms, [j(terms=["steel flask " * 8])], out=O.BACKEND_TERMS, retry_bound=0)
        assert isinstance(out, Failed)

    def test_each_standalone_prompt_carries_the_approved_title_and_only_its_own_task(self):
        out, p = comp(sa.generate_bullets, [j(bullets=["Stainless steel", "750 ml", "Easy to carry"])])
        assert ANCHOR in p.prompts[0] and "description" not in p.prompts[0].split("Reply shape:")[1].split("DATA")[0]

    def test_standalone_never_alters_or_depends_on_a_pack_row(self):
        out, _ = comp(sa.generate_description, [j(description="A 750 ml stainless steel bottle by AquaKeep.")], out=O.DESCRIPTION)
        assert "bullets" not in out.structured and "keywords" not in out.structured  # type: ignore[union-attr]


class TestHashtags:
    def run(self, replies, size=3, retry_bound=1):
        p = ScriptedLlmProvider(replies)
        return sa.generate_hashtags(provider=p, model=MODEL, facts=ctx(), hashtag_set_size=size, retry_bound=retry_bound), p

    def test_separate_labelled_marketing_artefact_with_no_marketplace_constraint(self):
        out, p = self.run([j(hashtags=["#steelbottle", "#AquaKeep", "#hydration"])])
        assert isinstance(out, Delivered) and out.output_type is O.HASHTAGS
        assert out.structured["label"] == sa.HASHTAG_LABEL and out.structured["listing_field"] is False
        assert "constraint" not in out.structured and "format_constraint_ref" not in json.dumps(out.structured)
        assert "AMAZON" not in p.prompts[0] and "FLIPKART" not in p.prompts[0]

    def test_the_configured_size_is_a_maximum(self):
        out, _ = self.run([j(hashtags=["#a1", "#b2"]), j(hashtags=["#a1", "#b2"])], size=1, retry_bound=0)
        assert isinstance(out, Failed)
        out, _ = self.run([j(hashtags=["#steel", "#bottle"])], size=5)
        assert isinstance(out, Delivered) and len(out.structured["hashtags"]) == 2

    @pytest.mark.parametrize("bad", ["steelbottle", "#steel bottle", "#bestseller", "#Rs499", "#gst", "#"])
    def test_invalid_or_forbidden_hashtags_are_never_delivered(self, bad):
        out, _ = self.run([j(hashtags=[bad, "#steel"])], retry_bound=0)
        assert isinstance(out, Failed)

    def test_set_size_is_never_defaulted(self):
        for bad in (0, -1, True, None, 2.5):
            with pytest.raises(ValueError):
                self.run([j(hashtags=["#a"])], size=bad)  # type: ignore[arg-type]

    def test_missing_hashtag_config_is_config_missing_and_does_not_block_other_artefacts(self):
        assert isinstance(load_hashtag_config({}), ConfigMissing)
        assert load_hashtag_config({}).missing == ("hashtag_set_size",)  # type: ignore[union-attr]
        for bad in (True, 0, 1.5, "3"):
            assert isinstance(load_hashtag_config({"hashtag_set_size": bad}), ConfigMissing)
        assert load_hashtag_config({"hashtag_set_size": 4}) == HashtagConfig(4)
