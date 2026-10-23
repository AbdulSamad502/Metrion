"""The expense-ledger feed as a pure function over fixture rows — engine spec §5.17 (Rounds 6–8), expense-tracker F1, F6, F7, AC16, AC17.

No database: rows are fixtures. Only `confirmed` + `incremental` rows count; the latest event per expense wins; a refund is a negative row in the
period of its own date; an absent class is `None` ("not entered"), never zero; the SKU-level rule for advertising and storage is Q29.
"""

from __future__ import annotations

from datetime import date

import pytest

from calc_engine.formulas.allocation import AllocationBasis
from calc_engine.formulas.allocation_outcome import AllocationTarget, allocate_with_basis
from calc_engine.formulas.expense_profit import compute_profit_statement, pool_split
from calc_engine.formulas.ledger_feed import (
    LedgerEvent,
    engine_to_ledger_display,
    ledger_feed,
    ledger_to_engine_pool,
    ledger_watermark,
    ledger_display_to_signed,
)
from calc_engine.types import Paise

SEP = (date(2026, 9, 1), date(2026, 9, 30))
OCT = (date(2026, 10, 1), date(2026, 10, 31))
CATALOG = {"B0ASIN1": "SKU-1", "SKU-2": "SKU-2"}


def ev(eid, amount, *, cls="OVERHEAD", seq=1, day=date(2026, 9, 10), treatment="incremental", status="confirmed", category="rent", **kw):
    return LedgerEvent(
        expense_id=eid, seq=seq, effective_date=day, category=category, cost_class=cls, treatment=treatment, review_status=status,
        amount=Paise(amount), **kw,
    )


def feed(events, period=SEP, channel=None):
    return ledger_feed(events, period_start=period[0], period_end=period[1], channel_scope=channel, catalog=CATALOG)


# --- treatments and review states -------------------------------------------------------------------------------------------------------
def test_only_confirmed_incremental_rows_count_and_the_others_are_visible_not_summed():
    r = feed([
        ev("e1", 10_000),
        ev("e2", 4_000, treatment="already_in_settlement"),
        ev("e3", 2_500, treatment="informational"),
    ])
    assert r.pools["OVERHEAD"].total == Paise(10_000)
    assert r.excluded_by_treatment == {"already_in_settlement": Paise(4_000), "informational": Paise(2_500)}


def test_review_states_only_confirmed_counts_pending_is_queued_draft_and_voided_are_not_counted():
    r = feed([
        ev("e1", 1_000),
        ev("e2", 700, status="pending_review"),
        ev("e3", 300, status="draft"),
        ev("e4", 9_999, status="voided"),
    ])
    assert r.pools["OVERHEAD"].total == Paise(1_000)
    assert r.review_queue_amount == Paise(700)
    assert r.including_unresolved == Paise(1_700)
    assert [i.reason for i in r.review_queue] == ["PENDING_REVIEW"]


def test_latest_event_per_expense_wins_and_a_later_void_removes_it():
    edited = feed([ev("e1", 1_000, seq=1), ev("e1", 1_500, seq=2)])
    assert edited.pools["OVERHEAD"].total == Paise(1_500)
    voided = feed([ev("e1", 1_000, seq=1), ev("e1", 1_000, seq=2, status="voided")])
    assert voided.pools["OVERHEAD"].total is None  # nothing left: not entered, not zero


def test_input_order_does_not_change_the_result_or_the_watermark():
    rows = [ev("e1", 100, seq=1), ev("e2", 200, seq=2), ev("e3", 300, seq=3, cls="DIRECT")]
    assert feed(rows) == feed(list(reversed(rows)))
    assert ledger_watermark(rows) == ledger_watermark(list(reversed(rows)))


# --- F1 signed amounts, both directions --------------------------------------------------------------------------------------------------
def test_f1_cost_positive_refund_negative_map_to_the_engine_and_back():
    assert ledger_to_engine_pool([Paise(10_000), Paise(-2_500)]) == Paise(7_500)
    d = engine_to_ledger_display(Paise(7_500))
    assert (d.kind, d.magnitude) == ("COST", Paise(7_500))
    assert ledger_display_to_signed(d) == Paise(7_500)
    credit = engine_to_ledger_display(Paise(-2_500))
    assert (credit.kind, credit.magnitude) == ("NET_CREDIT", Paise(2_500))
    assert ledger_display_to_signed(credit) == Paise(-2_500)  # never floored, round-trips
    zero = engine_to_ledger_display(Paise(0))
    assert (zero.kind, zero.magnitude) == ("COST", Paise(0))


def test_f1_a_refund_posts_to_the_period_of_its_own_date_and_leaves_the_original_period_alone():
    rows = [ev("c1", 10_000, day=date(2026, 9, 5)), ev("r1", -4_000, day=date(2026, 10, 3), linked_expense_id="c1")]
    assert feed(rows, SEP).pools["OVERHEAD"].total == Paise(10_000)
    assert feed(rows, OCT).pools["OVERHEAD"].total == Paise(-4_000)  # a net credit in October, not floored


# --- not entered vs zero; unknown class ----------------------------------------------------------------------------------------------------
def test_an_absent_class_is_not_entered_never_zero_and_an_explicit_zero_is_entered():
    r = feed([ev("e1", 5_000)])
    assert r.pools["ADVERTISING"].total is None
    assert r.pools["ADVERTISING"].entered is False
    assert "advertising: not entered" in r.gaps
    z = feed([ev("a1", 0, cls="ADVERTISING")])
    assert z.pools["ADVERTISING"].total == Paise(0) and z.pools["ADVERTISING"].entered is True
    assert "advertising: not entered" not in z.gaps


def test_an_unknown_cost_class_is_queued_not_counted_and_not_dropped():
    r = feed([ev("e1", 800, cls="MYSTERY")])
    assert [i.reason for i in r.review_queue] == ["UNKNOWN_COST_CLASS"]
    assert r.including_unresolved == Paise(800)
    assert all(p.total is None for p in r.pools.values())


# --- scope -----------------------------------------------------------------------------------------------------------------------------------
def test_channel_scope_takes_only_its_own_rows_business_wide_is_reported_not_spread():
    rows = [ev("w", 1_000), ev("a", 400, channel_scope="AMAZON"), ev("f", 600, channel_scope="FLIPKART")]
    whole = feed(rows)
    assert whole.pools["OVERHEAD"].total == Paise(2_000)
    amazon = feed(rows, channel="AMAZON")
    assert amazon.pools["OVERHEAD"].total == Paise(400)
    assert amazon.business_wide_out_of_scope == Paise(1_000)


# --- aggregates ------------------------------------------------------------------------------------------------------------------------
def test_aggregates_by_category_cost_class_and_recurring():
    r = feed([
        ev("e1", 1_000, category="rent", recurring=True),
        ev("e2", 250, category="software", recurring=True),
        ev("e3", 700, category="packaging", cls="DIRECT"),
    ])
    assert r.by_category == {"packaging": Paise(700), "rent": Paise(1_000), "software": Paise(250)}
    assert r.by_cost_class == {"DIRECT": Paise(700), "OVERHEAD": Paise(1_250)}
    assert r.recurring_total == Paise(1_250)
    assert r.expense_total == Paise(1_950)


# --- F6 / AC16: the Q29 SKU-level rule ----------------------------------------------------------------------------------------------------
def test_f6_validated_import_with_a_mapped_identifier_is_sku_level():
    r = feed([ev("a1", 3_000, cls="ADVERTISING", origin="IMPORT", source_validated=True, identifier="B0ASIN1")])
    p = r.pools["ADVERTISING"]
    assert p.sku_level == {"SKU-1": Paise(3_000)} and p.business_level == Paise(0) and p.total == Paise(3_000)


def test_f6_campaign_spend_without_an_asin_is_business_level():
    r = feed([ev("a1", 3_000, cls="ADVERTISING", origin="IMPORT", source_validated=True, identifier=None)])
    assert r.pools["ADVERTISING"].sku_level == {} and r.pools["ADVERTISING"].business_level == Paise(3_000)


def test_f6_an_import_that_is_not_validated_is_business_level():
    r = feed([ev("a1", 3_000, cls="ADVERTISING", origin="IMPORT", source_validated=False, identifier="B0ASIN1")])
    assert r.pools["ADVERTISING"].sku_level == {}


def test_f6_manual_is_business_level_unless_tagged_and_a_tagged_entry_stays_flagged_manual():
    plain = feed([ev("a1", 1_000, cls="ADVERTISING", origin="MANUAL")])
    assert plain.pools["ADVERTISING"].sku_level == {} and plain.pools["ADVERTISING"].manual_sku_level == Paise(0)
    tagged = feed([ev("a2", 1_000, cls="STORAGE", origin="MANUAL", sku_tag="SKU-2")])
    p = tagged.pools["STORAGE"]
    assert p.sku_level == {"SKU-2": Paise(1_000)} and p.manual_sku_level == Paise(1_000)


def test_f6_an_unmapped_identifier_is_business_level_and_goes_to_the_review_queue():
    r = feed([ev("a1", 2_000, cls="ADVERTISING", origin="IMPORT", source_validated=True, identifier="B0UNKNOWN")])
    p = r.pools["ADVERTISING"]
    assert p.sku_level == {} and p.business_level == Paise(2_000) and p.total == Paise(2_000)
    assert [i.reason for i in r.review_queue] == ["UNMAPPED_IDENTIFIER"]
    assert r.review_queue_amount == Paise(0)  # still counted, only flagged for resolution


# --- watermark -------------------------------------------------------------------------------------------------------------------------
def test_the_watermark_changes_when_an_event_is_appended():
    base = [ev("e1", 100, seq=1)]
    assert ledger_watermark(base) != ledger_watermark(base + [ev("e1", 150, seq=2)])
    assert ledger_watermark(base).startswith("ledger:1:")


# --- F7 / AC17 / TP10: reconciliation across missing, zero, unallocated and allocated ------------------------------------------------------
@pytest.mark.parametrize("basis", [None, AllocationBasis.NET_REVENUE])
def test_f7_dashboard_total_equals_pl_expense_lines_plus_unallocated_and_the_four_states_stay_distinct(basis):
    rows = [
        ev("ads", 5_000, cls="ADVERTISING", origin="IMPORT", source_validated=True, identifier="B0ASIN1"),  # allocated directly (SKU-level)
        ev("sto0", 0, cls="STORAGE"),                                                                     # explicit zero
        ev("ovh", 9_001),                                                                                 # business overhead: allocated or not
        ev("dir", 700, cls="DIRECT", category="packaging"),
    ]                                                                                                     # nothing for... all four classes present except none missing
    r = feed(rows)
    targets = [AllocationTarget(ref="SKU-1", data_period="2026-09-01/2026-09-30", data_scope="ALL", net_revenue=Paise(100))]
    def split(cls):
        p = r.pools[cls]
        biz = p.business_level
        out = allocate_with_basis(biz, pool_period="2026-09-01/2026-09-30", pool_scope="ALL", basis=basis, targets=targets)
        return pool_split(p.total, p.total - biz, out)
    s = compute_profit_statement(
        net_realized_revenue=Paise(100_000), cogs=Paise(1), marketplace_fees=Paise(0), shipping_logistics=Paise(0), return_rto_losses=Paise(0),
        other_attributed_costs=r.pools["DIRECT"].total, advertising=split("ADVERTISING"), storage=split("STORAGE"), overhead=split("OVERHEAD"),
    )
    assert r.expense_total.value == s.pl_expense_lines.value + s.unallocated_lines.value
    assert r.pools["STORAGE"].total == Paise(0) and r.pools["STORAGE"].entered           # explicit zero stays zero
    assert (s.unallocated_overhead.value == 9_001) == (basis is None)                       # unallocated vs allocated stay distinct
    missing = feed([ev("ovh", 100)])
    assert missing.pools["ADVERTISING"].total is None                                       # missing stays None, not 0
