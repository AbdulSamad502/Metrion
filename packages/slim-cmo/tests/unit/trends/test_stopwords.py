"""Configurable niche stop words, tested on English, Hindi (Devanagari), Romanised Hindi and
mixed-language catalog titles (P2 review decision 6)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo import stopwords as sw
from slim_cmo.config import ConfigMissing, TrendConfig, load_trend_config
from slim_cmo.trends import screening as sc

from ..factories import trend_values

DEFAULT = sw.DEFAULT_STOPWORDS


def suggest(titles, stopwords=DEFAULT, max_terms=10):
    return sc.suggest_terms(titles, stopwords=stopwords, max_terms=max_terms, max_term_chars=40)


def terms(titles, **kw):
    return {x.term for x in suggest(titles, **kw)}


class TestBuiltInSets:
    def test_all_four_families_are_present(self):
        assert {"the", "for"} <= sw.ENGLISH_FUNCTION_WORDS
        assert {"pack", "combo"} <= sw.LISTING_FILLER_WORDS
        assert {"का", "की", "के", "में", "और"} <= sw.HINDI_FUNCTION_WORDS  # का की के में और
        assert {"ka", "ki", "ke", "mein", "aur", "liye"} <= sw.HINGLISH_FUNCTION_WORDS
        assert DEFAULT == sw.ENGLISH_FUNCTION_WORDS | sw.LISTING_FILLER_WORDS | sw.HINDI_FUNCTION_WORDS | sw.HINGLISH_FUNCTION_WORDS

    def test_words_that_are_also_english_content_words_are_not_stop_words(self):
        assert "main" not in DEFAULT  # "main compartment"
        for content in ("steel", "bottle", "yoga", "premium", "copper"):
            assert content not in DEFAULT

    def test_every_built_in_word_is_already_in_normal_form(self):
        assert all(sw.normalise_stopword(w) == w for w in DEFAULT)


class TestBuildStopwords:
    def test_no_adjustments_gives_the_defaults(self):
        assert sw.build_stopwords() == DEFAULT

    def test_extra_words_are_added_and_normalised(self):
        out = sw.build_stopwords(extra=["Premium", " STEEL "])
        assert {"premium", "steel"} <= out and DEFAULT <= out

    def test_excluded_words_are_removed_from_the_defaults(self):
        out = sw.build_stopwords(exclude=["The", "की"])
        assert "the" not in out and "की" not in out and "for" in out

    def test_extra_wins_over_exclude_for_the_same_word(self):
        out = sw.build_stopwords(extra=["steel"], exclude=["steel"])
        assert "steel" in out  # (defaults - exclude) | extra

    def test_harmless_no_ops(self):
        assert sw.build_stopwords(extra=["the"], exclude=["notadefaultword"]) == DEFAULT

    @pytest.mark.parametrize("bad", ["", "   ", "two words", None, 5, ["x"], "​"])
    def test_invalid_entries_are_rejected_loudly(self, bad):
        with pytest.raises(ValueError):
            sw.build_stopwords(extra=[bad])
        with pytest.raises(ValueError):
            sw.build_stopwords(exclude=[bad])

    def test_a_custom_base_set_can_be_supplied(self):
        assert sw.build_stopwords(extra=["x"], defaults=frozenset({"a"})) == frozenset({"a", "x"})


class TestEnglishTitles:
    TITLES = ["Stainless Steel Water Bottle for Gym", "Steel Water Bottle with Lid", "Copper Water Bottle for Home"]

    def test_phrases_never_span_a_stop_word(self):
        found = terms(self.TITLES)
        assert "water bottle" in found and "steel water bottle" in found
        assert not any({"for", "with"} & set(t.split()) for t in found)
        assert "bottle for" not in found and "bottle with" not in found

    def test_ranking_by_document_frequency(self):
        top = suggest(self.TITLES)[0]
        assert (top.term, top.document_frequency) == ("water bottle", 3)


class TestHindiTitles:
    HI = ["स्टील की बोतल", "स्टील की बोतल जिम के लिए"]
    STEEL, BOTTLE, GYM, KI = "स्टील", "बोतल", "जिम", "की"  # स्टील बोतल जिम की

    def test_devanagari_words_survive_intact_and_split_at_stop_words(self):
        found = terms(self.HI)
        # 'जिम' (gym) is folded into the kept longer phrase 'बोतल जिम' (same frequency): the dominance rule
        assert {self.STEEL, self.BOTTLE, f"{self.BOTTLE} {self.GYM}"} <= found and self.GYM not in found
        assert not any(self.KI in t.split() for t in found)  # 'की' (of) is a stop word
        assert not any("के" in t.split() or "लिए" in t.split() for t in found)  # 'के' 'लिए'

    def test_vowel_signs_are_not_shredded(self):
        found = terms(self.HI)
        assert self.BOTTLE in found and "बतल" not in found  # बोतल not बतल

    def test_document_frequency_counts_distinct_titles(self):
        by_term = {x.term: x.document_frequency for x in suggest(self.HI)}
        assert by_term[self.STEEL] == 2 and by_term[self.BOTTLE] == 2 and by_term[f"{self.BOTTLE} {self.GYM}"] == 1


class TestMixedLanguageTitles:
    MIXED = [
        "steel की bottle",  # steel की bottle
        "steel ki bottle gym ke liye",  # Hinglish
        "Steel Bottle के लिए gym",  # steel bottle के लिए gym
    ]

    def test_stop_words_of_every_family_split_a_mixed_title(self):
        found = terms(self.MIXED)
        assert {"steel", "bottle", "gym"} <= found
        banned = {"की", "ki", "ke", "liye", "के", "लिए"}
        assert not any(banned & set(t.split()) for t in found)

    def test_scripts_are_not_merged_across_a_stop_word(self):
        assert "steel bottle" not in terms(["steel की bottle"])  # the Hindi 'of' separates them

    def test_frequency_is_counted_across_scripts_per_title(self):
        by_term = {x.term: x.document_frequency for x in suggest(self.MIXED)}
        assert by_term["steel"] == 3 and by_term["bottle"] == 3

    def test_without_the_hindi_and_hinglish_sets_the_particles_leak_into_terms(self):
        english_only = sw.ENGLISH_FUNCTION_WORDS | sw.LISTING_FILLER_WORDS
        leaked = terms(self.MIXED, stopwords=english_only)
        assert any("ki" in t.split() or "की" in t.split() for t in leaked)  # proves the sets are doing the work


class TestConfigurability:
    TITLES = ["premium steel bottle", "premium steel flask", "steel bottle"]

    def test_extending_the_set_removes_a_word_from_suggestions(self):
        before = terms(self.TITLES)
        after = terms(self.TITLES, stopwords=sw.build_stopwords(extra=["premium"]))
        assert any("premium" in t.split() for t in before)
        assert not any("premium" in t.split() for t in after)

    def test_excluding_a_default_lets_it_into_suggestions(self):
        titles = ["bottle for gym", "bottle for gym use"]
        assert not any("for" in t.split() for t in terms(titles))
        assert any("for" in t.split() for t in terms(titles, stopwords=sw.build_stopwords(exclude=["for"])))

    def test_hindi_particles_can_be_excluded_too(self):
        titles = ["स्टील की बोतल"] * 1
        with_ki = terms(titles, stopwords=sw.build_stopwords(exclude=["की"]))
        assert "स्टील की बोतल" in with_ki

    def test_the_loader_applies_extra_and_exclude(self):
        out = load_trend_config(trend_values(niche_stopwords_extra=["Premium"], niche_stopwords_exclude=["the", "की"]))
        assert isinstance(out, TrendConfig)
        assert "premium" in out.niche_stopwords and "the" not in out.niche_stopwords and "की" not in out.niche_stopwords
        assert out.niche_stopwords_extra == ("premium",) and out.niche_stopwords_exclude == ("the", "की")
        snap = out.snapshot()
        assert snap["niche_stopwords_extra"] == ["premium"] and snap["niche_stopwords_exclude"] == ["the", "की"]

    def test_absent_keys_mean_the_documented_defaults(self):
        out = load_trend_config(trend_values())
        assert isinstance(out, TrendConfig)
        assert out.niche_stopwords == DEFAULT and out.niche_stopwords_extra == () and out.niche_stopwords_exclude == ()

    @pytest.mark.parametrize("key", ["niche_stopwords_extra", "niche_stopwords_exclude"])
    @pytest.mark.parametrize("bad", ["premium", 5, [""], ["two words"], [None], [5], {"a": 1}])
    def test_invalid_values_are_reported_as_invalid_configuration(self, key, bad):
        out = load_trend_config(trend_values(**{key: bad}))
        assert isinstance(out, ConfigMissing) and key in [k for k, _ in out.invalid]

    def test_duplicates_in_config_are_collapsed(self):
        out = load_trend_config(trend_values(niche_stopwords_extra=["premium", "Premium", " premium "]))
        assert isinstance(out, TrendConfig) and out.niche_stopwords_extra == ("premium",)

    def test_end_to_end_config_to_suggestions(self):
        cfg = load_trend_config(trend_values(niche_stopwords_extra=["premium"]))
        assert isinstance(cfg, TrendConfig)
        found = terms(self.TITLES, stopwords=cfg.niche_stopwords)
        assert not any("premium" in t.split() for t in found) and "steel bottle" in found


class TestProperties:
    @given(st.lists(st.text(max_size=40), max_size=8), st.frozensets(st.sampled_from(["steel", "bottle", "the", "premium", "की"]), max_size=4))
    @settings(max_examples=150, deadline=None)
    def test_no_suggestion_ever_contains_a_stop_word(self, titles, extra):
        stop = sw.build_stopwords(extra=extra)
        for s in sc.suggest_terms(titles, stopwords=stop, max_terms=6, max_term_chars=30):
            assert not (set(s.term.split()) & stop)
