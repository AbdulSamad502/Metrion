"""Expense ledger repository (docs/specs/cfo-expense-ledger.md). Append-only: the application role can only SELECT and INSERT.

Every write bumps `cfo_read_model_version` in the **same transaction** (AC-L7), so a cached planner answer can never outlive a ledger change.
The `*_on(conn)` functions run on an already-open `tenant_scope()` connection so the streaming ingestion can write a whole file atomically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from calc_engine.expense_ledger import Decision, Disposition, LedgerRuleError, NewEntry, decide, entry_identity, validate_new_entry
from calc_engine.formulas.expense_accounting import ExpenseClass, ExpenseHold, ExpenseLine, OverheadCoverage, effective_class
from calc_engine.repositories import read_model_version_repo
from calc_engine.repositories.tenant_context import tenant_scope

_CHUNK = 2000
COMPONENTS = ("ADVERTISING", "PACKAGING", "STORAGE", "LOGISTICS", "OTHER")

_INSERT_ENTRY = text(
    """
    INSERT INTO expense_entry
      (id, tenant_id, source, ingestion_run_id, source_row_number, entry_date, paid_date, amount_paise, gst_amount_paise, gst_treatment, category,
       vendor, description, payment_ref, marketplace, identity, hold, supersedes_id, is_void, created_by)
    VALUES
      (:id, :tenant_id, :source, :ingestion_run_id, :source_row_number, :entry_date, :paid_date, :amount_paise, :gst_amount_paise, :gst_treatment, :category,
       :vendor, :description, :payment_ref, :marketplace, :identity, :hold, :supersedes_id, :is_void, :created_by)
    """
)

_ACTIVE_WHERE = """
    e.tenant_id = :tenant_id AND NOT e.is_void
    AND NOT EXISTS (SELECT 1 FROM expense_entry n WHERE n.tenant_id = e.tenant_id AND n.supersedes_id = e.id)
"""

_ENTRY_COLUMNS = ("e.id, e.source, e.ingestion_run_id, e.source_row_number, e.entry_date, e.paid_date, e.amount_paise, e.gst_amount_paise, e.gst_treatment, "
                  "e.category, e.vendor, e.description, e.payment_ref, e.marketplace, e.identity, e.hold, e.supersedes_id, e.created_by, e.created_at")


@dataclass(frozen=True, slots=True)
class AddResult:
    inserted_ids: tuple[UUID, ...]
    skipped_exact_duplicates: int
    held_possible_duplicates: int
    held_overlap: int
    held_ids: tuple[UUID, ...] = field(default=())


def _params(tenant_id: UUID, e: NewEntry, ident: str, hold: ExpenseHold, created_by: UUID, *, supersedes_id: UUID | None = None, is_void: bool = False,
            entry_id: UUID | None = None) -> dict[str, Any]:
    return {
        "id": str(entry_id or uuid4()), "tenant_id": str(tenant_id), "source": e.source, "ingestion_run_id": e.ingestion_run_id,
        "source_row_number": e.source_row_number, "entry_date": e.entry_date, "paid_date": e.paid_date, "amount_paise": e.amount_paise,
        "gst_amount_paise": e.gst_amount_paise, "gst_treatment": e.gst_treatment, "category": e.category, "vendor": e.vendor, "description": e.description,
        "payment_ref": e.payment_ref, "marketplace": e.marketplace, "identity": ident, "hold": hold.value,
        "supersedes_id": None if supersedes_id is None else str(supersedes_id), "is_void": is_void, "created_by": str(created_by),
    }


def add_entries_on(conn: Connection, tenant_id: UUID, entries: Sequence[NewEntry], created_by: UUID) -> AddResult:
    """Validates, de-duplicates and inserts a batch in the caller's transaction, then bumps the read-model version once."""
    clean = [validate_new_entry(e) for e in entries]
    if not clean:
        return AddResult((), 0, 0, 0)
    known_ids: set[str] = set()
    known_keys: set[tuple[str, int, str | None]] = set()
    lo, hi = min(e.entry_date for e in clean), max(e.entry_date for e in clean)
    idents = [entry_identity(e) for e in clean]
    for i in range(0, len(idents), _CHUNK):
        for (ident,) in conn.execute(text("SELECT identity FROM expense_entry WHERE tenant_id = :t AND NOT is_void AND identity = ANY(:ids)"),
                                     {"t": str(tenant_id), "ids": idents[i:i + _CHUNK]}):
            known_ids.add(ident)
    for d, amt, vendor in conn.execute(text(
            f"SELECT e.entry_date, e.amount_paise, e.vendor FROM expense_entry e WHERE {_ACTIVE_WHERE} AND e.entry_date BETWEEN :lo AND :hi"),
            {"tenant_id": str(tenant_id), "lo": lo, "hi": hi}):
        known_keys.add((d.isoformat(), int(amt), None if vendor is None else vendor.casefold()))

    inserted: list[UUID] = []
    held: list[UUID] = []
    skipped = poss = overlap = 0
    rows: list[dict[str, Any]] = []
    for e in clean:
        dec: Decision = decide(e, known_ids, known_keys)
        if dec.disposition is Disposition.SKIP_EXACT_DUPLICATE:
            skipped += 1
            continue
        new_id = uuid4()
        rows.append(_params(tenant_id, e, dec.identity, dec.hold, created_by, entry_id=new_id))
        inserted.append(new_id)
        known_ids.add(dec.identity)  # a repeat later in the same batch is an exact duplicate of this one
        if dec.hold is ExpenseHold.NONE:
            known_keys.add((e.entry_date.isoformat(), e.amount_paise, None if e.vendor is None else e.vendor.casefold()))
        else:
            held.append(new_id)
            if dec.hold is ExpenseHold.POSSIBLE_DUPLICATE:
                poss += 1
            else:
                overlap += 1
    for i in range(0, len(rows), _CHUNK):
        conn.execute(_INSERT_ENTRY, rows[i:i + _CHUNK])
    if rows:
        read_model_version_repo.bump_on(conn, tenant_id)
    return AddResult(tuple(inserted), skipped, poss, overlap, tuple(held))


def add_entries(tenant_id: UUID, entries: Sequence[NewEntry], created_by: UUID) -> AddResult:
    with tenant_scope(tenant_id) as conn:
        return add_entries_on(conn, tenant_id, entries, created_by)


def _get_entry_on(conn: Connection, tenant_id: UUID, entry_id: UUID) -> Mapping[str, Any]:
    row = conn.execute(text(f"SELECT {_ENTRY_COLUMNS} FROM expense_entry e WHERE {_ACTIVE_WHERE} AND e.id = :id"), {"tenant_id": str(tenant_id), "id": str(entry_id)}).one_or_none()
    if row is None:
        raise LedgerRuleError("that expense does not exist, is already corrected or removed")
    return dict(row._mapping)


def supersede_entry(tenant_id: UUID, entry_id: UUID, replacement: NewEntry, created_by: UUID) -> UUID:
    """A correction: a new row naming the one it replaces. A replacement identical to the original is refused (it would change nothing)."""
    new = validate_new_entry(replacement)
    ident = entry_identity(new)
    with tenant_scope(tenant_id) as conn:
        old = _get_entry_on(conn, tenant_id, entry_id)
        if old["identity"] == ident:
            raise LedgerRuleError("the correction is identical to the existing expense")
        clash = conn.execute(text("SELECT 1 FROM expense_entry WHERE tenant_id = :t AND NOT is_void AND identity = :i"), {"t": str(tenant_id), "i": ident}).first()
        if clash is not None:
            raise LedgerRuleError("an expense identical to the corrected one already exists")
        new_id = uuid4()
        conn.execute(_INSERT_ENTRY, _params(tenant_id, new, ident, ExpenseHold.NONE, created_by, supersedes_id=entry_id, entry_id=new_id))
        read_model_version_repo.bump_on(conn, tenant_id)
        return new_id


def void_entry(tenant_id: UUID, entry_id: UUID, created_by: UUID) -> UUID:
    """A removal: a void row copying the original, naming it in supersedes_id. The original stops being active; nothing is deleted."""
    with tenant_scope(tenant_id) as conn:
        old = _get_entry_on(conn, tenant_id, entry_id)
        e = NewEntry(entry_date=old["entry_date"], amount_paise=int(old["amount_paise"]), category=old["category"], paid_date=old["paid_date"],
                     gst_amount_paise=old["gst_amount_paise"], gst_treatment=old["gst_treatment"], vendor=old["vendor"], description=old["description"],
                     payment_ref=old["payment_ref"], marketplace=old["marketplace"], source="MANUAL")
        void_id = uuid4()
        conn.execute(_INSERT_ENTRY, _params(tenant_id, e, f"void:{void_id}", ExpenseHold.NONE, created_by, supersedes_id=entry_id, is_void=True, entry_id=void_id))
        read_model_version_repo.bump_on(conn, tenant_id)
        return void_id


def release_hold(tenant_id: UUID, entry_id: UUID, created_by: UUID) -> UUID:
    """The seller confirms a held entry is genuine: a superseding row with the hold cleared (the held original stops being active)."""
    with tenant_scope(tenant_id) as conn:
        old = _get_entry_on(conn, tenant_id, entry_id)
        if old["hold"] == ExpenseHold.NONE.value:
            raise LedgerRuleError("that expense is not on hold")
        e = NewEntry(entry_date=old["entry_date"], amount_paise=int(old["amount_paise"]), category=old["category"], paid_date=old["paid_date"],
                     gst_amount_paise=old["gst_amount_paise"], gst_treatment=old["gst_treatment"], vendor=old["vendor"], description=old["description"],
                     payment_ref=old["payment_ref"], marketplace=old["marketplace"], source=old["source"], ingestion_run_id=None, source_row_number=old["source_row_number"])
        new_id = uuid4()
        # the released row keeps the meaning (and so the identity) of the held one; uniqueness is enforced among rows with hold NONE, which the held original is not
        conn.execute(_INSERT_ENTRY, _params(tenant_id, e, entry_identity(e), ExpenseHold.NONE, created_by, supersedes_id=entry_id, entry_id=new_id))
        read_model_version_repo.bump_on(conn, tenant_id)
        return new_id


# --------------------------------------------------------------------------------------------------- classes
def _record_assignment(tenant_id: UUID, *, scope: str, entry_id: UUID | None, category: str | None, klass: ExpenseClass, state: str, by: UUID | None,
                       suggested_by: str | None, reason: str | None, allocated_component: str | None = None) -> UUID:
    if scope == "CATEGORY":
        category = category.strip() if category else category
        if not category:
            raise LedgerRuleError("a category class needs a category")
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        if scope == "ENTRY":
            assert entry_id is not None
            _get_entry_on(conn, tenant_id, entry_id)  # must be an active entry of this tenant
        prev = conn.execute(text(
            "SELECT a.id FROM expense_class_assignment a WHERE a.tenant_id = :t AND a.state = :s AND a.scope = :sc "
            "AND ((:sc = 'ENTRY' AND a.entry_id = :eid) OR (:sc = 'CATEGORY' AND a.category = :cat)) "
            "AND NOT EXISTS (SELECT 1 FROM expense_class_assignment n WHERE n.tenant_id = a.tenant_id AND n.supersedes_id = a.id) ORDER BY a.created_at DESC LIMIT 1"),
            {"t": str(tenant_id), "s": state, "sc": scope, "eid": None if entry_id is None else str(entry_id), "cat": category}).one_or_none()
        conn.execute(text(
            "INSERT INTO expense_class_assignment (id, tenant_id, scope, entry_id, category, class, state, suggested_by, reason, confirmed_by, confirmed_at, supersedes_id, allocated_component) "
            "VALUES (:id, :t, :scope, :eid, :cat, :cls, :state, :sby, :reason, :cby, :cat_at, :sup, :comp)"),
            {"id": str(new_id), "t": str(tenant_id), "scope": scope, "eid": None if entry_id is None else str(entry_id), "cat": category if scope == "CATEGORY" else None,
             "cls": klass.value, "state": state, "sby": suggested_by, "reason": reason, "cby": None if by is None or state != "CONFIRMED" else str(by),
             "cat_at": datetime.now().astimezone() if state == "CONFIRMED" else None, "sup": None if prev is None else str(prev[0]), "comp": allocated_component})
        if state == "CONFIRMED":
            read_model_version_repo.bump_on(conn, tenant_id)  # only a confirmation changes a figure (E3/E4)
    return new_id


def confirm_class(tenant_id: UUID, *, klass: ExpenseClass, confirmed_by: UUID, entry_id: UUID | None = None, category: str | None = None,
                  allocated_component: str | None = None) -> UUID:
    if (entry_id is None) == (category is None):
        raise LedgerRuleError("confirm a class for exactly one entry or one category")
    if klass is ExpenseClass.OTHER_UNCLASSIFIED:
        raise LedgerRuleError("OTHER_UNCLASSIFIED is the absence of a decision and cannot be confirmed")
    if klass is ExpenseClass.ALLOCATED_COST and allocated_component not in COMPONENTS:
        raise LedgerRuleError(f"an allocated cost must say which cost it is: one of {', '.join(c.lower() for c in COMPONENTS)}")
    if klass is not ExpenseClass.ALLOCATED_COST and allocated_component is not None:
        raise LedgerRuleError("only an allocated cost (advertising, packaging, storage, logistics or other) names a cost pool")
    return _record_assignment(tenant_id, scope="ENTRY" if entry_id is not None else "CATEGORY", entry_id=entry_id, category=category, klass=klass,
                              state="CONFIRMED", by=confirmed_by, suggested_by=None, reason=None, allocated_component=allocated_component)


def suggest_class(tenant_id: UUID, *, klass: ExpenseClass, suggested_by: str, reason: str, entry_id: UUID | None = None, category: str | None = None) -> UUID:
    if (entry_id is None) == (category is None):
        raise LedgerRuleError("suggest a class for exactly one entry or one category")
    if suggested_by not in ("RULE", "MODEL"):
        raise LedgerRuleError("suggested_by must be RULE or MODEL")
    return _record_assignment(tenant_id, scope="ENTRY" if entry_id is not None else "CATEGORY", entry_id=entry_id, category=category, klass=klass,
                              state="SUGGESTED", by=None, suggested_by=suggested_by, reason=reason)


# --------------------------------------------------------------------------------------------------- reads
def _assignments_on(conn: Connection, tenant_id: UUID, entry_ids: Sequence[UUID], categories: Sequence[str]) -> tuple[dict[tuple[str, str], tuple[ExpenseClass, str, str | None]], dict[tuple[str, str], tuple[ExpenseClass, str, str | None]]]:
    """(confirmed, suggested): {(scope, key): (class, reason, allocated_component)} — the latest assignment per target that no later one supersedes."""
    out: dict[str, dict[tuple[str, str], tuple[ExpenseClass, str, str | None]]] = {"CONFIRMED": {}, "SUGGESTED": {}}
    sql = text(
        "SELECT a.scope, a.entry_id, a.category, a.class, a.state, coalesce(a.reason, ''), a.allocated_component FROM expense_class_assignment a "
        "WHERE a.tenant_id = :t AND ((a.scope = 'ENTRY' AND a.entry_id = ANY(:eids)) OR (a.scope = 'CATEGORY' AND a.category = ANY(:cats))) "
        "AND NOT EXISTS (SELECT 1 FROM expense_class_assignment n WHERE n.tenant_id = a.tenant_id AND n.supersedes_id = a.id) ORDER BY a.created_at")
    for scope, eid, cat, klass, state, reason, comp in conn.execute(sql, {"t": str(tenant_id), "eids": [str(i) for i in entry_ids], "cats": list(categories)}):
        out[state][(scope, str(eid) if scope == "ENTRY" else cat)] = (ExpenseClass(klass), reason, comp)
    return out["CONFIRMED"], out["SUGGESTED"]


def active_entries_on(conn: Connection, tenant_id: UUID, start: date | None, end: date | None) -> list[dict[str, Any]]:
    sql = f"SELECT {_ENTRY_COLUMNS} FROM expense_entry e WHERE {_ACTIVE_WHERE}"
    params: dict[str, Any] = {"tenant_id": str(tenant_id)}
    if start is not None:
        sql += " AND e.entry_date >= :s"
        params["s"] = start
    if end is not None:
        sql += " AND e.entry_date <= :e"
        params["e"] = end
    sql += " ORDER BY e.entry_date, e.created_at, e.id"
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def lines_for_period(tenant_id: UUID, start: date | None, end: date | None) -> list[ExpenseLine]:
    """The ledger as Phase 2a `ExpenseLine`s: the seller's confirmed class (entry beats category), the suggestion as a hint only, holds as stored."""
    with tenant_scope(tenant_id) as conn:
        rows = active_entries_on(conn, tenant_id, start, end)
        confirmed, suggested = _assignments_on(conn, tenant_id, [r["id"] for r in rows], sorted({r["category"] for r in rows}))
    lines: list[ExpenseLine] = []
    for r in rows:
        eid = str(r["id"])
        conf = confirmed.get(("ENTRY", eid)) or confirmed.get(("CATEGORY", r["category"]))
        sugg = suggested.get(("ENTRY", eid)) or suggested.get(("CATEGORY", r["category"]))
        lines.append(ExpenseLine(
            entry_id=eid, category=r["category"], amount_paise=int(r["amount_paise"]), entry_date=r["entry_date"], paid_date=r["paid_date"],
            confirmed_class=None if conf is None else conf[0], suggested_class=None if sugg is None else sugg[0], hold=ExpenseHold(r["hold"]),
            marketplace=r["marketplace"], allocated_component=None if conf is None else conf[2]))
    return lines


def list_entries(tenant_id: UUID, start: date | None, end: date | None) -> list[dict[str, Any]]:
    """Active entries with their effective class and the suggestion's reason, for the seller to review and confirm."""
    with tenant_scope(tenant_id) as conn:
        rows = active_entries_on(conn, tenant_id, start, end)
        confirmed, suggested = _assignments_on(conn, tenant_id, [r["id"] for r in rows], sorted({r["category"] for r in rows}))
    out = []
    for r in rows:
        eid = str(r["id"])
        conf = confirmed.get(("ENTRY", eid)) or confirmed.get(("CATEGORY", r["category"]))
        sugg = suggested.get(("ENTRY", eid)) or suggested.get(("CATEGORY", r["category"]))
        out.append({**r, "id": eid, "allocated_component": None if conf is None else conf[2], "confirmed_class": None if conf is None else conf[0].value, "suggested_class": None if sugg is None else sugg[0].value,
                    "suggestion_reason": None if sugg is None else sugg[1]})
    return out


def categories_with_assignment(tenant_id: UUID) -> set[str]:
    """Categories that already carry a category-level class (suggested or confirmed), so a suggestion is never repeated."""
    with tenant_scope(tenant_id) as conn:
        return {r[0] for r in conn.execute(text("SELECT DISTINCT category FROM expense_class_assignment WHERE tenant_id = :t AND scope = 'CATEGORY'"), {"t": str(tenant_id)})}


def overhead_coverage(tenant_id: UUID, start: date, end: date) -> OverheadCoverage:
    """D3: DECLARED_NONE when a live declaration covers the whole period; SOURCE_PRESENT when at least one active, non-held entry is dated in it."""
    with tenant_scope(tenant_id) as conn:
        declared = conn.execute(text(
            "SELECT 1 FROM expense_period_declaration d WHERE d.tenant_id = :t AND d.declaration = 'NO_OVERHEAD' AND d.period_start <= :s AND d.period_end >= :e "
            "AND NOT EXISTS (SELECT 1 FROM expense_period_declaration n WHERE n.tenant_id = d.tenant_id AND n.supersedes_id = d.id) LIMIT 1"),
            {"t": str(tenant_id), "s": start, "e": end}).first()
        if declared is not None:
            return OverheadCoverage.DECLARED_NONE
        present = conn.execute(text(f"SELECT 1 FROM expense_entry e WHERE {_ACTIVE_WHERE} AND e.hold = 'NONE' AND e.entry_date BETWEEN :s AND :e LIMIT 1"),
                               {"tenant_id": str(tenant_id), "s": start, "e": end}).first()
    return OverheadCoverage.SOURCE_PRESENT if present is not None else OverheadCoverage.NONE


def declare_no_overhead(tenant_id: UUID, start: date, end: date, declared_by: UUID) -> UUID:
    """E9: refused while the period holds confirmed OVERHEAD entries — the declaration would contradict the seller's own ledger."""
    if end < start:
        raise LedgerRuleError("the period ends before it starts")
    lines = lines_for_period(tenant_id, start, end)
    overhead = [ln for ln in lines if ln.hold is ExpenseHold.NONE and effective_class(ln) is ExpenseClass.OVERHEAD]
    if overhead:
        raise LedgerRuleError(f"{len(overhead)} overhead expense(s) already exist in this period; a 'no overhead' declaration would contradict them")
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(text(
            "INSERT INTO expense_period_declaration (id, tenant_id, period_start, period_end, declaration, declared_by) VALUES (:id, :t, :s, :e, 'NO_OVERHEAD', :by)"),
            {"id": str(new_id), "t": str(tenant_id), "s": start, "e": end, "by": str(declared_by)})
        read_model_version_repo.bump_on(conn, tenant_id)
    return new_id
