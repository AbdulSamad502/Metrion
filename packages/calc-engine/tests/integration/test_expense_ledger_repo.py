"""The expense ledger on a real database (docs/specs/cfo-expense-ledger.md AC-L1…L9, golden scenarios of cfo-expense-model-options.md §7).

Golden values are hand-computed paise. Operating profit is evaluated through the Phase 2a formula on lines the ledger produces."""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from calc_engine.expense_ledger import LedgerRuleError, NewEntry  # noqa: E402
from calc_engine.formulas.expense_accounting import (  # noqa: E402
    ExpenseClass as C, ExpenseHold as H, OperatingProfitStatus, OverheadCoverage as OC, expense_breakdown, operating_profit,
)
from calc_engine.repositories import expense_ledger_repo as repo  # noqa: E402
from calc_engine.repositories import read_model_version_repo as rmv  # noqa: E402
from calc_engine.repositories.tenant_context import tenant_scope  # noqa: E402
from calc_engine.types import Unavailable  # noqa: E402

START, END = date(2026, 10, 1), date(2026, 10, 31)
USER = uuid.uuid4()


def entry(amount: int, category: str, *, day: int = 5, **kw) -> NewEntry:
    return NewEntry(entry_date=date(2026, 10, day), amount_paise=amount, category=category, vendor=kw.pop("vendor", "V"), **kw)


def add(t: uuid.UUID, *entries: NewEntry) -> repo.AddResult:
    return repo.add_entries(t, list(entries), USER)


def op(t: uuid.UUID, cp: int = 10_000_000):
    return operating_profit(cp, repo.lines_for_period(t, START, END), repo.overhead_coverage(t, START, END), period_start=START, period_end=END)


# ---------------------------------------------------------------------------------------------------- golden accounting scenarios (AC-L5)
def test_rent_reduces_operating_profit_and_an_unconfirmed_entry_makes_it_provisional_and_listed() -> None:
    t = uuid.uuid4()
    r = add(t, entry(1_200_000, "Rent", description="Oct"))
    r2 = op(t)
    assert not isinstance(r2, Unavailable) and r2.status is OperatingProfitStatus.PROVISIONAL and r2.value_paise == 10_000_000  # unconfirmed: not subtracted yet
    assert r2.unclassified.entry_ids == (str(r.inserted_ids[0]),) and r2.unclassified.total_paise == 1_200_000
    repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Rent")
    r3 = op(t)
    assert not isinstance(r3, Unavailable) and r3.status is OperatingProfitStatus.FINAL and r3.value_paise == 8_800_000 and r3.overhead_total_paise == 1_200_000


def test_inventory_purchase_owner_drawing_capital_and_tax_asset_never_reach_profit() -> None:
    t = uuid.uuid4()
    r = add(t, entry(5_000_000, "Stock purchase"), entry(300_000, "Owner draw"), entry(800_000, "Laptop"), entry(40_000, "TCS credit"), entry(100_000, "Software"))
    assert r.held_overlap == 1  # TCS is deducted by the marketplace: held until the seller says it is not already in a settlement
    repo.release_hold(t, r.held_ids[0], USER)
    for cat, klass in (("Stock purchase", C.INVENTORY_PURCHASE), ("Owner draw", C.OWNER_DRAWING), ("Laptop", C.CAPITAL), ("TCS credit", C.TAX_ASSET), ("Software", C.OVERHEAD)):
        repo.confirm_class(t, klass=klass, confirmed_by=USER, category=cat)
    r = op(t)
    assert not isinstance(r, Unavailable) and r.value_paise == 9_900_000 and r.overhead_total_paise == 100_000  # only software
    assert {k: v for k, v, _ in r.non_pnl_totals} == {C.INVENTORY_PURCHASE: 5_000_000, C.OWNER_DRAWING: 300_000, C.CAPITAL: 800_000, C.TAX_ASSET: 40_000}


def test_allocated_cost_is_not_subtracted_twice_and_a_refund_reduces_its_class() -> None:
    t = uuid.uuid4()
    add(t, entry(500_000, "Packaging"), entry(2_000_000, "Rent", description="Oct"), entry(-300_000, "Rent", description="Landlord refund", day=9))
    repo.confirm_class(t, klass=C.ALLOCATED_COST, confirmed_by=USER, category="Packaging", allocated_component="PACKAGING")
    repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Rent")
    r = op(t)
    assert not isinstance(r, Unavailable) and r.allocated_cost_total_paise == 500_000 and r.overhead_total_paise == 1_700_000 and r.value_paise == 8_300_000


def test_an_entry_class_beats_the_category_class_and_a_later_confirmation_beats_an_earlier_one() -> None:
    t = uuid.uuid4()
    r = add(t, entry(100_000, "Misc", description="a"), entry(200_000, "Misc", description="b"))
    repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Misc")
    repo.confirm_class(t, klass=C.OWNER_DRAWING, confirmed_by=USER, entry_id=r.inserted_ids[1])
    by = {ln.entry_id: ln for ln in repo.lines_for_period(t, START, END)}
    assert by[str(r.inserted_ids[0])].confirmed_class is C.OVERHEAD and by[str(r.inserted_ids[1])].confirmed_class is C.OWNER_DRAWING
    repo.confirm_class(t, klass=C.CAPITAL, confirmed_by=USER, category="Misc")  # supersedes the earlier category confirmation
    by = {ln.entry_id: ln for ln in repo.lines_for_period(t, START, END)}
    assert by[str(r.inserted_ids[0])].confirmed_class is C.CAPITAL and by[str(r.inserted_ids[1])].confirmed_class is C.OWNER_DRAWING


def test_a_suggestion_changes_no_figure_only_a_confirmation_does() -> None:
    t = uuid.uuid4()
    r = add(t, entry(250_000, "Software"))
    v0 = rmv.get(t)
    repo.suggest_class(t, klass=C.OVERHEAD, suggested_by="RULE", reason="looks like a subscription", category="Software")
    assert rmv.get(t) == v0  # nothing cached can be stale: nothing a figure depends on changed
    ln = repo.lines_for_period(t, START, END)[0]
    assert ln.confirmed_class is None and ln.suggested_class is C.OVERHEAD
    listed = repo.list_entries(t, START, END)[0]
    assert listed["suggestion_reason"] == "looks like a subscription" and listed["confirmed_class"] is None
    out = op(t)
    assert not isinstance(out, Unavailable) and out.value_paise == 10_000_000 and out.status is OperatingProfitStatus.PROVISIONAL
    repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Software")
    assert rmv.get(t) == v0 + 1
    assert r.inserted_ids


def test_operating_profit_is_unavailable_without_entries_or_a_declaration_and_the_declaration_rules_hold() -> None:
    t = uuid.uuid4()
    assert isinstance(op(t), Unavailable)
    repo.declare_no_overhead(t, START, END, USER)
    r = op(t)
    assert not isinstance(r, Unavailable) and r.value_paise == 10_000_000 and r.status is OperatingProfitStatus.FINAL
    u = uuid.uuid4()
    add(u, entry(100_000, "Rent"))
    repo.confirm_class(u, klass=C.OVERHEAD, confirmed_by=USER, category="Rent")
    with pytest.raises(LedgerRuleError, match="contradict"):
        repo.declare_no_overhead(u, START, END, USER)  # E9


# ---------------------------------------------------------------------------------------------------- duplicates and overlap (AC-L3)
def test_exact_repeats_are_skipped_within_a_batch_and_across_uploads() -> None:
    t = uuid.uuid4()
    r = add(t, entry(100_000, "Rent"), entry(100_000, "RENT "), entry(100_000, "rent"))
    assert len(r.inserted_ids) == 1 and r.skipped_exact_duplicates == 2
    again = add(t, entry(100_000, "Rent"))
    assert again.inserted_ids == () and again.skipped_exact_duplicates == 1
    assert len(repo.lines_for_period(t, START, END)) == 1


def test_a_possible_duplicate_is_held_excluded_from_totals_and_listed() -> None:
    t = uuid.uuid4()
    add(t, entry(100_000, "Rent", description="Oct rent"))
    r = add(t, entry(100_000, "Rent", description="Rent payment"))  # same day/amount/vendor, other text
    assert r.held_possible_duplicates == 1
    repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Rent")
    out = op(t)
    assert not isinstance(out, Unavailable) and out.overhead_total_paise == 100_000  # counted once
    assert out.held.entry_ids == (str(r.held_ids[0]),) and out.held.total_paise == 100_000 and out.status is OperatingProfitStatus.PROVISIONAL
    released = repo.release_hold(t, r.held_ids[0], USER)
    out2 = op(t)
    assert not isinstance(out2, Unavailable) and out2.overhead_total_paise == 200_000 and out2.held.line_count == 0
    assert str(released) in {ln.entry_id for ln in repo.lines_for_period(t, START, END)}
    with pytest.raises(LedgerRuleError):
        repo.release_hold(t, released, USER)  # not on hold any more


def test_marketplace_deduction_like_categories_wait_for_the_sellers_word() -> None:
    t = uuid.uuid4()
    r = add(t, entry(180_000, "Commission"))
    assert r.held_overlap == 1
    b = expense_breakdown(repo.lines_for_period(t, START, END))
    assert b.groups == () and [(e.hold, e.total_paise) for e in b.excluded] == [(H.MAY_OVERLAP_UNCONFIRMED, 180_000)]


# ---------------------------------------------------------------------------------------------------- corrections and append-only (AC-L1)
def test_a_correction_and_a_void_are_new_rows_and_the_history_stays() -> None:
    t = uuid.uuid4()
    first = add(t, entry(100_000, "Rent")).inserted_ids[0]
    fixed = repo.supersede_entry(t, first, entry(110_000, "Rent"), USER)
    active = [ln.entry_id for ln in repo.lines_for_period(t, START, END)]
    assert active == [str(fixed)]
    with pytest.raises(LedgerRuleError):
        repo.supersede_entry(t, first, entry(120_000, "Rent"), USER)  # the original is no longer active
    repo.void_entry(t, fixed, USER, "entered by mistake")
    assert repo.lines_for_period(t, START, END) == []
    with tenant_scope(t) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_entry WHERE tenant_id = :t"), {"t": str(t)}).scalar_one() == 3  # original, correction, void
    with pytest.raises(LedgerRuleError):
        repo.supersede_entry(t, fixed, entry(1, "Rent"), USER)


def test_the_application_role_cannot_update_or_delete_ledger_rows() -> None:
    t = uuid.uuid4()
    add(t, entry(100_000, "Rent"))
    for sql in ("UPDATE expense_entry SET amount_paise = 1", "DELETE FROM expense_entry", "TRUNCATE expense_entry",
                "UPDATE expense_class_assignment SET class = 'OVERHEAD'", "DELETE FROM expense_class_assignment",
                "UPDATE expense_period_declaration SET period_end = period_end", "DELETE FROM expense_period_declaration"):
        with pytest.raises((DBAPIError, Exception), match="permission denied"):
            with tenant_scope(t) as conn:
                conn.execute(text(sql))


def test_database_checks_reject_bad_values_whatever_the_application_does() -> None:
    t = uuid.uuid4()
    base = ("INSERT INTO expense_entry (tenant_id, source, entry_date, amount_paise, category, identity, hold, created_by{extra}) "
            "VALUES (:t, :src, '2026-10-05', 1, :cat, :i, :hold, :by{extra_v})")

    def insert(src="MANUAL", cat="Rent", hold="NONE", i=None, extra="", extra_v="") -> None:
        with tenant_scope(t) as conn:
            conn.execute(text(base.format(extra=extra, extra_v=extra_v)), {"t": str(t), "src": src, "cat": cat, "i": i or uuid.uuid4().hex, "hold": hold, "by": str(USER)})

    insert()
    for kwargs in ({"src": "EMAIL"}, {"cat": "   "}, {"hold": "MAYBE"}):
        with pytest.raises(IntegrityError):
            insert(**kwargs)
    with pytest.raises(IntegrityError):
        insert(extra=", marketplace", extra_v=", 'EBAY'")
    with pytest.raises(IntegrityError):
        insert(extra=", gst_treatment", extra_v=", 'WHATEVER'")
    with pytest.raises(IntegrityError):
        with tenant_scope(t) as conn:  # a class outside the seven
            conn.execute(text("INSERT INTO expense_class_assignment (tenant_id, scope, category, class, state) VALUES (:t, 'CATEGORY', 'Rent', 'MAGIC', 'SUGGESTED')"), {"t": str(t)})
    with pytest.raises(IntegrityError):
        with tenant_scope(t) as conn:  # confirmed without a confirmer
            conn.execute(text("INSERT INTO expense_class_assignment (tenant_id, scope, category, class, state) VALUES (:t, 'CATEGORY', 'Rent', 'OVERHEAD', 'CONFIRMED')"), {"t": str(t)})
    with pytest.raises(IntegrityError):
        with tenant_scope(t) as conn:  # entry scope without an entry
            conn.execute(text("INSERT INTO expense_class_assignment (tenant_id, scope, category, class, state) VALUES (:t, 'ENTRY', 'Rent', 'OVERHEAD', 'SUGGESTED')"), {"t": str(t)})


def test_the_identity_is_unique_among_entries_that_count() -> None:
    t = uuid.uuid4()
    with tenant_scope(t) as conn:
        for _ in range(1):
            conn.execute(text("INSERT INTO expense_entry (tenant_id, source, entry_date, amount_paise, category, identity, created_by) VALUES (:t, 'MANUAL', '2026-10-05', 1, 'x', 'same', :by)"),
                         {"t": str(t), "by": str(USER)})
    with pytest.raises(IntegrityError):
        with tenant_scope(t) as conn:
            conn.execute(text("INSERT INTO expense_entry (tenant_id, source, entry_date, amount_paise, category, identity, created_by) VALUES (:t, 'MANUAL', '2026-10-05', 1, 'x', 'same', :by)"),
                         {"t": str(t), "by": str(USER)})


# ---------------------------------------------------------------------------------------------------- read model + isolation + periods (AC-L7, AC-L9)
def test_every_write_bumps_the_read_model_version_in_the_same_transaction() -> None:
    t = uuid.uuid4()
    v = rmv.get(t)
    first = add(t, entry(100_000, "Rent")).inserted_ids[0]
    assert rmv.get(t) == v + 1
    add(t, entry(100_000, "Rent"))  # a pure duplicate writes nothing, so nothing is invalidated
    assert rmv.get(t) == v + 1
    repo.supersede_entry(t, first, entry(110_000, "Rent"), USER)
    repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Rent")
    repo.declare_no_overhead(uuid.uuid4(), START, END, USER)
    assert rmv.get(t) == v + 3
    with pytest.raises(RuntimeError):
        with tenant_scope(t) as conn:
            repo.add_entries_on(conn, t, [entry(5, "Other")], USER)
            raise RuntimeError("the surrounding write failed")
    assert rmv.get(t) == v + 3 and len(repo.list_entries(t, START, END)) == 1  # rows and version roll back together


def test_tenants_never_see_each_others_ledger() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    ra = add(a, entry(100_000, "Rent"))
    assert repo.lines_for_period(b, START, END) == [] and isinstance(op(b), Unavailable)
    with tenant_scope(b) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_entry WHERE id = :i"), {"i": str(ra.inserted_ids[0])}).scalar_one() == 0
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO expense_entry (tenant_id, source, entry_date, amount_paise, category, identity, created_by) VALUES (:t, 'MANUAL', '2026-10-05', 1, 'x', 'z', :by)"),
                         {"t": str(a), "by": str(USER)})
    with pytest.raises(LedgerRuleError):
        repo.confirm_class(b, klass=C.OVERHEAD, confirmed_by=USER, entry_id=ra.inserted_ids[0])  # another tenant's entry does not exist for b


def test_profit_uses_the_incurred_date_and_period_edges_are_inclusive() -> None:
    t = uuid.uuid4()
    add(t, entry(100_000, "Rent", day=1, paid_date=date(2026, 11, 20)), entry(200_000, "Rent", day=31, description="end"),
        NewEntry(entry_date=date(2026, 9, 30), amount_paise=900_000, category="Rent", vendor="V"), NewEntry(entry_date=date(2026, 11, 1), amount_paise=700_000, category="Rent", vendor="V"))
    repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Rent")
    r = op(t)
    assert not isinstance(r, Unavailable) and r.overhead_total_paise == 300_000  # 1 Oct and 31 Oct count; 30 Sep and 1 Nov do not; the paid date is irrelevant to profit


def test_bad_requests_are_refused_before_any_write() -> None:
    t = uuid.uuid4()
    with pytest.raises(LedgerRuleError):
        add(t, entry(0, "Rent"))
    with pytest.raises(LedgerRuleError):
        repo.confirm_class(t, klass=C.OTHER_UNCLASSIFIED, confirmed_by=USER, category="Rent")
    with pytest.raises(LedgerRuleError):
        repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER)
    with pytest.raises(LedgerRuleError):
        repo.suggest_class(t, klass=C.OVERHEAD, suggested_by="HUMAN", reason="x", category="Rent")
    assert rmv.get(t) == 0


def test_an_allocated_cost_must_name_its_cost_pool_and_the_component_is_validated() -> None:
    import pytest

    from calc_engine.expense_ledger import LedgerRuleError

    t = uuid.uuid4()
    add(t, entry(500_000, "Packaging"))
    with pytest.raises(LedgerRuleError, match="which cost"):
        repo.confirm_class(t, klass=C.ALLOCATED_COST, confirmed_by=USER, category="Packaging")
    with pytest.raises(LedgerRuleError):
        repo.confirm_class(t, klass=C.ALLOCATED_COST, confirmed_by=USER, category="Packaging", allocated_component="COGS")
    with pytest.raises(LedgerRuleError):
        repo.confirm_class(t, klass=C.OVERHEAD, confirmed_by=USER, category="Packaging", allocated_component="PACKAGING")  # only an allocated cost names a pool
    repo.confirm_class(t, klass=C.ALLOCATED_COST, confirmed_by=USER, category="Packaging", allocated_component="PACKAGING")
    assert {ln.allocated_component for ln in repo.lines_for_period(t, START, END)} == {"PACKAGING"}


# ---------------------------------------------------------------------------------------------------- payment states and the removal reason (docs/specs/cfo-expense-ledger.md 14.5)
def _active(t: uuid.UUID) -> list[dict]:
    return repo.list_entries(t, None, None)


def test_no_payment_statement_reads_as_not_stated_never_unpaid_or_paid() -> None:
    t = uuid.uuid4()
    add(t, entry(500_000, "Rent"))
    row = _active(t)[0]
    assert row["payment_status"] is None and row["paid_amount_paise"] is None


def test_payment_states_are_recorded_append_only_and_the_latest_wins_without_moving_any_figure() -> None:
    t = uuid.uuid4()
    eid = add(t, entry(500_000, "Rent")).inserted_ids[0]
    version = rmv.get(t) if hasattr(rmv, "get") else None
    assert repo.set_payment(t, eid, "UNPAID", None, USER) is True
    assert repo.set_payment(t, eid, "unpaid", None, USER) is False  # a repeat writes nothing
    assert repo.set_payment(t, eid, "PARTIALLY_PAID", 200_000, USER) is True
    assert repo.set_payment(t, eid, "PAID", None, USER) is True
    row = _active(t)[0]
    assert (row["payment_status"], row["paid_amount_paise"]) == ("PAID", None)
    with tenant_scope(t) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_payment_event WHERE entry_id = :e"), {"e": str(eid)}).scalar_one() == 3  # the history is kept
    if version is not None:
        assert rmv.get(t) == version  # payment is information about cash: no cached figure is invalidated


def test_a_partial_payment_must_be_between_zero_and_the_whole_and_a_removed_entry_takes_no_payment() -> None:
    t = uuid.uuid4()
    eid = add(t, entry(500_000, "Rent")).inserted_ids[0]
    for bad in (None, 0, 500_000, 600_000):
        with pytest.raises(LedgerRuleError):
            repo.set_payment(t, eid, "PARTIALLY_PAID", bad, USER)
    repo.void_entry(t, eid, USER, "entered by mistake")
    with pytest.raises(LedgerRuleError):
        repo.set_payment(t, eid, "PAID", None, USER)


def test_the_database_itself_refuses_a_payment_row_that_breaks_the_shape() -> None:
    t = uuid.uuid4()
    eid = add(t, entry(500_000, "Rent")).inserted_ids[0]
    with pytest.raises((IntegrityError, DBAPIError)), tenant_scope(t) as conn:
        conn.execute(text("INSERT INTO expense_payment_event (tenant_id, entry_id, payment_status, paid_amount_paise, created_by) VALUES (:t, :e, 'PAID', 5, :u)"),
                     {"t": str(t), "e": str(eid), "u": str(USER)})


def test_a_removal_keeps_who_why_and_when_and_needs_a_reason() -> None:
    t = uuid.uuid4()
    eid = add(t, entry(500_000, "Rent")).inserted_ids[0]
    for bad in ("", "ok", None):
        with pytest.raises(LedgerRuleError):
            repo.void_entry(t, eid, USER, bad)  # type: ignore[arg-type]
    assert len(_active(t)) == 1  # a refused removal changed nothing
    void_id = repo.void_entry(t, eid, USER, "  Duplicate   entry ")
    with tenant_scope(t) as conn:
        row = conn.execute(text("SELECT is_void, void_reason, created_by, created_at, supersedes_id FROM expense_entry WHERE id = :i"), {"i": str(void_id)}).one()
    assert row.is_void and row.void_reason == "Duplicate entry" and str(row.created_by) == str(USER) and row.created_at is not None and str(row.supersedes_id) == str(eid)
    assert _active(t) == []
    got = repo.get_entry(t, eid)
    assert got is not None and got["superseded"] is True  # the original is still readable


def test_the_database_refuses_a_new_void_row_without_a_reason() -> None:
    t = uuid.uuid4()
    eid = add(t, entry(500_000, "Rent")).inserted_ids[0]
    with pytest.raises((IntegrityError, DBAPIError)), tenant_scope(t) as conn:
        conn.execute(text("INSERT INTO expense_entry (id, tenant_id, source, entry_date, amount_paise, category, identity, hold, supersedes_id, is_void, created_by) "
                          "VALUES (gen_random_uuid(), :t, 'MANUAL', '2026-10-05', 500000, 'Rent', 'void:x', 'NONE', :e, true, :u)"), {"t": str(t), "e": str(eid), "u": str(USER)})


def test_a_correction_carries_the_payment_statement_unless_the_new_amount_makes_it_impossible() -> None:
    t = uuid.uuid4()
    a = add(t, entry(500_000, "Rent")).inserted_ids[0]
    repo.set_payment(t, a, "PARTIALLY_PAID", 300_000, USER)
    b = repo.supersede_entry(t, a, entry(450_000, "Rent"), USER)  # 3,000.00 of 4,500.00 is still a partial payment
    assert repo.get_entry(t, b)["payment_status"] == "PARTIALLY_PAID"
    c = repo.supersede_entry(t, b, entry(250_000, "Rent"), USER)  # 3,000.00 is now more than the whole: the statement is not carried, not guessed
    assert repo.get_entry(t, c)["payment_status"] is None
