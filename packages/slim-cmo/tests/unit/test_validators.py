"""validators: lengths, counts, bytes and content enforced in code (AC9, AC13, AC25).

Boundaries are tested on both sides of every limit. Test limits are tiny and arbitrary
(see factories.py) - they say nothing about real marketplaces."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo import validators as v
from slim_cmo.types import CountRule, Marketplace
from slim_cmo.validators import ConstraintFieldMissing, ViolationCode as Code

from .factories import constraint

C = constraint()  # title<=40, 3 options, 3 bullets<=60, desc<=300, 5 keywords<=20, backend 50 bytes
FK = constraint(Marketplace.FLIPKART)


def codes(violations) -> list[Code]:
    return [x.code for x in violations]


# ---------------------------------------------------------------------------------- titles
class TestTitle:
    def test_valid(self):
        out = v.check_title("Steel Bottle 750 ml", C)
        assert out.valid and out.text == "Steel Bottle 750 ml" and out.char_count == 19

    def test_length_boundary(self):
        assert v.check_title("a" * 40, C).valid
        out = v.check_title("a" * 41, C)
        assert codes(out.violations) == [Code.TOO_LONG] and out.violations[0].detail == "41>40"

    def test_unstated_limit_is_not_enforced(self):
        assert v.check_title("a" * 5000, constraint(title_max_chars=None)).valid

    def test_astral_characters_are_counted_conservatively_under_the_utf16_rule(self):
        assert v.check_title("a" * 38 + "\U0001F600", C).valid  # 38 + 2 = 40
        assert not v.check_title("a" * 39 + "\U0001F600", C).valid  # 39 + 2 = 41

    def test_the_marketplaces_verified_rule_decides_how_an_emoji_counts(self):
        points = constraint(count_rule=CountRule.CODE_POINTS)
        assert v.check_title("a" * 39 + "\U0001F600", points).valid  # 39 + 1 = 40
        assert not v.check_title("a" * 40 + "\U0001F600", points).valid  # 41

    def test_the_rule_applied_is_recorded_with_every_option(self):
        out = v.evaluate_title_set(["Alpha", "Beta", "Gamma"], constraint(count_rule=CountRule.CODE_POINTS))
        assert out.accepted[0].constraint_check["count_rule"] == "CODE_POINTS"
        assert "count_unit" not in out.accepted[0].constraint_check

    def test_validating_without_a_verified_rule_is_a_caller_bug_not_a_silent_fallback(self):
        with pytest.raises(ConstraintFieldMissing):
            v.check_title("Alpha", constraint(count_rule=None))
        with pytest.raises(ConstraintFieldMissing):
            v.check_description("Alpha", constraint(count_rule=None))

    @pytest.mark.parametrize("raw", ["", "   ", "\n", "​​"])
    def test_empty_after_cleaning(self, raw):
        assert codes(v.check_title(raw, C).violations) == [Code.EMPTY]

    @pytest.mark.parametrize("raw", [None, 5, ["x"], {"a": 1}, b"bytes"])
    def test_non_strings_are_rejected_not_crashed_on(self, raw):
        assert codes(v.check_title(raw, C).violations) == [Code.WRONG_TYPE]

    def test_titles_are_single_line(self):
        assert Code.CONTROL_CHARACTER in codes(v.check_title("line one\nline two", C).violations)
        assert Code.CONTROL_CHARACTER in codes(v.check_title("tab\there", C).violations)

    def test_edges_are_trimmed_not_penalised(self):
        out = v.check_title("  ​Steel Bottle\n", C)
        assert out.valid and out.text == "Steel Bottle"

    @pytest.mark.parametrize("raw,cat", [("Bottle Rs. 499", "PRICE"), ("Bottle GST", "TAX"), ("Bestseller Bottle", "DEMAND_CLAIM"),
                                          ("Call 9876543210", "CONTACT"), ("Certified Bottle", "REGULATED")])
    def test_forbidden_content(self, raw, cat):
        out = v.check_title(raw, C)
        assert codes(out.violations) == [Code.FORBIDDEN_CONTENT] and cat in out.violations[0].detail

    def test_seller_stated_regulated_claim_is_allowed_via_context(self):
        assert v.check_title("Certified Bottle", C, allowed_context="certified by the seller").valid

    def test_violations_never_contain_seller_text(self):
        out = v.check_title("SecretBrand GST " + "x" * 80, C)
        assert all("SecretBrand" not in str(x) for x in out.violations)


class TestTitleSet:
    def opts(self, *texts):
        return v.evaluate_title_set(list(texts), C)

    def test_full_valid_set(self):
        out = self.opts("Alpha Bottle", "Beta Bottle", "Gamma Bottle")
        assert out.complete and not out.short and not out.rejected
        assert [o.rank for o in out.accepted] == [1, 2, 3]
        assert out.accepted[0].constraint_check == {"max_chars": 40, "limit_unverified": False, "count_rule": "UTF16_CODE_UNITS", "passed": True}

    def test_char_count_is_computed_in_code(self):
        out = self.opts("Alpha Bottle", "Beta", "Gamma")
        assert [o.char_count for o in out.accepted] == [12, 4, 5]

    def test_short_set_is_returned_short_and_labelled_never_padded(self):
        out = self.opts("Alpha Bottle", "x" * 99, "Gamma Bottle")
        assert out.short and len(out.accepted) == 2 and out.expected_count == 3
        assert [r.index for r in out.rejected] == [1]
        assert all(o.text.strip() for o in out.accepted)

    def test_empty_output_is_a_short_set_of_zero(self):
        out = v.evaluate_title_set([], C)
        assert out.short and out.accepted == () and out.expected_count == 3

    def test_duplicates_are_rejected_first_occurrence_wins(self):
        out = self.opts("Alpha Bottle", "ALPHA   bottle!", "Beta Bottle", "Gamma Bottle")
        assert [o.text for o in out.accepted] == ["Alpha Bottle", "Beta Bottle", "Gamma Bottle"]
        assert [r.index for r in out.rejected] == [1] and codes(out.rejected[0].violations) == [Code.DUPLICATE]

    def test_only_exact_normalised_duplicates_are_detected_no_similarity_threshold(self):
        """Decision (P2 review): exact duplicates after normalisation only. Similar-but-different
        options are NOT merged - no near-duplicate threshold exists to tune or to disagree with."""
        out = self.opts("Alpha Steel Bottle 750 ml", "Alpha Steel Bottles 750 ml", "Alpha Steel Bottle 750ml")
        assert len(out.accepted) == 3 and not out.rejected  # plural, and a glued unit, are distinct options
        same = self.opts("Alpha  Steel-Bottle, 750 ml!", "alpha steel bottle 750 ml", "Beta", "Gamma")
        assert [r.index for r in same.rejected] == [1] and len(same.accepted) == 3  # punctuation/case/spacing only

    def test_a_duplicate_of_a_rejected_option_is_not_a_duplicate(self):
        long = "z" * 60
        out = self.opts(long, long, "Alpha", "Beta", "Gamma")
        assert [o.text for o in out.accepted] == ["Alpha", "Beta", "Gamma"]  # both long ones failed on length, not duplication

    def test_surplus_valid_options_are_dropped_not_violations(self):
        out = self.opts("A1 Bottle", "B2 Bottle", "C3 Bottle", "D4 Bottle", "E5 Bottle")
        assert len(out.accepted) == 3 and out.surplus_dropped == 2 and not out.rejected and out.complete

    def test_non_string_items_are_rejected_individually(self):
        out = self.opts("Alpha Bottle", None, 7, "Beta Bottle", "Gamma Bottle")  # type: ignore[arg-type]
        assert len(out.accepted) == 3 and [r.index for r in out.rejected] == [1, 2]

    def test_unstated_limit_is_flagged_unverified_in_the_persisted_check(self):
        out = v.evaluate_title_set(["Alpha", "Beta", "Gamma"], constraint(title_max_chars=None))
        assert out.accepted[0].constraint_check["limit_unverified"] is True and out.accepted[0].constraint_check["max_chars"] is None

    def test_missing_option_count_is_a_programming_error(self):
        with pytest.raises(ConstraintFieldMissing):
            v.evaluate_title_set(["a"], constraint(title_option_count=None))

    @given(st.lists(st.text(max_size=60), max_size=12))
    @settings(max_examples=200, deadline=None)
    def test_invariants_hold_for_arbitrary_model_output(self, raw):
        out = v.evaluate_title_set(raw, C)
        assert len(out.accepted) <= out.expected_count
        assert [o.rank for o in out.accepted] == list(range(1, len(out.accepted) + 1))
        assert all(v.check_title(o.text, C).valid for o in out.accepted)
        assert len({o.text.casefold() for o in out.accepted}) == len(out.accepted)


# ---------------------------------------------------------------------------------- bullets
class TestBullets:
    def test_valid(self):
        out = v.check_bullets(["Keeps cold", "Leak resistant", "Easy to clean"], C)
        assert out.valid and len(out.items) == 3

    @pytest.mark.parametrize("n,code", [(2, Code.TOO_FEW), (4, Code.TOO_MANY), (0, Code.TOO_FEW)])
    def test_exact_count_is_enforced(self, n, code):
        assert code in codes(v.check_bullets([f"bullet number {i}" for i in range(n)], C).violations)

    def test_per_bullet_length_boundary(self):
        ok = ["a" * 60, "b", "c"]
        assert v.check_bullets(ok, C).valid
        assert Code.TOO_LONG in codes(v.check_bullets(["a" * 61, "b", "c"], C).violations)

    def test_duplicates_empties_and_multiline(self):
        out = v.check_bullets(["Same thing", "same   THING.", ""], C)
        assert {Code.DUPLICATE, Code.EMPTY} <= set(codes(out.violations))
        assert Code.CONTROL_CHARACTER in codes(v.check_bullets(["a\nb", "c", "d"], C).violations)

    def test_not_a_list_is_wrong_type(self):
        for raw in ("a string", None, 5, {"a": 1}):
            assert codes(v.check_bullets(raw, C).violations) == [Code.WRONG_TYPE]

    def test_forbidden_content_names_the_offending_bullet(self):
        out = v.check_bullets(["Fine", "GST extra", "Fine too"], C)
        assert [x.field for x in out.violations if x.code is Code.FORBIDDEN_CONTENT] == ["bullets[1]"]

    def test_unstated_bullet_length_is_not_enforced(self):
        assert v.check_bullets(["a" * 900, "b", "c"], constraint(bullet_max_chars=None)).valid

    def test_missing_bullet_count_is_a_programming_error(self):
        with pytest.raises(ConstraintFieldMissing):
            v.check_bullets(["a"], constraint(bullet_count=None))


# ---------------------------------------------------------------------------------- description
class TestDescription:
    def test_valid_with_paragraphs(self):
        assert v.check_description("Para one.\n\nPara two.", C).valid

    def test_length_boundary(self):
        assert v.check_description("a" * 300, C).valid
        assert Code.TOO_LONG in codes(v.check_description("a" * 301, C).violations)

    def test_other_control_characters_still_rejected(self):
        assert Code.CONTROL_CHARACTER in codes(v.check_description("a\x00b", C).violations)
        assert Code.CONTROL_CHARACTER in codes(v.check_description("a\tb", C).violations)

    @pytest.mark.parametrize("raw", ["", "  \n ", None, 5])
    def test_empty_or_wrong_type(self, raw):
        assert codes(v.check_description(raw, C).violations) in ([Code.EMPTY], [Code.WRONG_TYPE])

    def test_forbidden_content(self):
        assert Code.FORBIDDEN_CONTENT in codes(v.check_description("Best price, free GST bill", C).violations)


# ---------------------------------------------------------------------------------- keywords
class TestKeywords:
    def test_valid(self):
        assert v.check_keywords(["steel bottle", "insulated", "flask"], C).valid

    def test_count_and_length_boundaries(self):
        assert v.check_keywords([f"kw{i}" for i in range(5)], C).valid
        assert Code.TOO_MANY in codes(v.check_keywords([f"kw{i}" for i in range(6)], C).violations)
        assert v.check_keywords(["a" * 20], C).valid
        assert Code.TOO_LONG in codes(v.check_keywords(["a" * 21], C).violations)

    def test_empty_list_is_not_a_deliverable(self):
        assert codes(v.check_keywords([], C).violations) == [Code.EMPTY]

    def test_duplicates_ignoring_case_and_punctuation(self):
        assert Code.DUPLICATE in codes(v.check_keywords(["Steel Bottle", "steel-bottle"], C).violations)

    def test_near_duplicates_are_not_flagged_only_exact_normalised_ones(self):
        assert v.check_keywords(["steel bottle", "steel bottles", "bottle steel"], C).valid

    def test_non_string_items_and_non_lists(self):
        assert Code.WRONG_TYPE in codes(v.check_keywords(["ok", 7], C).violations)
        assert codes(v.check_keywords("steel", C).violations) == [Code.WRONG_TYPE]

    def test_unstated_limits_not_enforced(self):
        row = constraint(keywords_max_count=None, keywords_max_chars=None)
        assert v.check_keywords([f"k{i}" * 30 for i in range(50)], row).valid


# ---------------------------------------------------------------------------------- backend terms
class TestBackendTerms:
    def test_bytes_not_characters(self):
        # cap is 50 BYTES: 16 rupee-sign terms of 1 char (3 bytes each) joined by spaces
        terms = ["₹"] * 12  # forbidden currency, but sizing first
        ok = v.check_backend_terms(["alpha", "beta", "gamma"], C)
        assert ok.valid and ok.byte_count == len("alpha beta gamma")
        multibyte = v.check_backend_terms(["é" * 20], C)  # 20 chars, 40 bytes
        assert multibyte.byte_count == 40 and multibyte.valid
        assert Code.BYTES_EXCEEDED in codes(v.check_backend_terms(["é" * 26], C).violations)  # 52 bytes
        del terms

    def test_boundary(self):
        assert v.check_backend_terms(["a" * 50], C).valid
        out = v.check_backend_terms(["a" * 51], C)
        assert Code.BYTES_EXCEEDED in codes(out.violations) and out.violations[0].detail == "51>50"

    def test_joiner_counts_toward_the_cap(self):
        assert v.check_backend_terms(["a" * 24, "b" * 25], C).valid  # 24 + 1 + 25 = 50
        assert not v.check_backend_terms(["a" * 25, "b" * 25], C).valid  # 51

    def test_requires_the_cap(self):
        with pytest.raises(ConstraintFieldMissing):
            v.check_backend_terms(["a"], constraint(backend_terms_max_bytes=None))

    def test_duplicates_and_empty(self):
        assert Code.DUPLICATE in codes(v.check_backend_terms(["Flask", "flask"], C).violations)
        assert Code.EMPTY in codes(v.check_backend_terms([], C).violations)


# ---------------------------------------------------------------------------------- hashtags
class TestHashtags:
    def test_valid(self):
        assert v.check_hashtags(["#SteelBottle", "#fitness_goals", "#2026Style"]).valid

    @pytest.mark.parametrize("bad", ["SteelBottle", "#", "# bottle", "#steel bottle", "#steel-bottle", "##x", "#_x", "#a,b", "# "])
    def test_malformed_hashtags(self, bad):
        assert Code.INVALID_HASHTAG in codes(v.check_hashtags([bad]).violations)

    def test_unicode_hashtags_are_allowed(self):
        assert v.check_hashtags(["#बोतल"]).valid

    def test_duplicates_ignore_case(self):
        assert Code.DUPLICATE in codes(v.check_hashtags(["#Steel", "#steel"]).violations)

    def test_forbidden_words_cannot_be_smuggled_in_as_tags(self):
        for tag in ("#GST", "#bestseller", "#trending", "#rs499"):
            assert Code.FORBIDDEN_CONTENT in codes(v.check_hashtags([tag]).violations), tag

    def test_empty_list(self):
        assert codes(v.check_hashtags([]).violations) == [Code.EMPTY]

    def test_non_list_and_non_string_items(self):
        assert codes(v.check_hashtags("#tag").violations) == [Code.WRONG_TYPE]
        assert Code.WRONG_TYPE in codes(v.check_hashtags(["#ok", 5, None]).violations)


# ---------------------------------------------------------------------------------- the pack
GOOD = dict(description="Keeps drinks cold.", bullets=["One", "Two", "Three"], keywords=["steel", "flask"])


class TestListingCopyPackIsAtomic:
    def test_all_valid(self):
        out = v.check_listing_copy(GOOD["description"], GOOD["bullets"], GOOD["keywords"], C)
        assert out.valid
        assert out.structured() == {"description": "Keeps drinks cold.", "bullets": ["One", "Two", "Three"], "keywords": ["steel", "flask"]}

    @pytest.mark.parametrize(
        "broken",
        [
            dict(description=""),
            dict(description="Best price in town"),
            dict(bullets=["One", "Two"]),
            dict(bullets=["One", "Two", "Three", "Four"]),
            dict(keywords=[]),
            dict(keywords=["a" * 21]),
        ],
    )
    def test_any_single_failing_component_fails_the_whole_pack(self, broken):
        args = {**GOOD, **broken}
        out = v.check_listing_copy(args["description"], args["bullets"], args["keywords"], C)
        assert not out.valid
        with pytest.raises(ValueError, match="valid listing copy pack"):
            out.structured()  # a half-valid pack can never be persisted as a deliverable

    def test_violations_from_every_component_are_collected(self):
        out = v.check_listing_copy("", ["x"], [], C)
        fields = {x.field.split("[")[0] for x in out.violations}
        assert {"description", "bullets", "keywords"} <= fields

    def test_cleaned_text_is_what_is_persisted(self):
        out = v.check_listing_copy("  Keeps cold ​", [" One ", "Two", "Three\n"], [" steel "], C)
        assert out.valid and out.description == "Keeps cold" and out.bullets == ("One", "Two", "Three") and out.keywords == ("steel",)
