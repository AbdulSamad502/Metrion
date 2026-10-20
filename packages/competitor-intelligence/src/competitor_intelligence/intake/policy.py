"""Seller-confirmation policy — competitor-intelligence-agent.md §6.23 (C37, D15).

Decides, per extracted field, whether the seller must be asked — by **consequence**, not for
every field. Pure functions over (field name, source, presence, conflict): no I/O, no LLM.

A field is *consequential* if, once stored as a verified observation, it would feed Brain 1,
create or suppress a delta or alert, or assert product identity. For listing evidence that is
the price, the visible discount (it changes the effective price) and availability. Everything
else — rating, review count, listing copy, category — is non-consequential and is stored as
read, shown to the seller in the CEO's summary, and correctable without a prompt.

While Q18 stands (measured vision price accuracy 13/31, extractor emits no ambiguity flag), a
vision-extracted consequential field is **always** confirmed. The tuple below is the single
place that list lives, so relaxing it later is a one-line, reviewed change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from competitor_intelligence.types import Confidence

# Delivery charge and offers feed Brain 1's effective-price comparison (deterministic-engine.md 5.15.2), so they are consequential too (CI spec C44).
CONSEQUENTIAL_FIELDS: tuple[str, ...] = ("listed_price_paise", "visible_discount_paise", "availability", "delivery_charge_paise", "offers")


class FieldAction(str, Enum):
    STORE = "STORE"
    ASK_SELLER = "ASK_SELLER"
    LEAVE_UNKNOWN = "LEAVE_UNKNOWN"


class AskReason(str, Enum):
    CONSEQUENTIAL_FIELD = "CONSEQUENTIAL_FIELD"
    CONFLICT = "CONFLICT"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class FieldDecision:
    field_name: str
    action: FieldAction
    consequential: bool
    reason: AskReason | None = None


def is_consequential(field_name: str) -> bool:
    return field_name in CONSEQUENTIAL_FIELDS


def decide_field(
    field_name: str,
    *,
    source: Confidence | None,
    present: bool,
    conflict: bool = False,
    needed_for_request: bool = False,
) -> FieldDecision:
    """`needed_for_request` is True when the seller asked for something that requires this
    field (e.g. a price comparison needs the competitor price). A missing field is asked about
    only if it is consequential **and** needed — otherwise it stays `UNKNOWN`, unprompted."""
    consequential = is_consequential(field_name)

    if conflict:
        return FieldDecision(field_name, FieldAction.ASK_SELLER, consequential, AskReason.CONFLICT)

    if not present:
        if consequential and needed_for_request:
            return FieldDecision(field_name, FieldAction.ASK_SELLER, True, AskReason.MISSING)
        return FieldDecision(field_name, FieldAction.LEAVE_UNKNOWN, consequential)

    if source is Confidence.SELLER_ENTERED:
        return FieldDecision(field_name, FieldAction.STORE, consequential)  # verified on entry

    if consequential:
        return FieldDecision(field_name, FieldAction.ASK_SELLER, True, AskReason.CONSEQUENTIAL_FIELD)

    return FieldDecision(field_name, FieldAction.STORE, False)
