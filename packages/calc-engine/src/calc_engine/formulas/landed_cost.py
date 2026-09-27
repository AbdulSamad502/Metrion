"""landed_cost — deterministic-engine.md §5.13.1 (`landed_cost(manual_adjustment_ref, sku,
quantity)`), §7.2.1 (`supplier.quote` field registry), §7.3 (supplier quote data for CFO
ranking).

Unlike `cost_components.py`'s COGS handling, there is no "missing seller cost" case here to
model as `Unavailable`: a `supplier.quote` is opt-in seller-declared data (§7.3), and a quote
that is missing its `unit_cost_paise` or `supplier_name` is not a partially-known quote, it is
a malformed one — `parse_supplier_quote_adjustment` raises rather than inventing a zero, the
same convention as `parse_expense_pool_adjustment`. Once parsed, `landed_cost_per_unit`'s only
remaining invalid case is a caller bug (`quantity <= 0`), which also raises (mirroring
`billable_quantity`'s negative-value `ValueError`) rather than returning `Unavailable` — there
is no genuinely-missing-input path left in this formula once parsing has already gated the one
real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Paise


@dataclass(frozen=True, slots=True)
class LandedCostQuote:
    """One `supplier.quote` manual_adjustment (§7.2.1): `{supplier_name, sku?, unit_cost_paise,
    moq?, lead_time_days?, shipping_paise?, payment_terms?, reliability_note?}`."""

    supplier_name: str
    sku: str | None
    unit_cost_paise: Paise
    moq: int | None
    lead_time_days: int | None
    shipping_paise: Paise | None
    payment_terms: str | None
    reliability_note: str | None


def parse_supplier_quote_adjustment(value: dict[str, object]) -> LandedCostQuote:
    """§7.2.1 `supplier.quote` shape. `supplier_name` and `unit_cost_paise` are both required —
    a quote naming no supplier, or with no cost, isn't a usable quote, and neither is silently
    treated as absent/zero (that would hide a real data-entry problem, mirroring
    `parse_expense_pool_adjustment`'s handling of `amount_paise`). Every other field is parsed
    leniently: `None` if absent or wrong type, never raising."""
    supplier_name = value.get("supplier_name")
    if not isinstance(supplier_name, str):
        raise ValueError(f"supplier quote adjustment missing/invalid supplier_name: {value!r}")

    unit_cost_paise = value.get("unit_cost_paise")
    if not isinstance(unit_cost_paise, int) or isinstance(unit_cost_paise, bool):
        raise ValueError(f"supplier quote adjustment missing/invalid unit_cost_paise: {value!r}")

    sku = value.get("sku")
    moq = value.get("moq")
    lead_time_days = value.get("lead_time_days")
    shipping_raw = value.get("shipping_paise")
    payment_terms = value.get("payment_terms")
    reliability_note = value.get("reliability_note")

    return LandedCostQuote(
        supplier_name=supplier_name,
        sku=sku if isinstance(sku, str) else None,
        unit_cost_paise=Paise(unit_cost_paise),
        moq=moq if isinstance(moq, int) and not isinstance(moq, bool) else None,
        lead_time_days=(
            lead_time_days if isinstance(lead_time_days, int) and not isinstance(lead_time_days, bool) else None
        ),
        shipping_paise=(
            Paise(shipping_raw) if isinstance(shipping_raw, int) and not isinstance(shipping_raw, bool) else None
        ),
        payment_terms=payment_terms if isinstance(payment_terms, str) else None,
        reliability_note=reliability_note if isinstance(reliability_note, str) else None,
    )


def landed_cost_per_unit(quote: LandedCostQuote, quantity: int) -> Paise:
    """`unit_cost_paise` plus `shipping_paise` (if any) divided evenly across `quantity` units,
    rounded to one paise via `round_half_up_paise` (§5.11) — the primitive this codebase uses
    wherever a division must collapse to a single representative value, as distinct from
    `largest_remainder_allocate`, which is for splitting a pool across multiple named
    recipients that each keep their own persisted, sum-exact share (D8). Landed cost per unit
    is the former: every unit of a batch is quoted the same per-unit figure, not N different
    figures — using the allocator here and picking one recipient's share would introduce a
    systematic rounding bias into whichever recipient was picked, which this function must not
    do.

    `quantity <= 0` is a caller bug, not missing seller data — it raises `ValueError`, mirroring
    `billable_quantity`'s negative-value case, rather than returning `Unavailable`."""
    if quantity <= 0:
        raise ValueError(
            f"landed_cost_per_unit requires quantity > 0 for supplier {quote.supplier_name!r}: "
            f"quantity={quantity}"
        )
    if quote.shipping_paise is None:
        return quote.unit_cost_paise

    shipping_per_unit = round_half_up_paise(Fraction(quote.shipping_paise.value, quantity))
    return quote.unit_cost_paise + shipping_per_unit
