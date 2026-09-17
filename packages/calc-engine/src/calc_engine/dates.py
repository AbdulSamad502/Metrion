"""resolve_document_date() — deterministic-engine.md §6 (confirmed decision: invoice_date -> dispatch_date -> order_date).

Reasoning (confirmed by product owner): for seller business-period reporting, a cancelled
pre-invoice order should remain attributable to the period the order occurred in, not
disappear from reporting.
"""

from __future__ import annotations

from datetime import date


def resolve_document_date(
    invoice_date: date | None,
    dispatch_date: date | None,
    order_date: date | None,
) -> date:
    """invoice_date -> dispatch_date -> order_date. Raises if all three are None.

    A sales_line must have at least one date; a line with none is a canonical-data defect
    upstream of this engine, not a case this function silently papers over.
    """
    if invoice_date is not None:
        return invoice_date
    if dispatch_date is not None:
        return dispatch_date
    if order_date is not None:
        return order_date
    raise ValueError(
        "resolve_document_date: invoice_date, dispatch_date, and order_date are all None — "
        "a sales_line must carry at least one date"
    )
