"""`SellerProduct` data shapes — competitor-intelligence-agent.md §5.5.

Deliberately plain dataclasses, not ORM models: this contract is read by relevance-scoring
(a future checkpoint) and by the profile API, never persisted as a row in its own right —
`SellerProduct` is a *merged* view over two other sources (§5.5.1), not a table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

Paise = int


class FieldSource(str, Enum):
    """§5.5/C31 — a *source* marker (which of the two inputs produced a populated field),
    distinct from and never conflated with §5.1's `Confidence` vocabulary (that enum answers
    a different question: how a *competitor-side* value was captured)."""

    CANONICAL_DERIVED = "CANONICAL_DERIVED"
    SELLER_ENTERED = "SELLER_ENTERED"


@dataclass(frozen=True, slots=True)
class CanonicalDerived:
    """§5.5.1 Source 1 — the read-only view over `sales_line` (`derive.py`). Only the three
    fields `sales_line` can actually supply (§5.5.2): `product_id`, `title`, `last_updated`.
    Never carries `price` — `sales_line.gross_item_amount` is a transacted amount, not a
    listing price, and using it here would be exactly the kind of inference C30 forbids."""

    product_id: str
    title: str | None
    last_updated: datetime | None


@dataclass(frozen=True, slots=True)
class SellerProduct:
    """§5.5 — the merged baseline contract. `field_source` is populated only for fields that
    are `KNOWN`; a field's absence from `field_source` (and its `None` value) means
    `UNKNOWN` — never a default, never an inference. `review_count`/`rating` are always
    `None` and never appear in `field_source` — out of the manual form's scope by decision
    (C31, §5.5.2) and CI has no other way to obtain the seller's own review data."""

    product_id: str
    title: str | None
    category: str | None
    price_paise: Paise | None
    attributes: tuple[tuple[str, str], ...] | None
    keywords: tuple[str, ...] | None
    fulfillment_type: str | None
    review_count: None
    rating: None
    last_updated: datetime | None
    field_source: Mapping[str, FieldSource] = field(default_factory=dict)

    def is_known(self, field_name: str) -> bool:
        return field_name in self.field_source
