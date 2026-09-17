"""CanonicalDataBuilder — fluent, in-memory CanonicalLine/ComponentRow construction for tests, no Postgres."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise


class CanonicalDataBuilder:
    """Defaults to a fully-resolved, nothing-happened line (like a clean Meesho delivery) so a
    bare `.build()` is usable directly for T1-style tests. Every status defaults to a resolved
    "DELIVERED" value, not None — call `.unresolved_*()` explicitly to model an
    Amazon/Flipkart-style unsupported marketplace (C1/C2)."""

    def __init__(self) -> None:
        self._marketplace = "MEESHO"
        self._quantity = 1
        self._gross = Paise(0)
        self._components: list[ComponentRow] = []
        self._invoice_date: date | None = date(2026, 8, 15)
        self._dispatch_date: date | None = None
        self._order_date: date | None = None
        self._confidence = Confidence.PROVISIONAL
        self._cancellation_state: str | None = "DELIVERED"
        self._return_status: str | None = "DELIVERED"
        self._returned_qty = 0
        self._refunded_amount: Paise | None = None
        self._rto_status: str | None = "DELIVERED"
        self._rto_qty = 0
        self._rto_outcome: str | None = None

    def marketplace(self, marketplace: str) -> "CanonicalDataBuilder":
        self._marketplace = marketplace
        return self

    def quantity(self, quantity: int) -> "CanonicalDataBuilder":
        self._quantity = quantity
        return self

    def gross(self, amount_paise: int) -> "CanonicalDataBuilder":
        self._gross = Paise(amount_paise)
        return self

    def document_date(self, d: date) -> "CanonicalDataBuilder":
        self._invoice_date = d
        return self

    def dispatched_on(self, d: date) -> "CanonicalDataBuilder":
        self._dispatch_date = d
        return self

    def confidence(self, c: Confidence) -> "CanonicalDataBuilder":
        self._confidence = c
        return self

    def discount(self, code: str, amount_paise: int, *, side: str = "INVOICE") -> "CanonicalDataBuilder":
        self._components.append(
            ComponentRow(id=uuid4(), component_kind="DISCOUNT", component_code=code, source_side=side, amount=Paise(amount_paise))
        )
        return self

    def fee(self, code: str, amount_paise: int, *, side: str = "INVOICE", tax_amount_paise: int | None = None) -> "CanonicalDataBuilder":
        self._components.append(
            ComponentRow(
                id=uuid4(),
                component_kind="FEE",
                component_code=code,
                source_side=side,
                amount=Paise(amount_paise),
                tax_amount=Paise(tax_amount_paise) if tax_amount_paise is not None else None,
            )
        )
        return self

    def logistics(self, code: str, amount_paise: int, *, side: str = "INVOICE") -> "CanonicalDataBuilder":
        self._components.append(
            ComponentRow(id=uuid4(), component_kind="CHARGE", component_code=code, source_side=side, amount=Paise(amount_paise))
        )
        return self

    def cancelled(self) -> "CanonicalDataBuilder":
        self._cancellation_state = "CANCELLED"
        return self

    def unresolved_cancellation(self) -> "CanonicalDataBuilder":
        self._cancellation_state = None
        return self

    def returned(self, qty: int, refunded_amount_paise: int | None = None) -> "CanonicalDataBuilder":
        self._return_status = "RETURNED"
        self._returned_qty = qty
        if refunded_amount_paise is not None:
            self._refunded_amount = Paise(refunded_amount_paise)
        return self

    def unresolved_return(self) -> "CanonicalDataBuilder":
        self._return_status = None
        return self

    def rto(self, qty: int, outcome: str | None = None) -> "CanonicalDataBuilder":
        self._rto_status = "RTO"
        self._rto_qty = qty
        self._rto_outcome = outcome
        return self

    def unresolved_rto(self) -> "CanonicalDataBuilder":
        self._rto_status = None
        return self

    def build(self) -> CanonicalLine:
        return CanonicalLine(
            sales_line_id=uuid4(),
            marketplace=self._marketplace,
            document_type="INVOICE",
            quantity=self._quantity,
            invoice_date=self._invoice_date,
            dispatch_date=self._dispatch_date,
            order_date=self._order_date,
            gross_item_amount=self._gross,
            components=tuple(self._components),
            confidence=self._confidence,
            cancellation_state=self._cancellation_state,
            return_status=self._return_status,
            returned_qty=self._returned_qty,
            refunded_amount=self._refunded_amount,
            rto_status=self._rto_status,
            rto_qty=self._rto_qty,
            rto_outcome=self._rto_outcome,
        )
