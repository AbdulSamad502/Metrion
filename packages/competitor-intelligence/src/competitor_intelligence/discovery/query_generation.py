"""Research query generation — competitor-intelligence-agent.md §6.10/§6.11, C21.

Given a `SellerProduct` baseline (`seller_product/types.py`, §5.5 — imported and reused,
never redefined here), composes the six locked query kinds
(`ci_search_query.query_kind`, §5.4) and enforces the §6.11 query privacy boundary as an
explicit, testable allow/deny filter — never an implicit convention.

Rule order, matching §6.11 exactly:
1. `discovery_enabled = false` is checked by the caller *before* this module is ever
   invoked (§6.11 rule 1, AC17) — this module has no opinion on the flag and composes
   queries unconditionally when called; gating discovery entirely is the runner's job
   (`query_runner.py`), not this one's.
2. Every composed query is built ONLY from the permitted source list (§6.11): generic
   product name/category, non-sensitive attributes, generic intent terms, and the seller's
   own public listing keywords. `SellerProduct.product_id` (an internal SKU/product-id
   reference, §5.4) is never used as query material.
3. The composed text is then run through `check_query_privacy` — a second, independent
   check against the full composed string, not just its inputs (§6.11 rule 2: "a query
   assembled from permitted parts can still leak if a free-text field is concatenated in
   unchecked").
4. A query that fails step 3 is dropped, with a reason naming the violated category —
   never the offending text itself, and the pre-redaction draft is never returned to a
   caller that might persist it (§6.11 rules 3-4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from competitor_intelligence.seller_product.types import SellerProduct


class QueryKind(str, Enum):
    """`ci_search_query.query_kind` (§5.4) — the six locked categories (§6.10)."""

    PRODUCT_TERM = "PRODUCT_TERM"
    CATEGORY_TERM = "CATEGORY_TERM"
    FEATURE_TERM = "FEATURE_TERM"
    INTENT_PHRASE = "INTENT_PHRASE"
    SUBSTITUTE_TERM = "SUBSTITUTE_TERM"
    KEYWORD_TERM = "KEYWORD_TERM"


@dataclass(frozen=True, slots=True)
class GeneratedQuery:
    """A query cleared for dispatch — `query_text` is exactly the post-redaction text a
    `SearchProvider` would receive and `ci_search_query.query_text` would store (§6.11
    rule 4)."""

    kind: QueryKind
    query_text: str


@dataclass(frozen=True, slots=True)
class DroppedQuery:
    """A query that failed the privacy filter and was never sent. `reason` names the
    violated category only — the composed draft text is deliberately not carried on this
    object, so nothing downstream can accidentally log or persist it (§6.11 rules 3-4)."""

    kind: QueryKind
    reason: str


@dataclass(frozen=True, slots=True)
class QueryGenerationResult:
    sent: tuple[GeneratedQuery, ...]
    dropped: tuple[DroppedQuery, ...]


# Generic, non-product-specific intent modifiers (§6.11: "generic customer-intent terms").
_INTENT_MODIFIERS: tuple[str, ...] = ("budget", "best", "cheap", "premium")

# §6.11 "Never sent externally" — a keyword denylist covering each named forbidden
# category. Matched case-insensitively as whole words/phrases against the FULL composed
# query text, independent of which fields fed it (rule 2). Grouped by category so a
# rejection can name which rule was violated (never the offending text itself).
_FORBIDDEN_TERMS: dict[str, tuple[str, ...]] = {
    "INTERNAL_SKU_OR_PRODUCT_ID": (
        "sku",
        "internal id",
        "internal-id",
        "product id",
        "item id",
    ),
    "SUPPLIER_OR_SOURCING": (
        "supplier",
        "vendor",
        "sourcing",
        "manufacturer contact",
        "wholesale rate",
    ),
    "MARGIN_OR_COST_DATA": (
        "margin",
        "cogs",
        "cost price",
        "cost of goods",
        "landed cost",
        "unit cost",
    ),
    "SALES_VOLUME_OR_AD_SPEND": (
        "units sold",
        "sales volume",
        "ad spend",
        "ad-spend",
        "ppc spend",
        "acos",
    ),
    "PROPRIETARY_POSITIONING": (
        "internal only",
        "confidential",
        "do not share",
        "positioning strategy",
    ),
}

_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {
    term: re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE) for terms in _FORBIDDEN_TERMS.values() for term in terms
}


@dataclass(frozen=True, slots=True)
class PrivacyViolation:
    category: str
    term: str


def check_query_privacy(query_text: str, *, internal_identifiers: tuple[str, ...] = ()) -> PrivacyViolation | None:
    """The §6.11 allow/deny filter, applied server-side to the fully composed query text
    (rule 2) — never to its inputs alone. Returns the first violation found, or `None` if
    the text is safe to send.

    `internal_identifiers` lets a caller flag values that must never appear verbatim in a
    query even though they don't match a generic keyword — chiefly `SellerProduct.product_id`
    itself (an internal SKU/marketplace-item-id reference, §5.4), which is exactly the kind
    of "internal SKU code" §6.11 forbids outright.
    """
    for identifier in internal_identifiers:
        if identifier and identifier.lower() in query_text.lower():
            return PrivacyViolation(category="INTERNAL_SKU_OR_PRODUCT_ID", term=identifier)

    for category, terms in _FORBIDDEN_TERMS.items():
        for term in terms:
            if _WORD_BOUNDARY_CACHE[term].search(query_text):
                return PrivacyViolation(category=category, term=term)

    return None


_NOT_FEATURES = frozenset({"title", "marketplace", "test_fixture"})
_PARENTHETICAL = re.compile(r"\s*[(\[][^)\]]*[)\]]")


def _clean(value: str | None) -> str | None:
    """A term as a search engine should see it: bracketed side notes such as "(CI TEST)" or "[Pack of 2]" are not part of what the product is, and are left out."""
    if not value:
        return value
    return " ".join(_PARENTHETICAL.sub(" ", value).split()) or None


def _compose(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def generate_queries(seller_product: SellerProduct) -> QueryGenerationResult:
    """Builds the six query kinds from ONLY the permitted source fields (§6.11) —
    `title`/`category` for product and category terms, `attributes` for feature terms,
    generic intent-modifier templates combined with the product name for intent phrases,
    a generic "alternative to <product>" template for substitute terms, and `keywords`
    (public listing keywords, explicitly permitted) for market/keyword terms.
    `seller_product.product_id` never feeds any of these compositions.

    An `UNKNOWN` field (absent from `field_source`, C30/AC22) simply yields no query of the
    kind that depends on it — never a default, never an invented placeholder.
    """
    attributes = [(k, v) for k, v in (seller_product.attributes or ())]
    # A product the seller described in their own profile has no sales title: its own "title" attribute names it. Neither the title nor the marketplace is a product FEATURE.
    title_attr = next((v for k, v in attributes if str(k).strip().casefold() == "title" and v), None)
    product_name = _clean(seller_product.title or title_attr)
    category = _clean(seller_product.category)
    internal_identifiers = (seller_product.product_id,)

    candidates: list[tuple[QueryKind, str]] = []

    if product_name:
        candidates.append((QueryKind.PRODUCT_TERM, product_name))

    if category:
        candidates.append((QueryKind.CATEGORY_TERM, category))

    for _key, raw_value in attributes:
        if str(_key).strip().casefold() in _NOT_FEATURES:
            continue
        value = _clean(raw_value)
        if not value:
            continue
        if product_name:
            candidates.append((QueryKind.FEATURE_TERM, _compose([product_name, value])))
        else:
            candidates.append((QueryKind.FEATURE_TERM, value))

    if product_name:
        for modifier in _INTENT_MODIFIERS:
            candidates.append((QueryKind.INTENT_PHRASE, _compose([modifier, product_name])))

    if product_name:
        candidates.append((QueryKind.SUBSTITUTE_TERM, _compose(["alternative to", product_name])))
    elif category:
        candidates.append((QueryKind.SUBSTITUTE_TERM, _compose(["alternative to", category])))

    if seller_product.keywords:
        for keyword in seller_product.keywords:
            if cleaned := _clean(keyword):
                candidates.append((QueryKind.KEYWORD_TERM, cleaned))

    sent: list[GeneratedQuery] = []
    dropped: list[DroppedQuery] = []
    for kind, text in candidates:
        violation = check_query_privacy(text, internal_identifiers=internal_identifiers)
        if violation is None:
            sent.append(GeneratedQuery(kind=kind, query_text=text))
        else:
            dropped.append(
                DroppedQuery(
                    kind=kind,
                    reason=f"forbidden term in category {violation.category}",
                )
            )

    return QueryGenerationResult(sent=tuple(sent), dropped=tuple(dropped))
