"""§6.10/§6.11 — query generation's six locked kinds and the query privacy boundary.

The privacy-filter tests below cover every "never sent externally" category §6.11 names,
with concrete cases per category (not one generic test), per the checkpoint's test
requirements.
"""

from __future__ import annotations

from competitor_intelligence.discovery.query_generation import (
    QueryKind,
    check_query_privacy,
    generate_queries,
)
from competitor_intelligence.seller_product.types import FieldSource, SellerProduct


def _seller_product(
    *,
    product_id: str = "SKU-WM-001",
    title: str | None = "Wireless Mouse",
    category: str | None = "Computer Accessories",
    attributes: tuple[tuple[str, str], ...] | None = (("colour", "black"),),
    keywords: tuple[str, ...] | None = ("ergonomic mouse", "wireless mouse for laptop"),
) -> SellerProduct:
    field_source: dict[str, FieldSource] = {}
    if title is not None:
        field_source["title"] = FieldSource.CANONICAL_DERIVED
    if category is not None:
        field_source["category"] = FieldSource.SELLER_ENTERED
    if attributes is not None:
        field_source["attributes"] = FieldSource.SELLER_ENTERED
    if keywords is not None:
        field_source["keywords"] = FieldSource.SELLER_ENTERED
    return SellerProduct(
        product_id=product_id,
        title=title,
        category=category,
        price_paise=99900,
        attributes=attributes,
        keywords=keywords,
        fulfillment_type="SELLER_FULFILLED",
        review_count=None,
        rating=None,
        last_updated=None,
        field_source=field_source,
    )


# --- generation covers the six locked kinds ------------------------------------------------


def test_generates_all_six_locked_query_kinds() -> None:
    result = generate_queries(_seller_product())

    kinds = {q.kind for q in result.sent}
    assert kinds == {
        QueryKind.PRODUCT_TERM,
        QueryKind.CATEGORY_TERM,
        QueryKind.FEATURE_TERM,
        QueryKind.INTENT_PHRASE,
        QueryKind.SUBSTITUTE_TERM,
        QueryKind.KEYWORD_TERM,
    }


def test_product_term_uses_title() -> None:
    result = generate_queries(_seller_product())
    product_terms = [q.query_text for q in result.sent if q.kind is QueryKind.PRODUCT_TERM]
    assert product_terms == ["Wireless Mouse"]


def test_category_term_uses_category() -> None:
    result = generate_queries(_seller_product())
    category_terms = [q.query_text for q in result.sent if q.kind is QueryKind.CATEGORY_TERM]
    assert category_terms == ["Computer Accessories"]


def test_keyword_term_uses_public_listing_keywords() -> None:
    result = generate_queries(_seller_product())
    keyword_terms = {q.query_text for q in result.sent if q.kind is QueryKind.KEYWORD_TERM}
    assert keyword_terms == {"ergonomic mouse", "wireless mouse for laptop"}


def test_unknown_field_yields_no_dependent_query_never_a_default() -> None:
    """C30/AC22 — an UNKNOWN field (absent from field_source) produces no query of the kind
    that depends on it, never an invented placeholder."""
    result = generate_queries(_seller_product(category=None, keywords=None))

    kinds = {q.kind for q in result.sent}
    assert QueryKind.CATEGORY_TERM not in kinds
    assert QueryKind.KEYWORD_TERM not in kinds


def test_never_uses_internal_product_id_as_query_material() -> None:
    result = generate_queries(_seller_product(product_id="SKU-WM-001"))

    for query in result.sent:
        assert "SKU-WM-001" not in query.query_text


# --- privacy filter: one concrete case per §6.11 "never sent" category ---------------------


def test_rejects_internal_sku_code() -> None:
    violation = check_query_privacy("SKU-WM-001 wireless mouse", internal_identifiers=("SKU-WM-001",))
    assert violation is not None
    assert violation.category == "INTERNAL_SKU_OR_PRODUCT_ID"


def test_rejects_internal_product_id_keyword() -> None:
    violation = check_query_privacy("internal product id 88213 mouse")
    assert violation is not None
    assert violation.category == "INTERNAL_SKU_OR_PRODUCT_ID"


def test_rejects_supplier_sourcing_information() -> None:
    violation = check_query_privacy("supplier rate for wireless mouse")
    assert violation is not None
    assert violation.category == "SUPPLIER_OR_SOURCING"


def test_rejects_margin_or_cogs_data() -> None:
    violation = check_query_privacy("wireless mouse cogs breakdown")
    assert violation is not None
    assert violation.category == "MARGIN_OR_COST_DATA"


def test_rejects_cost_price_data() -> None:
    violation = check_query_privacy("wireless mouse cost price analysis")
    assert violation is not None
    assert violation.category == "MARGIN_OR_COST_DATA"


def test_rejects_private_sales_volume() -> None:
    violation = check_query_privacy("wireless mouse units sold this month")
    assert violation is not None
    assert violation.category == "SALES_VOLUME_OR_AD_SPEND"


def test_rejects_ad_spend_data() -> None:
    violation = check_query_privacy("wireless mouse ad spend report")
    assert violation is not None
    assert violation.category == "SALES_VOLUME_OR_AD_SPEND"


def test_rejects_proprietary_positioning_language() -> None:
    violation = check_query_privacy("wireless mouse internal only positioning strategy")
    assert violation is not None
    assert violation.category == "PROPRIETARY_POSITIONING"


def test_permits_generic_product_and_category_terms() -> None:
    assert check_query_privacy("wireless mouse") is None
    assert check_query_privacy("budget wireless mouse for gaming") is None
    assert check_query_privacy("alternative to Wireless Mouse") is None


def test_generation_drops_a_query_that_would_leak_forbidden_content() -> None:
    """A query assembled from a forbidden attribute value is dropped, not sent, and the
    pre-redaction draft never appears in the returned `sent` list (§6.11 rules 3-4)."""
    seller_product = _seller_product(attributes=(("note", "cogs is 120 per unit"),))

    result = generate_queries(seller_product)

    for query in result.sent:
        assert "cogs" not in query.query_text.lower()
    assert any(d.reason.startswith("forbidden term in category MARGIN_OR_COST_DATA") for d in result.dropped)
