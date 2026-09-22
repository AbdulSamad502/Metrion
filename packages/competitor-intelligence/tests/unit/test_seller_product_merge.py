"""seller_product/merge.py — competitor-intelligence-agent.md §5.5.1, C31, D8.

Mirrors test_evidence_merge.py's shape for the analogous evidence-side precedence rule."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from competitor_intelligence.seller_product.merge import merge_seller_product
from competitor_intelligence.seller_product.types import CanonicalDerived, FieldSource


def test_unfilled_profile_stays_unknown_except_canonical_fields() -> None:
    """T69-style baseline: no manual overrides at all. Only the canonical-derived fields
    (title) are KNOWN; everything the form would have supplied is UNKNOWN."""
    canonical = CanonicalDerived(product_id="SKU-1", title="Wireless Mouse", last_updated=None)

    product = merge_seller_product(canonical, {})

    assert product.product_id == "SKU-1"
    assert product.title == "Wireless Mouse"
    assert product.field_source["title"] == FieldSource.CANONICAL_DERIVED
    assert product.category is None
    assert "category" not in product.field_source
    assert product.price_paise is None
    assert "price_paise" not in product.field_source
    assert product.attributes is None
    assert product.keywords is None
    assert product.fulfillment_type is None


def test_seller_entered_field_with_no_canonical_counterpart_is_known() -> None:
    """category/price/attributes/keywords/fulfillment_type have no canonical source at all
    (§5.5.2) — filling them via the form is the only way they become KNOWN."""
    canonical = CanonicalDerived(product_id="SKU-1", title="Wireless Mouse", last_updated=None)
    manual = {
        "category": "Electronics",
        "price_paise": 149900,
        "attributes": (("color", "black"), ("battery", "AA")),
        "keywords": ("wireless", "mouse"),
        "fulfillment_type": "SELLER_FULFILLED",
    }

    product = merge_seller_product(canonical, manual)

    assert product.category == "Electronics"
    assert product.field_source["category"] == FieldSource.SELLER_ENTERED
    assert product.price_paise == 149900
    assert product.field_source["price_paise"] == FieldSource.SELLER_ENTERED
    assert product.attributes == (("color", "black"), ("battery", "AA"))
    assert product.keywords == ("wireless", "mouse")
    assert product.fulfillment_type == "SELLER_FULFILLED"
    assert product.field_source["fulfillment_type"] == FieldSource.SELLER_ENTERED


def test_seller_entered_supersedes_canonical_on_disagreement() -> None:
    """T70: a canonical-derived title and a seller-entered title differ — seller-entered
    wins, field_source records SELLER_ENTERED, and no UNAVAILABLE/conflict is produced
    (E26b) — unlike the competitor-side conflict case in evidence/merge.py."""
    canonical = CanonicalDerived(product_id="SKU-1", title="Wireless Mouse (Old Title)", last_updated=None)

    product = merge_seller_product(canonical, {"title": "Wireless Mouse Pro"})

    assert product.title == "Wireless Mouse Pro"
    assert product.field_source["title"] == FieldSource.SELLER_ENTERED


def test_partial_form_completion_leaves_only_blank_fields_unknown() -> None:
    """T69: seller fills only category and fulfillment_type, leaving price/attributes/keywords
    blank — the two filled fields are KNOWN/SELLER_ENTERED; the three blanks stay UNKNOWN,
    never defaulted or inferred."""
    canonical = CanonicalDerived(product_id="SKU-1", title="Wireless Mouse", last_updated=None)
    manual = {"category": "Electronics", "fulfillment_type": "SELLER_FULFILLED"}

    product = merge_seller_product(canonical, manual)

    assert product.category == "Electronics"
    assert product.field_source["category"] == FieldSource.SELLER_ENTERED
    assert product.fulfillment_type == "SELLER_FULFILLED"
    assert product.field_source["fulfillment_type"] == FieldSource.SELLER_ENTERED
    assert product.price_paise is None
    assert "price_paise" not in product.field_source
    assert product.attributes is None
    assert "attributes" not in product.field_source
    assert product.keywords is None
    assert "keywords" not in product.field_source


@pytest.mark.parametrize("junk", [{"review_count": 42}, {"rating": 4.5}])
def test_rating_and_review_count_are_always_unknown_regardless_of_input(junk: dict[str, object]) -> None:
    """rating/review_count are permanently out of the manual form's scope (C31, §5.5.2) and
    have no canonical source either — this asserts they can never leak through even if a
    caller mistakenly stuffs a value into manual_overrides."""
    canonical = CanonicalDerived(product_id="SKU-1", title="Wireless Mouse", last_updated=None)

    product = merge_seller_product(canonical, junk)

    assert product.review_count is None
    assert product.rating is None
    assert "review_count" not in product.field_source
    assert "rating" not in product.field_source


def test_neither_source_has_product_id_raises() -> None:
    with pytest.raises(ValueError):
        merge_seller_product(None, {})


def test_manual_only_product_id_is_accepted_when_canonical_is_none() -> None:
    """A seller who fills the form for a SKU with no sales_line rows yet (e.g. a brand-new
    product) still gets a SellerProduct — the canonical side is simply absent, not an error
    by itself; only "neither source at all" is refused."""
    product = merge_seller_product(None, {"product_id": "SKU-NEW", "category": "Electronics"})

    assert product.product_id == "SKU-NEW"
    assert product.title is None
    assert "title" not in product.field_source
    assert product.category == "Electronics"
    assert product.field_source["category"] == FieldSource.SELLER_ENTERED


def test_last_updated_is_the_later_of_canonical_and_manual_timestamps() -> None:
    canonical_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    manual_ts = datetime(2026, 6, 1, tzinfo=timezone.utc)
    canonical = CanonicalDerived(product_id="SKU-1", title="Wireless Mouse", last_updated=canonical_ts)

    product = merge_seller_product(canonical, {"updated_at": manual_ts})

    assert product.last_updated == manual_ts


def test_last_updated_falls_back_to_whichever_side_has_it() -> None:
    canonical = CanonicalDerived(product_id="SKU-1", title="Wireless Mouse", last_updated=None)

    product = merge_seller_product(canonical, {})
    assert product.last_updated is None

    manual_ts = datetime(2026, 6, 1, tzinfo=timezone.utc)
    product = merge_seller_product(canonical, {"updated_at": manual_ts})
    assert product.last_updated == manual_ts
