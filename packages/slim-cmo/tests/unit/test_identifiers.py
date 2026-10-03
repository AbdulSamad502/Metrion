"""identifiers: phone-shape detection for listing copy and the stricter long-digit rule for
outbound niche terms. Regression for the P2 review: years, dates, model numbers, HSN/PIN codes
and barcodes must NOT be mistaken for phone numbers, while real phone numbers - however they
are separated, prefixed or disguised - must still be caught."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo import identifiers as idf
from slim_cmo.forbidden import ForbiddenCategory, contains_phone_like_digits, scan_forbidden
from slim_cmo.trends import screening as sc


def gtin_check_digit(body: str) -> str:
    """GS1 mod-10 check digit, so the barcodes below are valid ones."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


EAN13 = "400638133393" + gtin_check_digit("400638133393")
UPC_A = "03600029145" + gtin_check_digit("03600029145")
INDIA_EAN = "890123456789" + gtin_check_digit("890123456789")


class TestPhoneNumbersAreStillCaught:
    @pytest.mark.parametrize(
        "text",
        [
            "9876543210", "call 9876543210 now", "98765 43210", "98765-43210", "98765.43210", "(98765) 43210", "98 76 54 32 10",
            "+91 98765 43210", "(+91) 98765 43210", "+91-9876543210", "+919876543210", "91 9876543210", "919876543210", "09876543210", "0 9876543210",
            "6000000000", "7000000000", "8000000000", "9999999999",  # every mobile leading digit
            "011-2345-6789", "0124 4567890", "02012345678",  # 0-prefixed STD landlines
            "+1 415 555 2671", "+44 20 7946 0958", "+49 30 901820", "+971 50 123 4567",  # explicit international
            "2024 98765 43210", "1999 2024 9876543210", "invoice 2026 call 9876543210",  # phone after year-looking groups
            "Contact: 9876543210.", "tel:9876543210", "WhatsApp 98765 43210",
        ],
    )
    def test_detected(self, text):
        assert idf.contains_phone_number(text), text

    def test_obfuscation_cannot_hide_a_number(self):
        assert idf.contains_phone_number("９８７６５４３２１０")  # full-width
        assert idf.contains_phone_number("९८७६५४३२१०")  # Devanagari digits
        assert idf.contains_phone_number("98765​43210")  # zero-width between groups
        assert idf.contains_phone_number("٩٨٧٦٥٤٣٢١٠")  # Arabic-Indic digits

    def test_explicit_plus_boundaries(self):
        assert not idf.contains_phone_number("+1234567")  # 7 digits: below the E.164 floor
        assert idf.contains_phone_number("+12345678")  # 8
        assert idf.contains_phone_number("+123456789012345")  # 15
        assert not idf.contains_phone_number("+1234567890123456")  # 16: beyond E.164

    def test_the_mobile_pattern_is_exact_in_length_and_leading_digit(self):
        assert not idf.contains_phone_number("987654321")  # 9 digits
        assert not idf.contains_phone_number("98765432109")  # 11 digits not starting 0
        assert not idf.contains_phone_number("5876543210")  # 10 digits starting 5: not a mobile
        assert not idf.contains_phone_number("1234567890")  # documented: a 10-digit id starting 1-5 is not a phone in COPY


class TestNotPhoneNumbers:
    """The regression the review asked for: years and product identifiers."""

    @pytest.mark.parametrize(
        "text",
        [
            # years and year ranges
            "2024 2025 edition", "2024-2025", "1999-2024", "2020 2021 2022 2023", "Model year 2024", "FY 2025", "since 1995",
            # dates
            "2026-10-03", "2026/10/03", "03/10/2026", "03-10-2026", "3.10.2026", "Updated 2026-10-03 and 2026-10-04",
            "+2026-10-03", "(+2026/10/03)",  # a plus-prefixed date must not be read as an international number
            # model / part / catalogue numbers
            "Model 1234 5678", "Part no 73239390", "SKU 12345678", "Item 123456789", "XL-2000", "Ref 1234-5678-90",
            # tax / geography codes
            "HSN 73239390", "PIN 110001", "Pincode 560 001",
            # barcodes
            f"EAN {EAN13}", f"UPC {UPC_A}", f"GTIN {INDIA_EAN}", EAN13, UPC_A, INDIA_EAN, "8901234567890", "036000291452",
            # ordinary quantities and sizes
            "12 hours", "750 ml", "Pack of 10 20 30", "5 in 1", "3 4 5 6", "100% cotton", "6 x 8 x 10", "2 AA batteries",
            "", "   ", "no digits at all",
        ],
    )
    def test_not_flagged(self, text):
        assert not idf.contains_phone_number(text), text

    def test_forbidden_scan_agrees(self):
        for text in ("Model 1234 5678", "Order 2024 2025 edition", "Since 1999-2024", "Updated 2026-10-03", f"EAN {EAN13}"):
            assert ForbiddenCategory.CONTACT not in {f.category for f in scan_forbidden(text)}, text

    def test_the_old_name_still_works_and_means_the_same_thing(self):
        assert contains_phone_like_digits is idf.contains_phone_number


class TestLongDigitRunForOutboundTerms:
    @pytest.mark.parametrize(
        "text", ["12345678", "1234 5678", "9876543210", "1234567890", "98765-43210", "order 171 1234567 1234567", "8901234567890", "2024 98765 43210"],
    )
    def test_identifier_sized_numbers_are_refused(self, text):
        assert idf.contains_long_digit_run(text), text

    @pytest.mark.parametrize(
        "text", ["2024 2025", "2024-2025 trends", "2026-10-03", "03/10/2026", "1234567", "750 ml", "5 in 1", "pack of 12", "usb 3 2 gen 2", "", "steel bottle"],
    )
    def test_years_dates_and_short_numbers_are_not(self, text):
        assert not idf.contains_long_digit_run(text), text

    def test_year_groups_are_discounted_not_the_whole_run_excused(self):
        assert not idf.contains_long_digit_run("2024 2025 3")  # 1 non-year digit
        assert idf.contains_long_digit_run("2024 2025 12345678")  # a real identifier next to years

    def test_the_threshold_is_a_parameter_with_a_floor(self):
        assert idf.contains_long_digit_run("123456789", min_digits=9)
        assert not idf.contains_long_digit_run("12345678", min_digits=9)
        for bad in (6, 0, -1, True, 8.0, "8"):
            with pytest.raises(ValueError):
                idf.contains_long_digit_run("123", min_digits=bad)  # type: ignore[arg-type]


class TestOutboundScreenUsesTheRefinedRules:
    def test_years_in_a_niche_term_are_allowed(self):
        assert sc.screen_term("2024 2025 yoga mats", max_chars=40).ok
        assert sc.screen_term("best of 2026 steel bottles", max_chars=40).ok

    def test_identifiers_in_a_niche_term_are_refused_with_the_right_reason(self):
        assert sc.ScreenReason.PHONE_NUMBER in sc.screen_term("98765-43210 bottles", max_chars=40).reasons
        assert sc.ScreenReason.DIGIT_RUN in sc.screen_term("1234 5678 bottle", max_chars=40).reasons
        assert not sc.screen_term("2024 98765 43210", max_chars=40).ok


class TestProperties:
    @given(st.text(max_size=80))
    @settings(max_examples=400, deadline=None)
    def test_never_raises(self, text):
        idf.contains_phone_number(text)
        idf.contains_long_digit_run(text)

    @given(st.integers(0, 10**12))
    @settings(max_examples=300, deadline=None)
    def test_a_year_pair_is_never_a_phone_and_a_valid_mobile_always_is(self, n):
        year_pair = f"{1900 + n % 200} {1900 + (n // 7) % 200}"
        assert not idf.contains_phone_number(year_pair)
        mobile = str(6 + n % 4) + str(n).zfill(9)[-9:]
        assert idf.contains_phone_number(mobile)

    @given(st.sampled_from(["", "call ", "tel: ", "WhatsApp ", "invoice 2026 "]), st.sampled_from([" now", ".", "!", ""]))
    @settings(max_examples=60, deadline=None)
    def test_surrounding_text_does_not_change_the_verdict(self, before, after):
        assert idf.contains_phone_number(f"{before}9876543210{after}")
        assert not idf.contains_phone_number(f"{before}2024 2025{after}")
