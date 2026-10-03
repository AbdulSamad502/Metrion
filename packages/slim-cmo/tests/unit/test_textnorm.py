"""textnorm: the folding every detector relies on, and the conservative counting rule."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo import textnorm as tn


class TestSkeleton:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("GST", "gst"),
            ("G​S‌T", "gst"),  # zero-width characters
            ("ＧＳＴ", "gst"),  # full-width letters (NFKC)
            ("G­ST", "gst"),  # soft hyphen
            ("﻿GST", "gst"),  # BOM
            ("G‮ST", "gst"),  # bidi override
            ("  many   spaces\t\nhere ", "many spaces here"),
            ("СТ", "ct"),  # Cyrillic С Т lookalikes
            ("gѕt", "gst"),  # Cyrillic ѕ
            ("ορ", "op"),  # Greek omicron, rho
            ("١٢٣", "123"),  # Arabic-Indic digits
            ("१२३", "123"),  # Devanagari digits
            ("₨", "rs"),  # NFKC maps the rupee sign
        ],
    )
    def test_folds_known_obfuscations(self, raw, expected):
        assert tn.skeleton(raw) == expected

    @given(st.text(max_size=80))
    @settings(max_examples=300, deadline=None)
    def test_is_idempotent_and_never_raises(self, text):
        once = tn.skeleton(text)
        assert tn.skeleton(once) == once

    def test_distinct_ordinary_words_stay_distinct(self):
        assert tn.skeleton("gist") != tn.skeleton("gst")


class TestDedupeKey:
    def test_ignores_case_punctuation_spacing_and_unicode_form(self):
        a = tn.dedupe_key("Steel Bottle — 750 ml!")
        b = tn.dedupe_key("steel  bottle 750  ml")
        assert a == b == "steel bottle 750 ml"

    def test_word_order_matters(self):
        assert tn.dedupe_key("steel bottle") != tn.dedupe_key("bottle steel")

    def test_empty_when_nothing_comparable(self):
        assert tn.dedupe_key("!!! ---") == ""

    def test_indic_words_are_not_shredded_and_different_words_stay_different(self):
        """Regression: combining marks (vowel signs) are not regex-word characters, so a naive
        punctuation strip turned 'बोतल' into 'बतल' and made distinct words equal."""
        assert tn.dedupe_key("बोतल") == "बोतल"
        assert tn.dedupe_key("बोतल") != tn.dedupe_key("बतल")

    def test_underscores_and_hyphens_are_separators(self):
        assert tn.dedupe_key("steel_bottle") == tn.dedupe_key("steel-bottle") == tn.dedupe_key("Steel Bottle")


class TestTokens:
    def test_keeps_letters_digits_and_marks(self):
        assert tn.tokens("steel-bottle, 750ml!") == ["steel", "bottle", "750ml"]
        assert tn.tokens("स्टील बोतल") == ["स्टील", "बोतल"]

    def test_empty(self):
        assert tn.tokens("") == [] and tn.tokens("!!! ---") == []


class TestCounting:
    def test_ascii(self):
        assert tn.count_chars("hello") == 5

    def test_astral_characters_count_twice_never_undercounted(self):
        # An emoji is one code point but two UTF-16 units: the conservative count is 2.
        assert tn.count_chars("\U0001F600") == 2
        assert tn.count_chars("a\U0001F600") == 3

    def test_decomposed_and_composed_forms_count_the_same(self):
        assert tn.count_chars("é") == tn.count_chars("é") == 1

    @given(st.text(max_size=60))
    @settings(max_examples=200, deadline=None)
    def test_never_less_than_code_points(self, text):
        import unicodedata

        assert tn.count_chars(text) >= len(unicodedata.normalize("NFC", text))

    def test_utf8_bytes(self):
        assert tn.utf8_bytes("abc") == 3
        assert tn.utf8_bytes("₹") == 3  # rupee sign: 3 bytes
        assert tn.utf8_bytes("\U0001F600") == 4


class TestCountByRule:
    def test_utf16_rule_is_the_conservative_fallback(self):
        assert tn.count_by_rule("a😀", "UTF16_CODE_UNITS") == 3 == tn.count_chars("a😀")

    def test_code_points_rule_counts_an_emoji_once(self):
        assert tn.count_by_rule("a😀", "CODE_POINTS") == 2

    def test_normalisation_applies_under_both_rules(self):
        for rule in ("UTF16_CODE_UNITS", "CODE_POINTS"):
            assert tn.count_by_rule("é", rule) == 1

    def test_an_unknown_rule_is_an_error_never_a_guess(self):
        for rule in ("GRAPHEMES", "", "utf16_code_units"):
            with pytest.raises(ValueError):
                tn.count_by_rule("abc", rule)


class TestControlCharacters:
    @pytest.mark.parametrize("text", ["a\nb", "a\tb", "a\x00b", "a\x1fb", "a\x7fb", "a\x85b", "a\rb"])
    def test_detected_by_default(self, text):
        assert tn.has_control_characters(text)

    def test_newlines_can_be_permitted_but_other_controls_never(self):
        assert not tn.has_control_characters("para one\n\npara two", allow_newlines=True)
        assert tn.has_control_characters("a\tb", allow_newlines=True)
        assert tn.has_control_characters("a\x00b", allow_newlines=True)

    def test_clean_text_has_none(self):
        assert not tn.has_control_characters("Plain title 123")


class TestCleanGeneratedText:
    def test_trims_and_strips_invisibles_but_does_not_rewrite_the_interior(self):
        assert tn.clean_generated_text("  ​Hello  world​ \n") == "Hello  world"

    def test_normalises_to_nfc(self):
        assert tn.clean_generated_text("é") == "é"
