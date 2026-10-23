"""The ledger feed with seller-chosen multi-SKU assignments (§5.18.3 inside §5.17): shares are SKU-level and flagged manual, the remainder stays business-level, the pool
total never changes (MS6), an unmapped SKU goes to the review queue, and only advertising and storage can carry an assignment."""

from __future__ import annotations

from datetime import date

from calc_engine.formulas.expense_assignment import SkuAssignment
from calc_engine.formulas.ledger_feed import LedgerEvent, ledger_feed, ledger_watermark
from calc_engine.types import Paise

CAT = {"A": "A", "B": "B", "C": "C"}
P = dict(period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), channel_scope=None)


def ev(eid="e1", amount=10_001, cost_class="ADVERTISING", assignment=None, **kw) -> LedgerEvent:
    base = dict(expense_id=eid, seq=1, effective_date=date(2026, 9, 10), category="advertising", cost_class=cost_class, treatment="incremental", review_status="confirmed",
                amount=Paise(amount), assignment=assignment)
    base.update(kw)
    return LedgerEvent(**base)


def equal(*skus):
    return SkuAssignment("EQUAL", tuple((s, None) for s in skus))


def test_an_equal_assignment_becomes_sku_level_manual_shares() -> None:
    f = ledger_feed([ev(assignment=equal("A", "B", "C"))], catalog=CAT, **P)
    pool = f.pools["ADVERTISING"]
    assert {k: v.value for k, v in pool.sku_level.items()} == {"A": 3_334, "B": 3_334, "C": 3_333}
    assert pool.manual_sku_level.value == 10_001 and pool.business_level.value == 0 and pool.total.value == 10_001  # flagged manual (Q29); conserved


def test_ms6_the_pool_and_every_total_are_identical_with_and_without_the_assignment() -> None:
    plain = ledger_feed([ev()], catalog=CAT, **P)
    split = ledger_feed([ev(assignment=SkuAssignment("EXPLICIT_SHARES", (("A", 2_500), ("B", 2_500))))], catalog=CAT, **P)
    for f in (plain, split):
        assert f.expense_total.value == 10_001 and f.pools["ADVERTISING"].total.value == 10_001 and f.by_cost_class["ADVERTISING"].value == 10_001
    assert plain.pools["ADVERTISING"].business_level.value == 10_001  # unassigned without a tag
    s = split.pools["ADVERTISING"]
    assert s.business_level.value + sum(v.value for v in s.sku_level.values()) == 10_001  # assigned + unassigned = amount


def test_explicit_shares_below_one_hundred_percent_leave_the_remainder_business_level() -> None:
    f = ledger_feed([ev(amount=100_000, assignment=SkuAssignment("EXPLICIT_SHARES", (("A", 4_000), ("B", 3_000))))], catalog=CAT, **P)
    p = f.pools["ADVERTISING"]
    assert {k: v.value for k, v in p.sku_level.items()} == {"A": 40_000, "B": 30_000} and p.business_level.value == 30_000 and f.review_queue == ()


def test_ms5_an_unmapped_sku_gets_no_share_and_the_record_goes_to_the_review_queue_once() -> None:
    f = ledger_feed([ev(amount=9_000, assignment=equal("A", "X", "Y"))], catalog=CAT, **P)
    assert {k: v.value for k, v in f.pools["ADVERTISING"].sku_level.items()} == {"A": 9_000}
    assert [(i.expense_id, i.reason) for i in f.review_queue] == [("e1", "UNMAPPED_IDENTIFIER")] and f.pools["ADVERTISING"].total.value == 9_000


def test_storage_can_be_assigned_but_overhead_and_direct_ignore_an_assignment() -> None:
    f = ledger_feed([ev("s", cost_class="STORAGE", category="storage", assignment=equal("A", "B")), ev("o", cost_class="OVERHEAD", category="software", assignment=equal("A", "B"))],
                    catalog=CAT, **P)
    assert {k: v.value for k, v in f.pools["STORAGE"].sku_level.items()} == {"A": 5_001, "B": 5_000}
    assert f.pools["OVERHEAD"].sku_level == {} and f.pools["OVERHEAD"].business_level.value == 10_001


def test_a_pending_or_voided_assigned_record_is_not_counted() -> None:
    f = ledger_feed([ev("p", review_status="pending_review", assignment=equal("A")), ev("v", review_status="voided", assignment=equal("A"))], catalog=CAT, **P)
    assert f.pools["ADVERTISING"].total is None and f.pools["ADVERTISING"].sku_level == {} and f.review_queue_amount.value == 10_001


def test_a_refund_assigned_the_same_way_reduces_the_same_skus() -> None:
    f = ledger_feed([ev("c", amount=10_000, assignment=equal("A", "B")), ev("r", amount=-2_000, linked_expense_id="c", assignment=equal("A", "B"))], catalog=CAT, **P)
    assert {k: v.value for k, v in f.pools["ADVERTISING"].sku_level.items()} == {"A": 4_000, "B": 4_000} and f.pools["ADVERTISING"].total.value == 8_000


def test_the_watermark_changes_when_the_assignment_changes() -> None:
    a = ledger_watermark([ev(assignment=equal("A", "B"))])
    assert a != ledger_watermark([ev(assignment=equal("A", "C"))]) and a != ledger_watermark([ev()]) and a == ledger_watermark([ev(assignment=equal("A", "B"))])
    assert ledger_watermark([ev()]).startswith("ledger:1:")  # unchanged for records without an assignment


def test_ms6_a_data_driven_assignment_changes_where_the_pool_sits_never_its_total() -> None:
    from calc_engine.formulas.expense_assignment import basis_target

    data = {"A": basis_target("A", units_sold=6, units_returned=0), "B": basis_target("B", units_sold=4, units_returned=0)}
    plain = ledger_feed([ev(amount=10_001)], catalog=CAT, **P)
    split = ledger_feed([ev(amount=10_001, assignment=SkuAssignment("UNITS", (("A", None), ("B", None))))], catalog=CAT, basis_data=data, **P)
    for f in (plain, split):
        assert f.expense_total.value == 10_001 and f.pools["ADVERTISING"].total.value == 10_001
    pool = split.pools["ADVERTISING"]
    assert {k: v.value for k, v in pool.sku_level.items()} == {"A": 6_001, "B": 4_000} and pool.business_level.value == 0 and pool.manual_sku_level.value == 10_001


def test_a_data_assignment_without_basis_data_stays_business_level_and_nothing_is_lost() -> None:
    f = ledger_feed([ev(amount=5_000, assignment=SkuAssignment("ORDERS", (("A", None), ("B", None))))], catalog=CAT, **P)
    pool = f.pools["ADVERTISING"]
    assert pool.sku_level == {} and pool.business_level.value == 5_000 and pool.total.value == 5_000  # unavailable data is never read as zero: the amount stays visible


def test_the_watermark_changes_with_a_data_assignment() -> None:
    plain = ledger_feed([ev()], catalog=CAT, **P)
    split = ledger_feed([ev(assignment=SkuAssignment("UNITS", (("A", None), ("B", None))))], catalog=CAT, **P)
    assert plain.watermark != split.watermark
