"""The per-SKU basis data for a data-driven multi-SKU assignment (NET_REVENUE, UNITS, ORDERS; engine section 5.18.3 with 5.10.1).

Built only when the ledger rows in the window carry such an assignment, from the same assembled sales lines the period P&L reads. Everything numeric comes from the engine
(`net_realized_revenue`; the units and order sets are read straight off the assembled lines): this module groups lines by SKU and passes each SKU's figures on. A figure the data
cannot give is left out (`None`, "not available", never zero): a SKU with no sales line in the window, a line whose cancellation, return or RTO status is unknown, an order
without an id, or any line that could not be assembled (the SKU it belongs to is unknown, so no SKU's data can be trusted) all leave the affected figures unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from calc_engine.formulas.expense_assignment import DATA_BASES, basis_target
from calc_engine.formulas.allocation_outcome import AllocationTarget
from calc_engine.formulas.ledger_feed import LedgerEvent
from calc_engine.formulas.net_realized_revenue import net_realized_revenue
from calc_engine.repositories import canonical_repo
from calc_engine.types import CanonicalLine, RecognitionState, Unavailable

from backend.services import cfo_actions


def needed_skus(events: Sequence[LedgerEvent]) -> set[str]:
    """The SKUs named by data-driven assignments among the records that can count (not voided, not draft)."""
    out: set[str] = set()
    for e in events:
        if e.assignment is not None and e.assignment.basis in DATA_BASES and e.review_status not in ("voided", "draft"):
            out.update(s for s, _ in e.assignment.shares)
    return out


def basis_data(tenant_id: UUID, *, period_start: date, period_end: date, events: Sequence[LedgerEvent], as_of: date | None = None) -> dict[str, AllocationTarget] | None:
    """`None` when no record needs it (nothing is read); otherwise one target per needed SKU that has data (a SKU missing from the result has none: every figure unavailable)."""
    skus = needed_skus(events)
    if not skus:
        return None
    assembled = cfo_actions.assemble_canonical_lines_for_period(tenant_id, period_start=period_start, period_end=period_end)
    if assembled.blocked:
        return {}
    rows = canonical_repo.sales_lines_in_period(tenant_id, period_start=period_start, period_end=period_end)
    order_ref = {str(r["sales_line_id"]): (r.get("order_ref") or "").strip() for r in rows}
    resolver = cfo_actions._bearer_resolver_for(tenant_id, as_of or period_end)  # noqa: SLF001 - the same resolver the period P&L uses
    by_sku: dict[str, list[CanonicalLine]] = {}
    for line in assembled.lines:
        sku = assembled.sku_by_line.get(str(line.sales_line_id))
        if sku in skus:
            by_sku.setdefault(sku, []).append(line)
    out: dict[str, AllocationTarget] = {}
    for sku, lines in by_sku.items():
        known = all(l.cancellation_state is not None for l in lines)
        units_known = known and all(l.return_status is not None and l.rto_status is not None for l in lines)
        revenue = net_realized_revenue(lines, resolver, RecognitionState.RECOGNISED)
        kept = [l for l in lines if l.cancellation_state != "CANCELLED"]
        out[sku] = basis_target(
            sku,
            net_revenue=revenue.value if not isinstance(revenue, Unavailable) else revenue,
            units_sold=sum(l.quantity for l in kept) if known else None,
            units_returned=sum(l.returned_qty + l.rto_qty for l in kept) if units_known else None,
            order_ids=frozenset(order_ref[str(l.sales_line_id)] for l in kept) if known and all(order_ref.get(str(l.sales_line_id)) for l in kept) else None,
        )
    return out
