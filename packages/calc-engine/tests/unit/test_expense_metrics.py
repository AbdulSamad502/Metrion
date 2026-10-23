"""Metric codes, inactive definitions and minting for the expense aggregates and profit lines — engine spec §9.3 (Round 6) and §9.2.

Stamping is the existing one: `formula_version`, `canonical_data_version`, `as_of_date`, `manual_adjustment_set`, `input_refs` (here carrying the ledger
watermark, no schema change), `exclusions` (reason codes of unallocated lines), `is_available`. The new definitions are INACTIVE: not in `SEED_DEFINITIONS`,
not seeded, and the active formula versions stay exactly what they were.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from fractions import Fraction

from calc_engine.api.compute_metric import MetricResult
from calc_engine.api.expense_metrics import mint_expense_metrics
from calc_engine.definitions.expense_definitions import (
    ACTIVE_FORMULA_VERSIONS,
    EXPENSE_METRIC_CODES,
    INACTIVE_DEFINITIONS,
    INACTIVE_FORMULA_VERSIONS,
)
from calc_engine.definitions.schema import parse_node
from calc_engine.definitions.seed_definitions import SEED_DEFINITIONS
from calc_engine.formulas.allocation import AllocationBasis
from calc_engine.formulas.allocation_outcome import AllocationTarget, allocate_with_basis
from calc_engine.formulas.expense_profit import compute_profit_statement, pool_split
from calc_engine.formulas.ledger_feed import LedgerEvent, ledger_feed
from calc_engine.types import Paise, Unavailable

P = "2026-09-01/2026-09-30"
AT = datetime(2026, 10, 16, tzinfo=timezone.utc)


def ev(eid, amount, cls, *, category="x", recurring=False):
    return LedgerEvent(expense_id=eid, seq=1, effective_date=date(2026, 9, 10), category=category, cost_class=cls, treatment="incremental",
                       review_status="confirmed", amount=Paise(amount), recurring=recurring)


def build(*, cogs=Paise(100), basis=None):
    feed = ledger_feed(
        [ev("a", 5_000, "ADVERTISING", category="ads"), ev("s", 2_000, "STORAGE", category="warehouse"), ev("o", 9_001, "OVERHEAD", category="rent", recurring=True)],
        period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), channel_scope=None, catalog={},
    )
    targets = [AllocationTarget(ref="SKU-1", data_period=P, data_scope="ALL", net_revenue=Paise(1000))]
    def split(cls):
        pool = feed.pools[cls]
        out = allocate_with_basis(pool.business_level, pool_period=P, pool_scope="ALL", basis=basis, targets=targets)
        return pool_split(pool.total, pool.total - pool.business_level, out)
    statement = compute_profit_statement(
        net_realized_revenue=Paise(100_000), cogs=cogs, marketplace_fees=Paise(0), shipping_logistics=Paise(0), return_rto_losses=Paise(0),
        other_attributed_costs=Paise(0), advertising=split("ADVERTISING"), storage=split("STORAGE"), overhead=split("OVERHEAD"),
    )
    return feed, statement


def mint(feed, statement, **kw):
    return mint_expense_metrics(
        feed, statement, ingestion_run_ids=["run-1"], adapter_versions=["meesho.v1"], active_adjustment_ids=["adj-1"], computed_at=AT,
        as_of_date=date(2026, 9, 30), **kw,
    )


def test_every_proposed_metric_code_exists_with_a_v1_version_and_contribution_profit_gets_v2():
    assert set(EXPENSE_METRIC_CODES) == {
        "EXPENSE_TOTAL", "EXPENSE_BY_CATEGORY", "EXPENSE_BY_COST_CLASS", "EXPENSE_RECURRING_TOTAL", "EXPENSE_REVIEW_QUEUE_AMOUNT",
        "EXPENSE_INCLUDING_UNRESOLVED", "UNALLOCATED_ADVERTISING", "UNALLOCATED_STORAGE", "UNALLOCATED_OVERHEAD", "ALLOCATED_OVERHEAD",
        "FULLY_ALLOCATED_PROFIT", "TOTAL_PROFIT",
    }
    for code in EXPENSE_METRIC_CODES:
        assert INACTIVE_FORMULA_VERSIONS[code] == f"{code}.v1"
    assert INACTIVE_FORMULA_VERSIONS["CONTRIBUTION_PROFIT"] == "CONTRIBUTION_PROFIT.v2"


def test_the_new_definitions_are_inactive_and_nothing_existing_changed():
    assert not (set(INACTIVE_DEFINITIONS) & set(SEED_DEFINITIONS))
    assert set(SEED_DEFINITIONS) == {"GROSS_ORDER_VALUE.v1", "SELLER_FUNDED_DISCOUNTS.v1", "NET_REALIZED_REVENUE.v1", "CONTRIBUTION_PROFIT.v1"}
    assert ACTIVE_FORMULA_VERSIONS["CONTRIBUTION_PROFIT"] == "CONTRIBUTION_PROFIT.v1"
    assert ACTIVE_FORMULA_VERSIONS["NET_REALIZED_REVENUE"] == "NET_REALIZED_REVENUE.v1"
    assert "TOTAL_PROFIT" not in ACTIVE_FORMULA_VERSIONS  # not released: no release date set (Q15)
    for key, definition in INACTIVE_DEFINITIONS.items():
        parse_node(definition)  # every inactive definition is a valid closed-schema node
        assert key in INACTIVE_FORMULA_VERSIONS.values()


def test_minted_results_carry_the_existing_stamp_and_the_ledger_watermark():
    feed, statement = build()
    minted = mint(feed, statement)
    codes = {m.result.metric_code for m in minted}
    assert {"EXPENSE_TOTAL", "TOTAL_PROFIT", "FULLY_ALLOCATED_PROFIT", "UNALLOCATED_OVERHEAD", "CONTRIBUTION_PROFIT"} <= codes
    for m in minted:
        r: MetricResult = m.result
        assert r.formula_version == INACTIVE_FORMULA_VERSIONS[r.metric_code]
        assert r.as_of_date == date(2026, 9, 30) and r.computed_at == AT
        assert r.canonical_data_version and r.manual_adjustment_set == ("adj-1",)
        assert feed.watermark in r.input_refs
        assert m.grain == "TENANT_PERIOD"


def test_values_match_the_feed_and_statement_and_reasons_ride_in_exclusions():
    feed, statement = build(basis=None)
    by_code = {m.result.metric_code: m.result for m in mint(feed, statement) if m.target_ref == "tenant"}
    assert by_code["EXPENSE_TOTAL"].value_paise == feed.expense_total.value == 16_001
    assert by_code["UNALLOCATED_OVERHEAD"].value_paise == 9_001
    assert by_code["UNALLOCATED_OVERHEAD"].exclusions[0]["reason"] == "BASIS_NOT_SELECTED"
    assert by_code["EXPENSE_RECURRING_TOTAL"].value_paise == 9_001
    assert by_code["TOTAL_PROFIT"].value_paise == statement.total_profit.value


def test_per_category_and_per_cost_class_results_carry_their_target_ref():
    feed, statement = build()
    minted = mint(feed, statement)
    cats = {m.target_ref: m.result.value_paise for m in minted if m.result.metric_code == "EXPENSE_BY_CATEGORY"}
    assert cats == {"ads": 5_000, "rent": 9_001, "warehouse": 2_000}
    classes = {m.target_ref: m.result.value_paise for m in minted if m.result.metric_code == "EXPENSE_BY_COST_CLASS"}
    assert classes == {"ADVERTISING": 5_000, "OVERHEAD": 9_001, "STORAGE": 2_000}


def test_an_unavailable_statement_mints_unavailable_profit_results_never_a_number():
    feed, statement = build(cogs=Unavailable("COGS missing"))
    by_code = {m.result.metric_code: m.result for m in mint(feed, statement) if m.target_ref == "tenant"}
    for code in ("CONTRIBUTION_PROFIT", "FULLY_ALLOCATED_PROFIT", "TOTAL_PROFIT"):
        r = by_code[code]
        assert r.is_available is False and r.value_paise is None and "COGS missing" in (r.unavailable_reason or "")
    assert by_code["UNALLOCATED_OVERHEAD"].is_available is True  # the unallocated lines still report


def test_minting_is_deterministic_apart_from_the_result_ids():
    feed, statement = build()
    a, b = mint(feed, statement), mint(feed, statement)
    strip = lambda ms: [(m.result.metric_code, m.target_ref, m.result.value_paise, m.result.input_refs, m.result.canonical_data_version) for m in ms]
    assert strip(a) == strip(b)


def test_not_entered_classes_mint_no_pool_result_and_are_not_zero_filled():
    feed = ledger_feed([ev("o", 100, "OVERHEAD")], period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), channel_scope=None, catalog={})
    classes = {k for k in feed.by_cost_class}
    assert classes == {"OVERHEAD"}
    assert feed.pools["ADVERTISING"].total is None
