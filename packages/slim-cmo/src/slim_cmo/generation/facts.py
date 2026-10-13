"""Seller facts -> the claim context a generation is allowed to use (P3 decision 2, spec C7, C9).

Rules (all deterministic):

* `TARGET_PRICE` and `NICHE` facts NEVER feed copy. A `TARGET_PRICE` row's value is not even read
  (C7/AC18: CMO writes no price). Attributes whose NAME is a price word are excluded as well.
* Latest row wins per `(fact_type, attribute_name)` (names compared case/whitespace-folded).
  An UNNAMED `FREE_TEXT` fact has no such key, so every distinct note is kept.
* `FREE_TEXT` is CONTEXT ONLY: shown to the model as a seller note, never a structured attribute,
  and NOT part of the "allowed context" the output checks use - so a number that appears only in a
  note is an unsupported number. Notes containing price, tax or contact content are dropped.
* Every attribute then goes through `claims.partition`: only eligible ones may be shown to the
  model as facts; ineligible ones (an ESTIMATED value, an UNVERIFIED_HINT image attribute) are kept
  ONLY so the output check can detect their values leaking into copy. They are never prompted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from slim_cmo.claims import (
    Attribute,
    EligibilityReason,
    allowed_context_text,
    partition,
)
from slim_cmo.forbidden import ForbiddenCategory, scan_forbidden
from slim_cmo.textnorm import collapse_whitespace, skeleton
from slim_cmo.types import AttributeBasis, SellerFactType

_PRICE_NAME_WORDS = frozenset({"price", "pricing", "mrp"})
_NOTE_BLOCKING_CATEGORIES = frozenset({ForbiddenCategory.PRICE, ForbiddenCategory.TAX, ForbiddenCategory.CONTACT})
_WORD = re.compile(r"[^\W_]+", re.UNICODE)

_NOT_FOR_COPY = frozenset({SellerFactType.NICHE, SellerFactType.TARGET_PRICE})


@dataclass(frozen=True, slots=True)
class FactInput:
    """One seller fact as a stored row or an inline request field. `value` for a TARGET_PRICE row
    is never read."""

    fact_type: SellerFactType
    value: str | None
    attribute_name: str | None = None
    provided_at: datetime | None = None  # must be timezone-aware when present
    fact_id: str | None = None


@dataclass(frozen=True, slots=True)
class FactContext:
    eligible: tuple[Attribute, ...]
    ineligible: tuple[tuple[Attribute, EligibilityReason], ...]
    notes: tuple[str, ...]
    fact_ids: tuple[str, ...]
    excluded: tuple[str, ...]  # 'FACT_TYPE:name:REASON' - provenance of what was deliberately left out

    @property
    def allowed_context(self) -> str:
        """Everything the output may say, as one string: eligible attribute names and values only."""
        return allowed_context_text(self.eligible)


def _display_name(fact: FactInput) -> str:
    raw = collapse_whitespace(fact.attribute_name or "")
    return raw or fact.fact_type.value.lower()


def _key(fact: FactInput) -> tuple[str, str]:
    return (fact.fact_type.value, _display_name(fact).casefold())


def _rank(fact: FactInput) -> tuple[int, datetime | None]:
    return (0, None) if fact.provided_at is None else (1, fact.provided_at)


def is_price_name(name: str) -> bool:
    return bool(set(_WORD.findall(skeleton(name))) & _PRICE_NAME_WORDS)


def image_attributes(raw: Sequence[Mapping[str, Any]]) -> tuple[Attribute, ...]:
    """`product_image_analysis.attributes` -> Attribute. Basis and trust_state are carried as stored;
    `claims.assess` keeps every `UNVERIFIED_HINT` ineligible (AC20) and treats any unrecognised
    basis as ineligible (fail closed). No vision call happens here (P6)."""
    out: list[Attribute] = []
    for item in raw:
        value = item.get("value")
        out.append(
            Attribute(
                name=str(item.get("name", "")),
                value=None if value is None else str(value),
                basis=str(item.get("basis", "")) or AttributeBasis.UNKNOWN,
                trust_state=item.get("trust_state"),
            )
        )
    return tuple(out)


def _later(candidate: FactInput, current: FactInput) -> bool:
    a, b = _rank(candidate), _rank(current)
    if a[0] != b[0]:
        return a[0] > b[0]
    if a[1] is None or b[1] is None:
        return True  # both undated: the later row wins
    return a[1] >= b[1]


def build_fact_context(facts: Sequence[FactInput], image_attrs: Sequence[Attribute] = ()) -> FactContext:
    excluded: list[str] = []
    winners: dict[tuple[str, str], FactInput] = {}
    unnamed_notes: list[FactInput] = []

    for fact in facts:
        if fact.fact_type in _NOT_FOR_COPY:
            excluded.append(f"{fact.fact_type.value}:{_display_name(fact)}:NOT_USED_IN_COPY")
            continue
        if fact.fact_type is SellerFactType.FREE_TEXT and not collapse_whitespace(fact.attribute_name or ""):
            unnamed_notes.append(fact)
            continue
        key = _key(fact)
        current = winners.get(key)
        if current is None or _later(fact, current):
            winners[key] = fact

    attributes: list[Attribute] = []
    notes: list[str] = []
    fact_ids: list[str] = []

    def add_note(fact: FactInput) -> None:
        text = collapse_whitespace(fact.value or "")
        if not text:
            return
        if any(f.category in _NOTE_BLOCKING_CATEGORIES for f in scan_forbidden(text)):
            excluded.append(f"FREE_TEXT:{_display_name(fact)}:BLOCKED_CONTENT")
            return
        if text not in notes:
            notes.append(text)
            if fact.fact_id:
                fact_ids.append(fact.fact_id)

    for fact in unnamed_notes:
        add_note(fact)

    for _key_, fact in sorted(winners.items()):
        name = _display_name(fact)
        if fact.fact_type is SellerFactType.FREE_TEXT:
            add_note(fact)
            continue
        if is_price_name(name):
            excluded.append(f"{fact.fact_type.value}:{name}:PRICE_NAMED")
            continue
        attributes.append(Attribute(name=name, value=fact.value, basis=AttributeBasis.SELLER_PROVIDED))
        if fact.fact_id:
            fact_ids.append(fact.fact_id)

    parts = partition([*attributes, *image_attrs])
    return FactContext(
        eligible=parts.eligible,
        ineligible=parts.ineligible,
        notes=tuple(notes),
        fact_ids=tuple(fact_ids),
        excluded=tuple(excluded),
    )


MIN_DETAIL_FACTS = 2  # a writing-quality heuristic, not a marketplace or business rule: fewer confirmed details than this and the writing is flagged as thin
_NOT_A_DETAIL = frozenset({"product_name", "category"})


def is_thin_input(ctx: FactContext) -> bool:
    """True when fewer than `MIN_DETAIL_FACTS` claim-eligible details (brand, size, material, features...) beyond the product name and category were confirmed. Counted from the same
    eligible facts the model is shown, so it can never be satisfied by a hint or an estimate."""
    return sum(1 for a in ctx.eligible if a.name.strip().casefold() not in _NOT_A_DETAIL) < MIN_DETAIL_FACTS


# Public names for the latest-wins helpers, so other layers (catalog Q&A) apply the SAME precedence
# rather than re-implementing it.
fact_key = _key
is_later = _later
fact_display_name = _display_name
