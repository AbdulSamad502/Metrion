"""`SellerProduct` merge — competitor-intelligence-agent.md §5.5.1, C31, D8.

Mirrors `evidence/merge.py::apply_manual_entries` exactly in shape and spirit: a
`SELLER_ENTERED` value always supersedes a `CANONICAL_DERIVED` one for the same field, and a
field absent from both sources is `UNKNOWN` (`None`, no `field_source` entry) — never a
merge artefact, never a default. Unlike `apply_manual_entries`'s competitor-side case
(§5.3 rule 4, resolving an extraction *conflict*), a disagreement here is never `UNAVAILABLE`
— there is always a designated winner by rule (§5.5.1 "Not a conflict case").

`manual_overrides` is a plain field-name-keyed mapping, generic like
`apply_manual_entries`'s `manual` argument — not hardcoded to the five fields the seller
profile form currently exposes (category, attributes, keywords, price_paise,
fulfillment_type). This keeps the precedence rule itself general (it would apply exactly the
same way if `title` were ever entered manually — see T70/AC22b), while the actual form and
its stored columns (`seller_product_profile_repo.py`) stay deliberately scoped to the five
fields C31 locked.
"""

from __future__ import annotations

from typing import Any, Mapping

from competitor_intelligence.seller_product.types import CanonicalDerived, FieldSource, SellerProduct

# review_count/rating are permanently out of scope for the manual form (C31, §5.5.2) and have
# no canonical source either (§5.5.2's table: "none" for both). They are forced to UNKNOWN
# unconditionally, regardless of what either source happens to contain, so a future caller
# that mistakenly stuffs a value into either input map can never leak one through.
_ALWAYS_UNKNOWN_FIELDS = frozenset({"review_count", "rating"})


def merge_seller_product(
    canonical: CanonicalDerived | None,
    manual_overrides: Mapping[str, Any],
) -> SellerProduct:
    """Combines the canonical-derived view and the seller-entered profile overrides into one
    `SellerProduct`, per §5.5.1's precedence rule. `manual_overrides` should contain only the
    fields the seller has actually filled — a key with value `None` is treated the same as an
    absent key (still `UNKNOWN` from that source), matching "an unfilled form field stays
    `UNKNOWN`" (C31).

    Raises `ValueError` if neither source can supply a `product_id` — `SellerProduct.product_id`
    is not itself `KNOWN`/`UNKNOWN`-typed (§5.5) and a caller with neither source populated has
    no product to build a profile for at all.
    """
    field_source: dict[str, FieldSource] = {}

    def resolve(field_name: str, canonical_value: Any) -> Any:
        if field_name in _ALWAYS_UNKNOWN_FIELDS:
            return None
        manual_value = manual_overrides.get(field_name)
        if manual_value is not None:
            field_source[field_name] = FieldSource.SELLER_ENTERED
            return manual_value
        if canonical_value is not None:
            field_source[field_name] = FieldSource.CANONICAL_DERIVED
            return canonical_value
        return None

    canonical_product_id = canonical.product_id if canonical is not None else None
    product_id = manual_overrides.get("product_id") or canonical_product_id
    if product_id is None:
        raise ValueError(
            "merge_seller_product() cannot build a SellerProduct with no product_id from "
            "either source (canonical-derived or seller-entered)."
        )

    title = resolve("title", canonical.title if canonical is not None else None)
    category = resolve("category", None)  # §5.5.2: no canonical source for category
    price_paise = resolve("price_paise", None)  # §5.5.2: no canonical source for price
    attributes = resolve("attributes", None)  # §5.5.2: no canonical source for attributes
    keywords = resolve("keywords", None)  # §5.5.2: no canonical source for keywords
    fulfillment_type = resolve("fulfillment_type", None)  # §5.5.2: no canonical source

    canonical_last_updated = canonical.last_updated if canonical is not None else None
    manual_last_updated = manual_overrides.get("updated_at")
    # §5.5.2: "sales_line ingestion timestamps, or the profile's own edit timestamp,
    # whichever is later" — not a precedence rule (no field_source entry for this), just
    # "most recent of the two, if either exists."
    candidates = [ts for ts in (canonical_last_updated, manual_last_updated) if ts is not None]
    last_updated = max(candidates) if candidates else None

    return SellerProduct(
        product_id=product_id,
        title=title,
        category=category,
        price_paise=price_paise,
        attributes=attributes,
        keywords=keywords,
        fulfillment_type=fulfillment_type,
        review_count=None,
        rating=None,
        last_updated=last_updated,
        field_source=field_source,
    )
