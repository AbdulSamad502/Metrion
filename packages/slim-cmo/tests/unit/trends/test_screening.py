"""trends.screening: nothing identifier-like may leave Metrion (C15, AC30, AC34, E20, T34/T39),
and catalog titles become niche SUGGESTIONS deterministically."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo.trends import screening as sc
from slim_cmo.trends.screening import ScreenReason as R

STOP = sc.ENGLISH_FUNCTION_WORDS | sc.LISTING_FILLER_WORDS


def ok(term, max_chars=30):
    return sc.screen_term(term, max_chars=max_chars)


class TestScreenTermAccepts:
    @pytest.mark.parametrize("term", ["steel bottle", "Insulated Flask", "yoga mat", "750ml bottle", "usb-c cable", "bottle", "a2 milk", "बोतल",
                                      "2 in 1 trimmer", "led lamp 12v"])
    def test_ordinary_niche_terms(self, term):
        out = ok(term)
        assert out.ok and out.reasons == () and out.term == sc.normalise_term(term)

    def test_normalises_case_and_whitespace(self):
        assert ok("  Steel   BOTTLE ").term == "steel bottle"


class TestScreenTermRejects:
    @pytest.mark.parametrize(
        "term,reason",
        [
            ("@someone", R.HANDLE), ("insta @brand_official", R.HANDLE), ("buyer@example.com", R.EMAIL), ("a.b+c@sub.example.co.in", R.EMAIL),
            ("https://example.com/x", R.URL_OR_DOMAIN), ("www.shop.in", R.URL_OR_DOMAIN), ("mystore.com bottles", R.URL_OR_DOMAIN),
            ("9876543210", R.PHONE_NUMBER), ("+91 9876543210", R.PHONE_NUMBER), ("call 98765-43210", R.PHONE_NUMBER),
            ("22AAAAA0000A1Z5", R.GSTIN), ("gstin 22aaaaa0000a1z5 bottle", R.GSTIN),
            ("ABCDE1234F", R.PAN), ("pan abcde1234f", R.PAN),
            ("171-1234567-1234567", R.ORDER_ID), ("OD123456789012345", R.ORDER_ID), ("od123456789012 refund", R.ORDER_ID),
            ("12345678", R.DIGIT_RUN), ("1234 5678", R.DIGIT_RUN),
            ("", R.EMPTY), ("   ", R.EMPTY), ("​", R.EMPTY),
            ("12345", R.NUMERIC_ONLY), ("3.5", R.NUMERIC_ONLY), ("--", R.NUMERIC_ONLY),
        ],
    )
    def test_identifier_like_terms_are_refused_with_a_reason(self, term, reason):
        out = ok(term)
        assert not out.ok and reason in out.reasons, (term, out)

    def test_length_boundary(self):
        assert ok("a" * 30, 30).ok
        assert R.TOO_LONG in ok("a" * 31, 30).reasons

    def test_control_characters(self):
        assert R.CONTROL_CHARACTERS in ok("steel\nbottle").reasons
        assert R.CONTROL_CHARACTERS in ok("steel\x00bottle").reasons

    def test_non_strings(self):
        for bad in (None, 5, ["bottle"], b"bottle"):
            assert not sc.screen_term(bad, max_chars=30).ok

    def test_obfuscated_identifiers_are_still_caught(self):
        assert not ok("９８７６５４３２１０").ok  # full-width phone
        assert not ok("b​uyer@ex​ample.com").ok

    def test_all_reasons_are_reported_together(self):
        out = ok("a@b.com 9876543210")
        assert {R.EMAIL, R.PHONE_NUMBER} <= set(out.reasons)

    @pytest.mark.parametrize("bad_max", [0, -1, True, 2.5, None])
    def test_max_chars_is_validated(self, bad_max):
        with pytest.raises(ValueError):
            sc.screen_term("steel bottle", max_chars=bad_max)  # type: ignore[arg-type]

    @given(st.text(max_size=60))
    @settings(max_examples=300, deadline=None)
    def test_never_raises_and_ok_terms_are_clean(self, term):
        out = sc.screen_term(term, max_chars=40)
        if out.ok:
            # no URL syntax, handle or e-mail can survive (the bare word "http" with no colon is harmless)
            assert out.term and out.reasons == () and "@" not in out.term and "://" not in out.term and "www." not in out.term


TITLES = [
    "Stainless Steel Insulated Water Bottle 750ml - Pack of 2",
    "Insulated Stainless Steel Water Bottle for Gym",
    "Steel Water Bottle Leakproof 1 Litre",
    "Yoga Mat Anti Slip 6mm",
    "Yoga Mat for Women Anti Slip Premium",
    "Copper Water Bottle",
]


class TestSuggestTerms:
    def suggest(self, titles=TITLES, max_terms=6, max_chars=30):
        return sc.suggest_terms(titles, stopwords=STOP, max_terms=max_terms, max_term_chars=max_chars)

    def test_ranks_by_document_frequency(self):
        out = self.suggest()
        terms = [x.term for x in out]
        assert terms[0] == "water bottle"  # in 4 of 6 titles
        assert dict((x.term, x.document_frequency) for x in out)["water bottle"] == 4
        assert out[0].word_count == 2

    def test_a_shorter_phrase_is_dropped_when_a_kept_longer_one_carries_it(self):
        terms = [x.term for x in self.suggest()]
        assert "stainless steel" in terms or "stainless steel water bottle" in terms or "steel water bottle" in terms
        assert not ("water" in terms and "water bottle" in terms)  # 'water' is dominated by 'water bottle' (same df)

    def test_caps_the_number_of_suggestions(self):
        assert len(self.suggest(max_terms=2)) == 2
        assert len(self.suggest(max_terms=1)) == 1

    def test_ngrams_never_span_stop_words(self):
        for x in self.suggest():
            assert not (set(x.term.split()) & STOP)
        assert "bottle for" not in [x.term for x in self.suggest()]

    def test_duplicate_titles_are_counted_once(self):
        out = sc.suggest_terms(["Steel Bottle", "steel  bottle!", "STEEL BOTTLE"], stopwords=STOP, max_terms=3, max_term_chars=30)
        assert all(x.document_frequency == 1 for x in out)

    def test_identifier_like_candidates_never_become_suggestions(self):
        titles = ["Steel Bottle 9876543210", "Steel Bottle seller@shop.com", "Steel Bottle 22AAAAA0000A1Z5"]
        out = sc.suggest_terms(titles, stopwords=STOP, max_terms=10, max_term_chars=30)
        for x in out:
            assert sc.screen_term(x.term, max_chars=30).ok
            assert "9876543210" not in x.term and "@" not in x.term and "22aaaaa0000a1z5" not in x.term

    def test_numeric_only_tokens_are_not_terms(self):
        out = sc.suggest_terms(["2024 2025 2026 steel"], stopwords=STOP, max_terms=10, max_term_chars=30)
        assert [x.term for x in out] == ["steel"]

    def test_long_phrases_are_dropped_by_the_configured_length(self):
        out = sc.suggest_terms(["stainless steel water bottle"], stopwords=STOP, max_terms=10, max_term_chars=12)
        assert all(len(x.term) <= 12 for x in out)

    def test_deterministic_and_order_independent(self):
        a = self.suggest(TITLES)
        b = self.suggest(list(reversed(TITLES)))
        assert a == b == self.suggest(TITLES)

    def test_empty_and_junk_input(self):
        assert self.suggest([]) == ()
        assert sc.suggest_terms(["", "   ", None, 5, "!!!"], stopwords=STOP, max_terms=5, max_term_chars=30) == ()  # type: ignore[list-item]

    def test_max_terms_is_validated(self):
        for bad in (0, -1, True, None):
            with pytest.raises(ValueError):
                sc.suggest_terms(TITLES, stopwords=STOP, max_terms=bad, max_term_chars=30)  # type: ignore[arg-type]

    def test_stopwords_are_supplied_by_the_caller_not_hidden(self):
        with_all = {x.term for x in sc.suggest_terms(["premium steel bottle"], stopwords=frozenset(), max_terms=10, max_term_chars=40)}
        assert "premium steel bottle" in with_all
        with_filler = {x.term for x in sc.suggest_terms(["premium steel bottle"], stopwords=STOP, max_terms=10, max_term_chars=40)}
        assert "premium steel bottle" in with_filler  # 'premium' is deliberately not a stop word

    def test_non_latin_titles_are_tokenised(self):
        out = sc.suggest_terms(["स्टील की बोतल", "स्टील बोतल 750ml"], stopwords=STOP, max_terms=5, max_term_chars=30)
        assert any("बोतल" in x.term for x in out)

    @given(st.lists(st.text(max_size=50), max_size=15), st.integers(1, 8))
    @settings(max_examples=150, deadline=None)
    def test_properties(self, titles, k):
        out = sc.suggest_terms(titles, stopwords=STOP, max_terms=k, max_term_chars=25)
        assert len(out) <= k
        assert len({x.term for x in out}) == len(out)
        assert all(sc.screen_term(x.term, max_chars=25).ok for x in out)
        dfs = [x.document_frequency for x in out]
        # dominance filtering may skip candidates, but what is kept stays in frequency-descending order
        assert all(dfs[i] >= dfs[i + 1] for i in range(len(dfs) - 1))
