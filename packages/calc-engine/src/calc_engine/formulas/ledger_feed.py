"""The expense-ledger feed — deterministic-engine.md §5.17 (Rounds 6–8), Q21, Q24, Q29; expense-tracker.md F1/F6/F7.

A **pure function over fixture rows**: no database, no clock, no tenant lookup. Ledger tables and migrations are Step 3; this module defines what
the engine does with ledger rows once it has them. All selection and aggregation of ledger amounts lives here (inside `packages/calc-engine`);
nothing outside the engine selects, sums or signs them.

Rules implemented
- Latest event per `expense_id` wins (the log is append-only); `voided` removes the record. Review states: `draft`, `pending_review`,
  `confirmed`, `voided` — only `confirmed` rows are counted; `pending_review` rows are queued and shown, never summed into a pool.
- Treatments: `incremental` rows count; `already_in_settlement` and `informational` rows are excluded from every sum and reported separately.
- Signed amounts: a cost is positive, a refund/credit note negative. A pool is the signed sum (identity on paise); a negative pool is a net credit,
  never floored. A refund belongs to the period of its OWN date (it is just a row with its own `effective_date`).
- A cost class with no counted row is `None` ("not entered"), never zero; an explicit zero row is an entered zero.
- Channel scope: channel-specific rows enter only their own channel's scope; business-wide rows reach a channel only through an allocation basis
  and are reported here as `business_wide_out_of_scope`.
- SKU-level rule for ADVERTISING and STORAGE (Q29): SKU-level only for a validated import with an explicit identifier that maps to a catalog SKU;
  everything else is business-level; a manual entry is SKU-level only when the seller tagged a SKU, and stays flagged manual; an unmapped
  identifier is business-level and goes to the review queue.
- `ledger_watermark` identifies exactly which events the result was built from (stamped into `input_refs` by the metric minting).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from calc_engine.types import ZERO, Paise

KNOWN_COST_CLASSES: tuple[str, ...] = ("ADVERTISING", "STORAGE", "OVERHEAD", "DIRECT")
_SKU_LEVEL_CLASSES = frozenset({"ADVERTISING", "STORAGE"})
_GAP_NAME = {"ADVERTISING": "advertising", "STORAGE": "storage", "OVERHEAD": "overhead", "DIRECT": "direct costs"}

TREATMENTS = frozenset({"incremental", "already_in_settlement", "informational"})
REVIEW_STATES = frozenset({"draft", "pending_review", "confirmed", "voided"})


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """One event of the append-only ledger as the feed needs it (a fixture row until Step 3 defines the tables)."""

    expense_id: str
    seq: int
    effective_date: date
    category: str
    cost_class: str
    treatment: str
    review_status: str
    amount: Paise  # signed: cost positive, refund / credit note negative
    channel_scope: str | None = None  # None = business-wide
    origin: str = "MANUAL"  # MANUAL | IMPORT
    source_validated: bool = False
    identifier: str | None = None  # explicit ASIN or SKU identifier carried by the source data
    sku_tag: str | None = None  # a SKU the seller tagged on the form
    linked_expense_id: str | None = None  # a refund / credit note links to its original
    recurring: bool = False  # Step 4 defines materialisation; the feed only totals the flag


@dataclass(frozen=True, slots=True)
class PoolTotals:
    cost_class: str
    entered: bool
    total: Paise | None  # None = not entered (never zero)
    sku_level: Mapping[str, Paise] = field(default_factory=dict)
    business_level: Paise = ZERO
    manual_sku_level: Paise = ZERO  # the part of sku_level that is a seller tag (flagged manual)


@dataclass(frozen=True, slots=True)
class ReviewItem:
    expense_id: str
    reason: str  # PENDING_REVIEW | UNKNOWN_COST_CLASS | UNKNOWN_TREATMENT | UNMAPPED_IDENTIFIER
    amount: Paise


@dataclass(frozen=True, slots=True)
class LedgerFeedResult:
    pools: Mapping[str, PoolTotals]
    gaps: tuple[str, ...]
    review_queue: tuple[ReviewItem, ...]
    review_queue_amount: Paise  # amounts awaiting review that are NOT counted in any pool
    including_unresolved: Paise  # expense_total + review_queue_amount
    expense_total: Paise  # Σ counted rows
    excluded_by_treatment: Mapping[str, Paise]
    business_wide_out_of_scope: Paise
    by_category: Mapping[str, Paise]
    by_cost_class: Mapping[str, Paise]
    recurring_total: Paise
    watermark: str


@dataclass(frozen=True, slots=True)
class LedgerDisplay:
    kind: str  # COST | NET_CREDIT
    magnitude: Paise  # non-negative


def ledger_to_engine_pool(amounts: Iterable[Paise]) -> Paise:
    """Ledger → engine: the pool is the signed sum (a refund reduces it). Identity on the paise value; no float."""
    total = ZERO
    for a in amounts:
        total = total + a
    return total


def engine_to_ledger_display(pool: Paise) -> LedgerDisplay:
    """Engine → ledger/display: a non-negative pool is a cost, a negative pool a net credit (never floored at zero)."""
    return LedgerDisplay("COST", pool) if pool.value >= 0 else LedgerDisplay("NET_CREDIT", Paise(-pool.value))


def ledger_display_to_signed(display: LedgerDisplay) -> Paise:
    return display.magnitude if display.kind == "COST" else Paise(-display.magnitude.value)


def ledger_watermark(events: Iterable[LedgerEvent]) -> str:
    """Order-independent identity of the event set the feed read: highest sequence plus a hash of every `expense_id:seq`."""
    events = list(events)
    pairs = sorted(f"{e.expense_id}:{e.seq}" for e in events)
    top = max((e.seq for e in events), default=0)
    return f"ledger:{top}:{hashlib.sha256(chr(10).join(pairs).encode('utf-8')).hexdigest()[:16]}"


def sku_level_for(event: LedgerEvent, catalog: Mapping[str, str]) -> tuple[str | None, bool, str | None]:
    """Q29. Returns `(sku, is_manual_tag, review_reason)`; `sku is None` means business-level."""
    if event.origin == "IMPORT":
        if event.source_validated and event.identifier:
            sku = catalog.get(event.identifier)
            return (sku, False, None) if sku is not None else (None, False, "UNMAPPED_IDENTIFIER")
        return None, False, None  # unvalidated import, or campaign-level spend without an ASIN/SKU breakdown
    # manual: never SKU-level by default; a seller tag makes it SKU-level, still flagged manual
    if event.sku_tag:
        sku = catalog.get(event.sku_tag)
        return (sku, True, None) if sku is not None else (None, False, "UNMAPPED_IDENTIFIER")
    return None, False, None


def ledger_feed(
    events: Sequence[LedgerEvent],
    *,
    period_start: date,
    period_end: date,
    channel_scope: str | None,
    catalog: Mapping[str, str],
) -> LedgerFeedResult:
    events = list(events)
    latest: dict[str, LedgerEvent] = {}
    for e in events:
        cur = latest.get(e.expense_id)
        if cur is None or e.seq > cur.seq:
            latest[e.expense_id] = e

    cls_total: dict[str, Paise] = {}
    cls_entered: dict[str, bool] = {c: False for c in KNOWN_COST_CLASSES}
    sku_level: dict[str, dict[str, Paise]] = {c: {} for c in KNOWN_COST_CLASSES}
    business: dict[str, Paise] = {c: ZERO for c in KNOWN_COST_CLASSES}
    manual_sku: dict[str, Paise] = {c: ZERO for c in KNOWN_COST_CLASSES}
    by_category: dict[str, Paise] = {}
    by_class: dict[str, Paise] = {}
    excluded: dict[str, Paise] = {}
    queue: list[ReviewItem] = []
    review_amount = ZERO
    out_of_scope = ZERO
    recurring = ZERO
    expense_total = ZERO

    for eid in sorted(latest):
        e = latest[eid]
        if e.review_status in ("voided", "draft"):
            continue
        if not (period_start <= e.effective_date <= period_end):
            continue
        if channel_scope is not None and e.channel_scope != channel_scope:
            if e.channel_scope is None and e.review_status == "confirmed" and e.treatment == "incremental":
                out_of_scope = out_of_scope + e.amount
            continue
        if e.treatment not in TREATMENTS:
            queue.append(ReviewItem(eid, "UNKNOWN_TREATMENT", e.amount))
            review_amount = review_amount + e.amount
            continue
        if e.review_status == "pending_review":
            if e.treatment == "incremental":
                queue.append(ReviewItem(eid, "PENDING_REVIEW", e.amount))
                review_amount = review_amount + e.amount
            continue
        # confirmed from here on
        if e.treatment != "incremental":
            excluded[e.treatment] = excluded.get(e.treatment, ZERO) + e.amount
            continue
        if e.cost_class not in KNOWN_COST_CLASSES:
            queue.append(ReviewItem(eid, "UNKNOWN_COST_CLASS", e.amount))
            review_amount = review_amount + e.amount
            continue

        cls = e.cost_class
        cls_entered[cls] = True
        cls_total[cls] = cls_total.get(cls, ZERO) + e.amount
        expense_total = expense_total + e.amount
        by_category[e.category] = by_category.get(e.category, ZERO) + e.amount
        by_class[cls] = by_class.get(cls, ZERO) + e.amount
        if e.recurring:
            recurring = recurring + e.amount

        sku = None
        if cls in _SKU_LEVEL_CLASSES:
            sku, manual, reason = sku_level_for(e, catalog)
            if reason is not None:
                queue.append(ReviewItem(eid, reason, e.amount))  # counted as business-level; flagged for resolution only
            if sku is not None:
                sku_level[cls][sku] = sku_level[cls].get(sku, ZERO) + e.amount
                if manual:
                    manual_sku[cls] = manual_sku[cls] + e.amount
        if sku is None:
            business[cls] = business[cls] + e.amount

    pools = {
        cls: PoolTotals(
            cost_class=cls, entered=cls_entered[cls], total=cls_total.get(cls) if cls_entered[cls] else None,
            sku_level=dict(sorted(sku_level[cls].items())), business_level=business[cls], manual_sku_level=manual_sku[cls],
        )
        for cls in KNOWN_COST_CLASSES
    }
    gaps = tuple(f"{_GAP_NAME[c]}: not entered" for c in KNOWN_COST_CLASSES if not cls_entered[c])
    return LedgerFeedResult(
        pools=pools, gaps=gaps, review_queue=tuple(sorted(queue, key=lambda i: (i.expense_id, i.reason))),
        review_queue_amount=review_amount, including_unresolved=expense_total + review_amount, expense_total=expense_total,
        excluded_by_treatment=dict(sorted(excluded.items())), business_wide_out_of_scope=out_of_scope,
        by_category=dict(sorted(by_category.items())), by_cost_class=dict(sorted(by_class.items())), recurring_total=recurring,
        watermark=ledger_watermark(events),
    )
