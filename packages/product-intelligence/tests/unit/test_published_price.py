"""supplier/published_price.py: a supplier's own per-unit price statement, as a labelled published figure; never a quote, never invented."""

from __future__ import annotations

from datetime import datetime, timezone

from product_intelligence.supplier.published_price import extract_published_unit_price

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _x(text):
    return extract_published_unit_price(text, source_url="https://s.example/p", captured_at=NOW)


def test_a_per_piece_price_is_found_in_integer_paise_with_its_source() -> None:
    got = _x("Steel watch wholesale. Price: ₹1,299.50 per piece, MOQ 50.")
    assert got["low_paise"] == got["high_paise"] == 129950 and got["unit"] == "piece" and got["sample_count"] == 1
    assert got["source_url"] == "https://s.example/p" and got["basis"] == "SUPPLIER_PAGE_TEXT" and "not a quote" in got["disclaimer"]


def test_slash_and_each_forms_and_several_amounts_become_a_range_never_an_average() -> None:
    got = _x("Rs. 450/pc for basic, INR 780 per unit for premium, ₹95 each")
    assert (got["low_paise"], got["high_paise"], got["sample_count"]) == (9500, 78000, 3)


def test_bare_amounts_and_non_unit_words_are_not_prices() -> None:
    for text in ("Free shipping above ₹499", "Starting at ₹450", "₹450 per month subscription", "₹450 eachother", "no price here", ""):
        assert _x(text) is None, text


def test_absurd_or_zero_values_are_ignored() -> None:
    assert _x("₹0 per piece") is None
    assert _x("₹99999999999 per piece") is None
