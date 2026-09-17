"""SellerFundedDiscounts / MarketplaceFundedDiscounts — deterministic-engine.md §5.3.

SellerFundedDiscounts(line) =
      Σ[SELLER_DISCOUNT]
    + Σ[SHIPPING_DISCOUNT   where bearer = SELLER]
    + Σ[PLATFORM_DISCOUNT   where bearer = SELLER]
    + Σ[CASHBACK_DISCOUNT   where bearer = SELLER]
    + Σ[* where bearer = UNKNOWN]                       -- conservative default (D2)

MarketplaceFundedDiscounts(line) = Σ[* where bearer = MARKETPLACE]   -- disclosure only, never in NRR (R2)
"""

from __future__ import annotations

from typing import Sequence

from calc_engine.formulas.component_sum import BearerResolver, sum_components
from calc_engine.types import Bearer, CanonicalLine, Paise

_DISCOUNT_KIND = "DISCOUNT"
_UNCONDITIONAL_CODES = frozenset({"SELLER_DISCOUNT"})


def seller_funded_discounts(lines: Sequence[CanonicalLine], bearer_resolver: BearerResolver) -> Paise:
    """§5.3. `SELLER_DISCOUNT` is summed unconditionally (the spec's own literal
    `Σ[SELLER_DISCOUNT]` term carries no bearer filter), so the bearer=UNKNOWN wildcard term
    below explicitly excludes that code via `exclude_codes` — this holds regardless of what a
    bearer_resolver happens to return for `SELLER_DISCOUNT` (a resolver with no explicit
    mapping legitimately resolves anything to UNKNOWN, so this cannot be left as an unenforced
    assumption about resolver behaviour).
    """
    unconditional_seller = sum_components(
        lines, component_codes=frozenset({"SELLER_DISCOUNT"}), component_kind=_DISCOUNT_KIND
    )
    shipping_seller = sum_components(
        lines,
        component_codes=frozenset({"SHIPPING_DISCOUNT"}),
        component_kind=_DISCOUNT_KIND,
        bearer=Bearer.SELLER,
        bearer_resolver=bearer_resolver,
    )
    platform_seller = sum_components(
        lines,
        component_codes=frozenset({"PLATFORM_DISCOUNT"}),
        component_kind=_DISCOUNT_KIND,
        bearer=Bearer.SELLER,
        bearer_resolver=bearer_resolver,
    )
    cashback_seller = sum_components(
        lines,
        component_codes=frozenset({"CASHBACK_DISCOUNT"}),
        component_kind=_DISCOUNT_KIND,
        bearer=Bearer.SELLER,
        bearer_resolver=bearer_resolver,
    )
    unknown_bearer_any_code = sum_components(
        lines,
        component_codes=None,
        component_kind=_DISCOUNT_KIND,
        bearer=Bearer.UNKNOWN,
        bearer_resolver=bearer_resolver,
        exclude_codes=_UNCONDITIONAL_CODES,
    )
    return unconditional_seller + shipping_seller + platform_seller + cashback_seller + unknown_bearer_any_code


def unknown_bearer_discount_amount(lines: Sequence[CanonicalLine], bearer_resolver: BearerResolver) -> Paise:
    """The portion of seller_funded_discounts contributed by the bearer=UNKNOWN fallback (D2).

    Exposed separately so callers can flag the resulting figure DERIVED (E13) rather than
    silently presenting it at the same confidence as a fully-resolved bearer."""
    return sum_components(
        lines,
        component_codes=None,
        component_kind=_DISCOUNT_KIND,
        bearer=Bearer.UNKNOWN,
        bearer_resolver=bearer_resolver,
        exclude_codes=_UNCONDITIONAL_CODES,
    )


def marketplace_funded_discounts(lines: Sequence[CanonicalLine], bearer_resolver: BearerResolver) -> Paise:
    """§5.3, R2. Disclosure only — this value must never be subtracted from NetRealizedRevenue."""
    return sum_components(
        lines,
        component_codes=None,
        component_kind=_DISCOUNT_KIND,
        bearer=Bearer.MARKETPLACE,
        bearer_resolver=bearer_resolver,
    )
