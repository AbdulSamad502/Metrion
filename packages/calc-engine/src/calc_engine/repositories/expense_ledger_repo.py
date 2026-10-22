"""expense_ledger repository — expense-tracker.md §5.1; migration `20261016_0013_expense_ledger.py`.

Append-only: this module only INSERTs and SELECTs (UPDATE and DELETE are revoked from the application role). It does no calculation and no
interpretation of amounts beyond storing and reading them; every total on a dashboard comes from the engine feed (`formulas/ledger_feed.py`).

State is read, never stored: a record's current review state and payment status are the LATEST `expense_status_event` of each kind. A correction is a new
record that points at the one it corrects (which is voided by a status event in the same transaction); a refund is a new negative record that points
at its original. An `idempotency_key` makes a retry return the original record instead of creating a second one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from calc_engine.formulas.ledger_feed import LedgerEvent
from calc_engine.repositories.tenant_context import tenant_scope
from calc_engine.types import Paise


@dataclass(frozen=True, slots=True)
class NewRecord:
    effective_date: date
    category: str
    cost_class: str
    amount_paise: int  # signed: cost positive, refund / credit note negative (Q21)
    treatment: str = "incremental"
    vendor: str | None = None
    description: str | None = None
    channel_scope: str | None = None
    sku: str | None = None
    origin: str = "MANUAL"
    source_validated: bool = False
    identifier: str | None = None
    source_reference: str | None = "manual"
    recurring: bool = False
    corrects_expense_id: UUID | None = None
    refund_of_expense_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class InsertResult:
    expense_id: UUID
    replayed: bool


_INSERT_EVENT = text(
    """
    INSERT INTO expense_event (id, tenant_id, effective_date, vendor, description, category, cost_class, treatment, amount_paise, channel_scope, sku,
                               origin, source_validated, identifier, source_reference, corrects_expense_id, refund_of_expense_id, recurring,
                               idempotency_key, created_by)
    VALUES (:id, :tenant, :day, :vendor, :description, :category, :cost_class, :treatment, :amount, :channel, :sku,
            :origin, :validated, :identifier, :source, :corrects, :refund, :recurring, :idem, :user)
    """
)
_INSERT_STATUS = text(
    """
    INSERT INTO expense_status_event (tenant_id, expense_id, kind, review_state, payment_status, paid_amount_paise, reason, idempotency_key, created_by)
    VALUES (:tenant, :expense, :kind, :review, :payment, :paid, :reason, :idem, :user)
    """
)
_BY_EVENT_KEY = text("SELECT id FROM expense_event WHERE tenant_id = :tenant AND idempotency_key = :key")
_BY_STATUS_KEY = text("SELECT 1 FROM expense_status_event WHERE tenant_id = :tenant AND idempotency_key = :key")
_EXISTS = text("SELECT 1 FROM expense_event WHERE tenant_id = :tenant AND id = :id")

_CURRENT = """
SELECT e.id, e.effective_date, e.vendor, e.description, e.category, e.cost_class, e.treatment, e.amount_paise, e.channel_scope, e.sku, e.origin,
       e.source_validated, e.identifier, e.source_reference, e.corrects_expense_id, e.refund_of_expense_id, e.recurring, e.created_by, e.created_at,
       r.review_state, r.reason AS review_reason, r.seq AS review_seq, p.payment_status, p.paid_amount_paise
  FROM expense_event e
  JOIN LATERAL (SELECT review_state, reason, seq FROM expense_status_event s
                 WHERE s.tenant_id = e.tenant_id AND s.expense_id = e.id AND s.kind = 'REVIEW' ORDER BY s.seq DESC LIMIT 1) r ON true
  LEFT JOIN LATERAL (SELECT payment_status, paid_amount_paise FROM expense_status_event s
                      WHERE s.tenant_id = e.tenant_id AND s.expense_id = e.id AND s.kind = 'PAYMENT' ORDER BY s.seq DESC LIMIT 1) p ON true
 WHERE e.tenant_id = :tenant
"""


def _event_params(tenant: UUID, expense_id: UUID, rec: NewRecord, created_by: UUID, key: str | None) -> dict[str, Any]:
    return {
        "id": str(expense_id), "tenant": str(tenant), "day": rec.effective_date, "vendor": rec.vendor, "description": rec.description,
        "category": rec.category, "cost_class": rec.cost_class, "treatment": rec.treatment, "amount": rec.amount_paise, "channel": rec.channel_scope,
        "sku": rec.sku, "origin": rec.origin, "validated": rec.source_validated, "identifier": rec.identifier, "source": rec.source_reference,
        "corrects": str(rec.corrects_expense_id) if rec.corrects_expense_id else None,
        "refund": str(rec.refund_of_expense_id) if rec.refund_of_expense_id else None,
        "recurring": rec.recurring, "idem": key, "user": str(created_by),
    }


def _status_params(tenant: UUID, expense_id: UUID, created_by: UUID, **kw: Any) -> dict[str, Any]:
    base = {"tenant": str(tenant), "expense": str(expense_id), "kind": None, "review": None, "payment": None, "paid": None, "reason": None, "idem": None,
            "user": str(created_by)}
    base.update(kw)
    return base


def insert_record(
    tenant_id: UUID,
    record: NewRecord,
    *,
    review_state: str,
    created_by: UUID,
    payment_status: str = "unknown",
    paid_amount_paise: int | None = None,
    idempotency_key: str | None = None,
    void_original: tuple[UUID, str] | None = None,
) -> InsertResult:
    """One record with its two initial status events, in one transaction. `void_original=(id, reason)` also voids the record this one corrects."""
    with tenant_scope(tenant_id) as conn:
        if idempotency_key is not None:
            hit = conn.execute(_BY_EVENT_KEY, {"tenant": str(tenant_id), "key": idempotency_key}).first()
            if hit is not None:
                return InsertResult(UUID(str(hit[0])), True)
        expense_id = uuid4()
        conn.execute(_INSERT_EVENT, _event_params(tenant_id, expense_id, record, created_by, idempotency_key))
        conn.execute(_INSERT_STATUS, _status_params(tenant_id, expense_id, created_by, kind="REVIEW", review=review_state))
        conn.execute(_INSERT_STATUS, _status_params(tenant_id, expense_id, created_by, kind="PAYMENT", payment=payment_status, paid=paid_amount_paise))
        if void_original is not None:
            original_id, reason = void_original
            conn.execute(_INSERT_STATUS, _status_params(tenant_id, original_id, created_by, kind="REVIEW", review="voided", reason=f"{reason}: {expense_id}"))
    return InsertResult(expense_id, False)


def _append(tenant_id: UUID, expense_id: UUID, created_by: UUID, key: str | None, **kw: Any) -> bool:
    """Returns True when the event was a replay of an earlier one with the same key (nothing is written)."""
    with tenant_scope(tenant_id) as conn:
        if conn.execute(_EXISTS, {"tenant": str(tenant_id), "id": str(expense_id)}).first() is None:
            raise LookupError(f"no ledger record {expense_id} for this tenant")
        if key is not None and conn.execute(_BY_STATUS_KEY, {"tenant": str(tenant_id), "key": key}).first() is not None:
            return True
        conn.execute(_INSERT_STATUS, _status_params(tenant_id, expense_id, created_by, idem=key, **kw))
    return False


def append_review(tenant_id: UUID, expense_id: UUID, *, review_state: str, reason: str | None, created_by: UUID, idempotency_key: str | None = None) -> bool:
    return _append(tenant_id, expense_id, created_by, idempotency_key, kind="REVIEW", review=review_state, reason=reason)


def append_payment(
    tenant_id: UUID, expense_id: UUID, *, payment_status: str, paid_amount_paise: int | None, created_by: UUID, reason: str | None = None,
    idempotency_key: str | None = None,
) -> bool:
    return _append(tenant_id, expense_id, created_by, idempotency_key, kind="PAYMENT", payment=payment_status, paid=paid_amount_paise, reason=reason)


def get_record(tenant_id: UUID, expense_id: UUID) -> dict[str, Any] | None:
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(text(_CURRENT + " AND e.id = :id"), {"tenant": str(tenant_id), "id": str(expense_id)}).first()
        if row is None:
            return None
        out = dict(row._mapping)
        history = conn.execute(
            text("SELECT seq, kind, review_state, payment_status, paid_amount_paise, reason, created_by, created_at FROM expense_status_event "
                 "WHERE tenant_id = :tenant AND expense_id = :id ORDER BY seq"),
            {"tenant": str(tenant_id), "id": str(expense_id)},
        ).fetchall()
    out["history"] = [dict(h._mapping) for h in history]
    return out


def list_records(
    tenant_id: UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    cost_class: str | None = None,
    review_state: str | None = None,
    payment_status: str | None = None,
    channel_scope: str | None = None,
    include_voided: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Newest first. Voided records are hidden unless asked for. Returns `(rows, total_matching)` where the count is a row count, not money."""
    where = ""
    params: dict[str, Any] = {"tenant": str(tenant_id)}
    for column, name, value in (
        ("e.effective_date >=", "date_from", date_from), ("e.effective_date <=", "date_to", date_to), ("e.category =", "category", category),
        ("e.cost_class =", "cost_class", cost_class), ("r.review_state =", "review_state", review_state), ("p.payment_status =", "payment_status", payment_status),
        ("e.channel_scope =", "channel_scope", channel_scope),
    ):
        if value is not None:
            where += f" AND {column} :{name}"
            params[name] = value
    if not include_voided and review_state != "voided":
        where += " AND r.review_state <> 'voided'"
    with tenant_scope(tenant_id) as conn:
        total = conn.execute(text("SELECT count(*) FROM (" + _CURRENT + where + ") q"), params).scalar_one()
        rows = conn.execute(
            text(_CURRENT + where + " ORDER BY e.effective_date DESC, e.created_at DESC, e.id LIMIT :limit OFFSET :offset"),
            {**params, "limit": limit, "offset": offset},
        ).fetchall()
    return [dict(r._mapping) for r in rows], int(total)


def feed_events(tenant_id: UUID, *, period_start: date, period_end: date) -> list[LedgerEvent]:
    """The records dated in the window as `LedgerEvent`s for the engine feed: one per record, `seq` = its latest review event, `review_status` = its current
    review state. Selection and every sum stay in `formulas/ledger_feed.py`; nothing is added up here."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(_CURRENT + " AND e.effective_date >= :a AND e.effective_date <= :b ORDER BY e.id"),
            {"tenant": str(tenant_id), "a": period_start, "b": period_end},
        ).fetchall()
    return [
        LedgerEvent(
            expense_id=str(r.id), seq=int(r.review_seq), effective_date=r.effective_date, category=r.category, cost_class=r.cost_class, treatment=r.treatment,
            review_status=r.review_state, amount=Paise(int(r.amount_paise)), channel_scope=r.channel_scope, origin=r.origin,
            source_validated=bool(r.source_validated), identifier=r.identifier, sku_tag=r.sku if r.origin == "MANUAL" else None,
            linked_expense_id=str(r.corrects_expense_id or r.refund_of_expense_id) if (r.corrects_expense_id or r.refund_of_expense_id) else None,
            recurring=bool(r.recurring),
        )
        for r in rows
    ]


def known_skus(tenant_id: UUID) -> set[str]:
    """The seller's catalog for the Q29 SKU-level rule: the distinct SKUs on the tenant's ingested sales lines (the only catalog the data model has)."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text("SELECT DISTINCT sku FROM sales_line WHERE tenant_id = :tenant AND sku IS NOT NULL"), {"tenant": str(tenant_id)}).fetchall()
    return {str(r[0]) for r in rows}


def import_candidates(tenant_id: UUID, *, date_from: date | None, date_to: date | None, source_references: list[str]) -> list[dict[str, Any]]:
    """The non-voided records an import could duplicate: those dated inside the file's date range, plus any whose `source_reference` is one the file carries
    (an id can be re-used at another date). Read-only; the matching rules live in the backend import service."""
    refs = list(source_references)
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            text(
                _CURRENT + " AND r.review_state <> 'voided' AND ((CAST(:a AS date) IS NOT NULL AND e.effective_date >= :a AND e.effective_date <= :b) "
                "OR (cardinality(CAST(:refs AS text[])) > 0 AND e.source_reference = ANY(CAST(:refs AS text[]))))"
            ),
            {"tenant": str(tenant_id), "a": date_from, "b": date_to, "refs": refs},
        ).fetchall()
    return [
        {"id": str(r.id), "effective_date": r.effective_date, "vendor": r.vendor, "description": r.description, "amount_paise": int(r.amount_paise),
         "source_reference": r.source_reference}
        for r in rows
    ]
