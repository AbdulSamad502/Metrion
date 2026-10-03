"""forbidden.scan_forbidden: price / tax / demand / regulated / contact detection and its
resistance to obfuscation. The scan is a safety net behind the generator, so the adversarial
cases matter more than the happy path."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo.forbidden import ForbiddenCategory as C
from slim_cmo.forbidden import scan_forbidden


def cats(text, **kw):
    return {f.category for f in scan_forbidden(text, **kw)}


def rules(text, **kw):
    return {f.rule for f in scan_forbidden(text, **kw)}


class TestCleanCopyIsNotFlagged:
    @pytest.mark.parametrize(
        "text",
        [
            "Insulated steel bottle keeps drinks cold for 12 hours",
            "750 ml capacity, leak-resistant lid",
            "Pack of 10 20 30",
            "Made from 100% cotton",
            "The gist of the matter",  # 'gist' is not 'gst'
            "Fits sizes S, M and L",
            "Dishwasher friendly; hand wash recommended",
            "Includes 2 spare gaskets",
            "",
            "   ",
        ],
    )
    def test_ordinary_product_language_is_clean(self, text):
        assert scan_forbidden(text) == ()


class TestPrice:
    @pytest.mark.parametrize(
        "text",
        ["Only Rs. 499", "₹499", "$10", "€5", "INR 100", "2 rupees", "MRP inside", "20% off today", "Big discount", "cashback offer",
         "percent off", "clearance stock"],
    )
    def test_figures_and_discounts_are_detected(self, text):
        assert C.PRICE in cats(text), text

    def test_price_words_inside_other_words_are_not_flagged(self):
        assert C.PRICE not in cats("comprised of steel; rsvp not needed; a pricey-sounding name is still a name")


class TestPriceClaimsVersusNeutralWording:
    """Decision (P2 review): the neutral word 'price' is allowed; figures and unsupported
    comparative / absolute / promotional claims about price, discounts or savings are not."""

    @pytest.mark.parametrize(
        "text",
        ["A fair price for a premium bottle", "fair price", "reasonable price", "great price", "value for money", "affordable steel bottle",
         "priced fairly", "The price is shown on the listing", "price", "Price on request", "premium price point"],
    )
    def test_neutral_wording_is_allowed(self, text):
        assert C.PRICE not in cats(text), text
        assert scan_forbidden(text) == (), text

    @pytest.mark.parametrize(
        "text",
        ["best price", "lowest price", "cheapest bottle", "cheap steel bottle", "cheaper than others", "special price", "offer price", "sale price",
         "discounted price", "price drop", "price cut", "price match", "price guarantee", "competitively priced", "competitive price",
         "on sale now", "save big", "save money", "save 20", "big savings", "money-saving design", "priced to sell", "unbeatable price",
         "half price", "wholesale price", "rock bottom prices", "great deal", "best deals", "limited-time price", "price starting soon"],
    )
    def test_unsupported_price_discount_and_savings_claims_are_blocked(self, text):
        found = rules(text)
        assert found & {"price_claim", "discount_word", "percent_off"}, (text, found)
        assert C.PRICE in cats(text)

    def test_a_figure_is_blocked_even_inside_neutral_wording(self):
        assert C.PRICE in cats("a fair price of Rs. 499")
        assert C.PRICE in cats("fair price Rs499")
        assert C.PRICE in cats("a fair price (MRP 999)")

    def test_claims_survive_obfuscation(self):
        assert C.PRICE in cats("b​est pr​ice")
        assert C.PRICE in cats("ＢＥＳＴ ＰＲＩＣＥ")
        assert C.PRICE in cats("Chеap bottle")  # Cyrillic е

    def test_a_savings_claim_cannot_hide_in_a_hashtag(self):
        from slim_cmo import validators as v

        for tag in ("#bestprice", "#cheap", "#savebig"):
            check = v.check_hashtags([tag])
            # a hashtag is one token: "#cheap" is blocked; fused words are a documented limit
            if tag == "#cheap":
                assert not check.valid, tag

    def test_the_word_price_alone_never_fires_any_rule(self):
        assert rules("price") == set() and rules("Prices vary by size") == set()


class TestLettersGluedToDigits:
    """Regression (found by the P2 hashtag test): word boundaries did not fire between a word
    and a digit, so the way sellers actually write prices and taxes slipped through."""

    @pytest.mark.parametrize(
        "text,category",
        [("Rs499", C.PRICE), ("rs.499", C.PRICE), ("inr250", C.PRICE), ("MRP999", C.PRICE), ("GST18", C.TAX), ("igst5", C.TAX),
         ("hsn7323", C.TAX), ("ISO9001", C.REGULATED), ("only499rs", C.PRICE)],
    )
    def test_detected(self, text, category):
        assert category in cats(text), text

    @pytest.mark.parametrize("text", ["750ml", "a4 paper", "5g network", "h2o", "m8 bolt", "xl2", "3d printed", "2in1"])
    def test_ordinary_size_and_model_tokens_are_not_flagged(self, text):
        assert scan_forbidden(text) == (), text

    def test_waiver_works_on_the_split_form_too(self):
        assert C.REGULATED not in cats("ISO9001 mark", allowed_context="Seller: ISO 9001 certified")


class TestTax:
    @pytest.mark.parametrize(
        "text",
        ["GST included", "igst applies", "CGST+SGST", "UTGST", "HSN code 7323", "tax invoice", "taxes extra", "TDS", "TCS", "cess", "VAT free",
         "input tax credit"],
    )
    def test_detected(self, text):
        assert C.TAX in cats(text)

    @pytest.mark.parametrize("text", ["g.s.t", "G S T", "g-s-t", "G​S​T", "ＧＳＴ", "gѕt", "G_S_T"])
    def test_acronym_obfuscations_are_still_detected(self, text):
        assert C.TAX in cats(text), text

    def test_known_gap_confusables_outside_the_documented_table_are_not_folded(self):
        """The confusable table is partial by design (textnorm docstring). Documented, not hidden:
        if this ever starts failing because coverage improved, update the docstring and delete this."""
        assert C.TAX not in cats("ɡst")  # Latin script-g U+0261

    def test_ordinary_words_that_contain_the_letters_are_not_flagged(self):
        for word in ("gist", "gust", "just", "guest", "agst", "digest", "taxonomy", "relax", "syntax"):
            assert C.TAX not in cats(word), word


class TestDemandClaims:
    @pytest.mark.parametrize(
        "text",
        ["A BESTSELLER", "best seller pick", "best-selling bottle", "top selling", "top-seller", "hot seller", "trending now", "TRENDING",
         "selling fast", "selling well", "sells like crazy", "selling like hotcakes", "flying off the shelves", "in demand", "high demand", "huge demand",
         "#1 choice", "# 1", "No.1 brand", "number one", "number 1", "most popular", "customers favourite", "customer favorite"],
    )
    def test_detected(self, text):
        assert C.DEMAND_CLAIM in cats(text), text

    def test_cyrillic_lookalike_cannot_hide_trending(self):
        assert C.DEMAND_CLAIM in cats("Тrending")  # Cyrillic Т
        assert C.DEMAND_CLAIM in cats("bеstseller")  # Cyrillic е


class TestRegulatedAndWaiver:
    @pytest.mark.parametrize(
        "text",
        ["100% guaranteed", "guarantee included", "certified organic", "ISO 9001", "FDA approved", "FSSAI licensed", "BIS mark",
         "clinically proven", "dermatologist tested", "doctor recommended", "cures acne", "Best in India", "world's best", "India's best"],
    )
    def test_detected_without_context(self, text):
        assert C.REGULATED in cats(text), text

    def test_waived_when_the_seller_stated_the_same_claim(self):
        assert C.REGULATED not in cats("Certified organic cotton", allowed_context="Seller note: certified organic cotton")

    def test_waiver_is_per_rule_not_blanket(self):
        found = rules("certified and guaranteed", allowed_context="certified by lab")
        assert "certified" not in found and "guarantee" in found

    def test_nothing_else_is_ever_waivable(self):
        ctx = "best price GST bestseller call 9876543210 www.x.com"
        for text in ("Best price", "GST extra", "bestseller", "Call 9876543210", "visit www.x.com"):
            assert scan_forbidden(text, allowed_context=ctx), text


class TestContact:
    @pytest.mark.parametrize(
        "text",
        ["see https://example.com", "http:", "www.shop.in", "shop.com", "buy at store.in", "mail me@x.in", "a.b+c@sub.example.co.in",
         "whatsapp us", "Telegram channel", "call 9876543210", "call +91 98765 43210", "98765-43210", "9876543210"],
    )
    def test_detected(self, text):
        assert C.CONTACT in cats(text), text

    def test_the_old_eight_digit_rule_is_gone_years_and_model_numbers_are_not_phones(self):
        for text in ("12 hours", "750 ml", "Model 1234", "Model 1234 5678", "Order 2024 2025 edition", "Since 1999-2024", "Updated 2026-10-03",
                     "Part no 73239390", "PIN 110001", "EAN 4006381333931", "UPC 036000291452", "Pack of 10 20 30"):
            assert C.CONTACT not in cats(text), text

    def test_real_phone_shapes_are_still_blocked(self):
        for text in ("call 9876543210", "98765-43210", "+91 98765 43210", "09876543210", "919876543210", "011-2345-6789 ext", "+1 415 555 2671",
                     "2024 98765 43210"):
            assert C.CONTACT in cats(text), text

    def test_full_width_and_devanagari_digits_cannot_hide_a_phone_number(self):
        assert C.CONTACT in cats("９８７６５４３２１０")
        assert C.CONTACT in cats("९८७६५४३२१०")  # 9876543210 in Devanagari digits


class TestCategoryFilter:
    def test_only_requested_categories_are_scanned(self):
        text = "GST best price bestseller"
        assert cats(text, categories=[C.TAX]) == {C.TAX}
        assert cats(text, categories=[C.PRICE, C.DEMAND_CLAIM]) == {C.PRICE, C.DEMAND_CLAIM}
        assert cats(text, categories=[C.CONTACT]) == set()


class TestRobustness:
    @given(st.text(max_size=120))
    @settings(max_examples=300, deadline=None)
    def test_never_raises_and_is_deterministic(self, text):
        assert scan_forbidden(text) == scan_forbidden(text)

    def test_findings_never_echo_seller_text(self):
        for f in scan_forbidden("secret-brand GST 9876543210"):
            assert "secret" not in f.rule and "9876" not in f.rule

    def test_very_long_input_completes(self):
        assert scan_forbidden("steel bottle " * 20000) == ()
