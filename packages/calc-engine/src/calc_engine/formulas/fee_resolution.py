"""fee_reference resolution — deterministic-engine.md §5.14. Mirrors formulas/leak.py's
`resolve_tolerance_or_unavailable` pattern: `config_repo.resolve_fee_reference()` returns
`None` on a miss, and this module turns that into `Unavailable`, never a guessed rate.

Approved decision (range-vs-point): a `fee_reference` row is never collapsed to a midpoint.
If `rate_pct` is populated, it is used as-is; if only `rate_low_pct`/`rate_high_pct` are
populated, they are carried through as-is with `rate_pct=None`. No field here is ever derived
from another — each of the three rate fields reflects exactly what the row stored, or `None`
if the row didn't store it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from calc_engine.types import Unavailable


@dataclass(frozen=True, slots=True)
class FeeReference:
    """A resolved fee_reference row (§5.14). `rate_pct` is populated for a point rate;
    `rate_low_pct`/`rate_high_pct` are populated for a range. A row may populate either shape
    (never both collapsed into the other) — callers must handle `rate_pct is None` as "this
    is a range, not a missing point," not as an error."""

    rate_pct: Fraction | None
    rate_low_pct: Fraction | None
    rate_high_pct: Fraction | None
    source: str
    confidence: str
    version: int


def _to_fraction(value: object) -> Fraction | None:
    """`numeric(7,4)` columns come back from the DB driver as `Decimal` (or `None`).
    `Fraction(Decimal(...))` is exact — no float ever enters this conversion."""
    if value is None:
        return None
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    raise TypeError(f"fee_reference rate field must be Decimal or None, got {type(value).__name__}: {value!r}")


def resolve_fee_or_unavailable(fee_row: "dict[str, object] | None") -> FeeReference | Unavailable:
    """`fee_row` is whatever `config_repo.resolve_fee_reference()` returned (`None` on a miss).
    A miss is never treated as a zero or default rate — it makes the fee reference
    UNAVAILABLE. A row where all three rate fields (`rate_pct`, `rate_low_pct`,
    `rate_high_pct`) are `None` is malformed, not merely incomplete — a fee_reference row
    asserting no rate at all is not a usable reference, so it raises `ValueError` rather than
    being silently treated as absent (mirroring `parse_supplier_quote_adjustment`'s
    malformed-vs-absent convention)."""
    if fee_row is None:
        return Unavailable(
            reason="no fee_reference row covers this (marketplace, category, fee_type)",
            missing_inputs=("fee_reference",),
        )

    rate_pct = _to_fraction(fee_row.get("rate_pct"))
    rate_low_pct = _to_fraction(fee_row.get("rate_low_pct"))
    rate_high_pct = _to_fraction(fee_row.get("rate_high_pct"))

    if rate_pct is None and rate_low_pct is None and rate_high_pct is None:
        raise ValueError(f"fee_reference row has no rate populated at all (malformed): {fee_row!r}")

    return FeeReference(
        rate_pct=rate_pct,
        rate_low_pct=rate_low_pct,
        rate_high_pct=rate_high_pct,
        source=fee_row["source"],  # type: ignore[arg-type]
        confidence=fee_row["confidence"],  # type: ignore[arg-type]
        version=fee_row["version"],  # type: ignore[arg-type]
    )
