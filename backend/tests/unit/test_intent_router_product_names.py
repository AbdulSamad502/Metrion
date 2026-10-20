"""A product name that merely contains digits is a product ("is Pegasus 41 worth stocking?"); a bare number or a rate is not (the CEO then asks which product)."""

from __future__ import annotations

import pytest

from backend.ceo.intent_router import _product_text


@pytest.mark.parametrize("name", ["Pegasus 41", "Brand6 Smart Watch Model6", "iPhone 15 case", "GEL-NIMBUS 28"])
def test_a_name_containing_digits_is_a_product(name):
    assert _product_text(name) == name


@pytest.mark.parametrize("text", ["18", "5%", "GST 18%", "it", "this product", "", "   "])
def test_a_bare_number_a_rate_or_a_pronoun_is_not_a_product(text):
    assert _product_text(text) is None
