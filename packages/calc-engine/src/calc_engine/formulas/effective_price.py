"""Effective price and buyer total of ONE observed competitor listing — deterministic-engine.md §5.15.2.

What a buyer actually pays for a competitor's product, from the values a seller's screenshot showed: the listed
price, any visible discount, any unconditional coupon, and the delivery charge. Not margin-aware — identical
boundary to §5.15/§5.15.1: no seller cost, fee or tax enters, and the result says nothing about the competitor's
margin or the seller's. CI supplies the observed values as `DERIVED` inputs and renders the returned rows unchanged.

The rules that matter, each pinned by a test:

1. **A missing input is not zero.** A missing listed price is `UNAVAILABLE`. A missing delivery charge makes the
   buyer total `UNAVAILABLE` (never "free delivery"); the effective price is still given. "Free delivery" is an
   explicit observed `0`, not an absence.
2. **No visible discount observed is stated as such, not guessed.** `visible_discount_paise = None` means the
   screenshot showed none; the effective price then equals the listed price and the basis says so.
3. **Only an unconditional offer with a stated amount is subtracted.** A bank-card or first-order offer (any
   `condition_text`), or an offer with no stated amount, is **excluded and named**, never silently applied —
   whether it applies to a given buyer is not observable.
4. Integer paise only; the only arithmetic is addition and subtraction.
5. An effective price at or below zero is `UNAVAILABLE` (the observed values contradict each other), not clamped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from calc_engine.types import Paise, Unavailable


@dataclass(frozen=True, slots=True)
class ObservedOffer:
    """One offer a screenshot showed. `condition_text` is the buyer-side condition ("with HDFC card", "first order");
    `None` means the offer is shown as applying to every buyer."""

    kind: str
    amount_paise: int | None
    condition_text: str | None = None


@dataclass(frozen=True, slots=True)
class ExcludedOffer:
    offer: ObservedOffer
    reason: str  # CONDITIONAL | NO_AMOUNT


@dataclass(frozen=True, slots=True)
class EffectivePrice:
    listed: Paise
    visible_discount: Paise
    discount_observed: bool
    applied_offers: tuple[ObservedOffer, ...]
    unconditional_offer_total: Paise
    effective: Paise
    delivery: Paise | None
    buyer_total: Paise | None
    excluded_offers: tuple[ExcludedOffer, ...]


def compute_effective_price(
    *,
    listed_paise: int | None,
    visible_discount_paise: int | None,
    delivery_charge_paise: int | None,
    offers: Sequence[ObservedOffer] = (),
) -> EffectivePrice | Unavailable:
    if listed_paise is None:
        return Unavailable("LISTED_PRICE_NOT_OBSERVED", ("listed_price_paise",))
    if listed_paise <= 0:
        return Unavailable("LISTED_PRICE_NOT_POSITIVE")
    if visible_discount_paise is not None and visible_discount_paise < 0:
        return Unavailable("VISIBLE_DISCOUNT_NEGATIVE")
    if delivery_charge_paise is not None and delivery_charge_paise < 0:
        return Unavailable("DELIVERY_CHARGE_NEGATIVE")

    applied: list[ObservedOffer] = []
    excluded: list[ExcludedOffer] = []
    for offer in offers:
        if offer.condition_text:
            excluded.append(ExcludedOffer(offer, "CONDITIONAL"))
        elif offer.amount_paise is None or offer.amount_paise <= 0:
            excluded.append(ExcludedOffer(offer, "NO_AMOUNT"))
        else:
            applied.append(offer)

    discount = Paise(visible_discount_paise or 0)
    offer_total = Paise(sum(o.amount_paise for o in applied if o.amount_paise is not None))
    effective = Paise(listed_paise) - discount - offer_total
    if effective.value <= 0:
        return Unavailable("DISCOUNTS_EXCEED_LISTED_PRICE")

    delivery = Paise(delivery_charge_paise) if delivery_charge_paise is not None else None
    return EffectivePrice(
        listed=Paise(listed_paise),
        visible_discount=discount,
        discount_observed=visible_discount_paise is not None,
        applied_offers=tuple(applied),
        unconditional_offer_total=offer_total,
        effective=effective,
        delivery=delivery,
        buyer_total=(effective + delivery) if delivery is not None else None,
        excluded_offers=tuple(excluded),
    )
