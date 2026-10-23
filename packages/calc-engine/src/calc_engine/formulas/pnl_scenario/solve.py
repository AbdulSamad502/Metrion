"""Break-even price and "find my price" for a hypothetical scenario.

Profit is NOT assumed to be one straight line in price: fee price-bands make it piecewise. The solver splits the price axis at every band edge,
solves each segment exactly (profit is linear inside a segment), then checks the answer against the same engine used for display. Order
volume is assumed NOT to change with price. Verified against an exhaustive paisa scan in the tests.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction

from calc_engine.formulas.pnl_scenario.calculate import make_view
from calc_engine.formulas.pnl_scenario.model import ZERO, Prepared, evaluate, from_bps, prepare, price_breakpoints
from calc_engine.formulas.pnl_scenario.types import (
    Entry,
    PriceRange,
    ScenarioInputs,
    SolveResult,
    SolveTarget,
)
from calc_engine.types import Paise

PLACEHOLDER_PRICE = 10000


def _build_g(p: Prepared, target: SolveTarget, basis: str) -> Callable[[int], Fraction] | None:
    m = from_bps(target.bps) if target.kind == "margin" else ZERO
    opex = ZERO
    if basis == "operating":
        if p.opex is None or not p.opex_answered:
            return None
        opex = p.opex

    def g(price: int) -> Fraction:
        t = evaluate(p, price)
        return t.contribution - opex - m * t.revenue

    return g


@dataclass
class _Span:
    lo: int
    hi: int | None  # None = no upper limit


def _merge_ranges(spans: list[_Span]) -> list[_Span]:
    out: list[_Span] = []
    for r in spans:
        last = out[-1] if out else None
        if last is not None and last.hi is not None and last.hi + 1 >= r.lo:
            last.hi = None if r.hi is None else max(last.hi, r.hi)
        else:
            out.append(_Span(r.lo, r.hi))
    return out


def solve_price(inputs: ScenarioInputs, target: SolveTarget, basis: str = "contribution") -> SolveResult:
    probe = inputs if inputs.selling_price.state == "set" else replace(inputs, selling_price=Entry("set", PLACEHOLDER_PRICE))
    prep = prepare(probe)
    p = prep.prepared
    if p is None:
        return SolveResult("unavailable", reason="incomplete")
    if p.k <= 0:
        return SolveResult("unavailable", reason="no_kept_orders")
    g = _build_g(p, target, basis)
    if g is None:
        return SolveResult("unavailable", reason="operating_unavailable")
    excludes_missing = len(prep.missing_costs) > 0

    # Segment edges: P <= edge belongs to the lower segment.
    edges = sorted({math.floor(x) for x in price_breakpoints(p)})
    edges = [e for e in edges if e >= 1]
    segments: list[tuple[int, int | None]] = []
    lo = 1
    for e in edges:
        if e >= lo:
            segments.append((lo, e))
        lo = max(lo, e + 1)
    segments.append((lo, None))

    found: list[_Span] = []
    for seg_lo, seg_hi in segments:
        g0 = g(seg_lo)
        if seg_hi is not None and seg_hi == seg_lo:
            if g0 >= 0:
                found.append(_Span(seg_lo, seg_lo))
            continue
        a = g(seg_lo + 1) - g0  # slope per paisa inside the segment
        b = g0 - a * seg_lo  # g(P) = a*P + b
        if a > 0:
            frm = math.ceil(-b / a)
            start = max(frm, seg_lo)
            if seg_hi is None or start <= seg_hi:
                found.append(_Span(start, seg_hi))
        elif a == 0:
            if b >= 0:
                found.append(_Span(seg_lo, seg_hi))
        else:
            limit = math.floor(b / -a)  # largest P with g >= 0
            end = limit if seg_hi is None or limit < seg_hi else seg_hi
            if end >= seg_lo:
                found.append(_Span(seg_lo, end))
    ranges = _merge_ranges(found)
    if not ranges:
        return SolveResult("unreachable", reason="No selling price reaches this target with the costs and fees entered.")

    # Break-even is also checked on the rounded figures the seller sees, so the screen never shows a profit of minus one paisa at the
    # "break-even" price.
    first = ranges[0]
    if target.kind == "breakeven" and basis == "contribution":
        price = first.lo
        for _ in range(20):
            view = make_view(evaluate(p, price), p.k, None)
            if view.contribution.value >= 0:
                break
            price += 1
        if first.hi is None or price <= first.hi:
            first.lo = price

    if first.lo <= 1 and first.hi is None:
        return SolveResult("always", excludes_missing_costs=excludes_missing)
    return SolveResult(
        "price",
        price=Paise(first.lo),
        ranges=tuple(PriceRange(r.lo, r.hi) for r in ranges),
        excludes_missing_costs=excludes_missing,
    )
