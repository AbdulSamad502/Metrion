"""Core types: Paise, Confidence, RecognitionState, Bearer, CanonicalLine, ComponentRow.

See docs/specs/deterministic-engine.md §4 (determinism contract) and §9 (provenance).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from fractions import Fraction
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Paise:
    """Signed integer paise. The only money type in this package — never float (AC3)."""

    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError(f"Paise must wrap int, got {type(self.value).__name__}")

    def __add__(self, other: "Paise") -> "Paise":
        return Paise(self.value + other.value)

    def __sub__(self, other: "Paise") -> "Paise":
        return Paise(self.value - other.value)

    def __neg__(self) -> "Paise":
        return Paise(-self.value)

    def __mul__(self, n: int) -> "Paise":
        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError(f"Paise can only be multiplied by an int, got {type(n).__name__}")
        return Paise(self.value * n)

    def __lt__(self, other: "Paise") -> bool:
        return self.value < other.value

    def __le__(self, other: "Paise") -> bool:
        return self.value <= other.value

    def __gt__(self, other: "Paise") -> bool:
        return self.value > other.value

    def __ge__(self, other: "Paise") -> bool:
        return self.value >= other.value

    def __abs__(self) -> "Paise":
        return Paise(abs(self.value))

    # Deliberately NO __truediv__ / __floordiv__: any division must go through
    # rounding.round_half_up_paise() or rounding.largest_remainder_allocate(),
    # so rounding is never an ad-hoc decision at a call site (§5.11, D8).


ZERO = Paise(0)


def sum_paise(values: "list[Paise] | tuple[Paise, ...]") -> Paise:
    total = ZERO
    for v in values:
        total = total + v
    return total


class Confidence(str, Enum):
    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    DERIVED = "DERIVED"
    MANUAL = "MANUAL"


# Rank order per data-foundation.md §7.1: 1 = strongest, 4 = weakest.
_CONFIDENCE_RANK: dict[Confidence, int] = {
    Confidence.VERIFIED: 1,
    Confidence.PROVISIONAL: 2,
    Confidence.DERIVED: 3,
    Confidence.MANUAL: 4,
}


def combine_confidence(*levels: Confidence) -> Confidence:
    """Confidence is monotonic under aggregation: the weakest input wins (data-foundation.md §7.1).

    "A figure can never present as more certain than its weakest input."
    """
    if not levels:
        raise ValueError("combine_confidence requires at least one Confidence level")
    return max(levels, key=lambda c: _CONFIDENCE_RANK[c])


class RecognitionState(str, Enum):
    RECOGNISED = "RECOGNISED"
    REALIZED = "REALIZED"
    UNAVAILABLE = "UNAVAILABLE"


class Bearer(str, Enum):
    SELLER = "SELLER"
    MARKETPLACE = "MARKETPLACE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class Unavailable:
    """A formula's result when a required input is missing. Never a silent zero (AC8)."""

    reason: str
    missing_inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ComponentRow:
    """Mirrors data-foundation.md §1.4 `line_component` (read-only, engine never writes here)."""

    id: UUID
    component_kind: str  # DISCOUNT | FEE | CHARGE | TAX | LEVY
    component_code: str
    source_side: str  # INVOICE | SETTLEMENT
    amount: Paise
    tax_amount: Paise | None = None
    rate_pct: Fraction | None = None
    source_row_ref: UUID | None = None


@dataclass(frozen=True, slots=True)
class CanonicalLine:
    """Mirrors the relevant fields of data-foundation.md §1.3 `sales_line`, plus overlay fields
    resolved from manual_adjustment/source data before this object is constructed — formulas
    never see a manual_adjustment row directly.

    Each of the three status fields below is **tri-state per marketplace capability**, not
    binary — `None` means "this marketplace cannot yet tell us this line's status at all"
    (C1/C2: true for Amazon/Flipkart cancellation and RTO today), which is a materially
    different fact from "resolved, and the answer is no." Collapsing those two states into one
    would silently misreport an unsupported marketplace as "nothing happened" instead of
    UNAVAILABLE (AC8). See formulas/revenue_reductions.py for how each state is consumed.
    """

    sales_line_id: UUID
    marketplace: str
    document_type: str
    quantity: int
    invoice_date: date | None
    dispatch_date: date | None
    order_date: date | None
    gross_item_amount: Paise  # already GST-normalised to tax-exclusive (§8.1) before formulas see it
    components: tuple[ComponentRow, ...]
    confidence: Confidence

    # Cancellation (§5.4, C1/A6). None = not resolvable for this marketplace (Amazon/Flipkart
    # today) -> UNAVAILABLE. "CANCELLED" = cancelled -> full reversal. Any other non-None value
    # (e.g. Meesho's "DELIVERED", "RTO_COMPLETE") = resolved, not cancelled -> reversal is zero.
    cancellation_state: str | None = None

    # Return (§5.4/§5.7, C1/A6). None = not resolvable for this marketplace -> UNAVAILABLE.
    # "RETURNED" = a return occurred. Any other non-None value = resolved, no return -> zero.
    return_status: str | None = None
    returned_qty: int = 0
    # Resolved refund value when return_status == "RETURNED" (from settlement data or a
    # return_refund_amount manual_adjustment, §7.3). None with return_status == "RETURNED"
    # means the amount is genuinely not yet known -> UNAVAILABLE, never zero.
    refunded_amount: Paise | None = None

    # RTO (§5.4/§5.7, C2/A7). None = not resolvable for this marketplace (Amazon/Flipkart
    # today) -> UNAVAILABLE. "RTO" = this line was returned-to-origin. Any other non-None
    # value = resolved, not RTO'd -> zero.
    rto_status: str | None = None
    rto_qty: int = 0
    # RECOVERED_SELLABLE | RECOVERED_DAMAGED | LOST. Even where rto_status == "RTO" is known
    # (Meesho, A7), no marketplace reports the condition of returned goods — this always
    # requires a seller-declared rto_outcome manual_adjustment. None here means "RTO confirmed
    # but outcome not yet classified" -> COGS/ReturnRTOLosses UNAVAILABLE for this line, even
    # though RTOUnrecoveredRevenue (which only needs rto_status) can still be computed.
    rto_outcome: str | None = None

    # Quarantine (E16, AC11, data-foundation.md's validation layer — e.g. V-TAX-001,
    # V-QTY-001). The *decision* to quarantine a row belongs to data-foundation's ingestion
    # validation, not this engine — but this engine owns the *disclosure* obligation: a
    # quarantined line must be excluded from every aggregate and named, with its rule id, in
    # that aggregate's `exclusions`, never silently dropped. Empty tuple = not quarantined.
    quarantine_rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricValue:
    """A formula's successful result, pre-persistence. api.compute_metric() wraps this into a
    metric_result row and mints the engine_result_ref (§9); formulas never construct a
    metric_result themselves.
    """

    value: Paise
    confidence: Confidence
    recognition_state: RecognitionState
    calculation_basis: str
    input_refs: tuple[Any, ...] = ()
    exclusions: tuple[dict[str, Any], ...] = ()
