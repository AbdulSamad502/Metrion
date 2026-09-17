"""Concrete tests for deterministic-engine.md §13 scenarios T1, T2, T3, T4, T7, T8, T9, T10,
T12, T13, T14, T15, T21, T22 — the scenarios covered by the formulas implemented in this pass.

Deferred to a later batch (need DB-backed manual_adjustment/config repos, or nuances not yet
modeled — e.g. T11's "cancelled after dispatch retains forward logistics"): T5, T6, T11,
T16-T20, T23-T30.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

from calc_engine.formulas.component_sum import sum_components
from calc_engine.formulas.contribution_profit import contribution_margin_pct, contribution_profit
from calc_engine.formulas.cost_components import CostEntry, billable_quantity, cogs, weighted_average_cost
from calc_engine.formulas.discount_attribution import marketplace_funded_discounts
from calc_engine.formulas.net_realized_revenue import net_realized_revenue
from calc_engine.formulas.return_rto_losses import return_rto_losses
from calc_engine.types import Bearer, Confidence, Paise, RecognitionState, Unavailable, ZERO

from tests.conftest import make_bearer_resolver
from tests.fixtures.canonical_builder import CanonicalDataBuilder


def test_t1_clean_prepaid_no_discount(empty_bearer_resolver):
    line = CanonicalDataBuilder().gross(100_000).build()
    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(100_000)
    assert result.confidence == Confidence.PROVISIONAL


def test_t2_seller_funded_discount(empty_bearer_resolver):
    line = CanonicalDataBuilder().gross(100_000).discount("SELLER_DISCOUNT", 50_000).build()
    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(50_000)


def test_t3_marketplace_funded_discount_unchanged():
    resolver = make_bearer_resolver({("MEESHO", "PLATFORM_DISCOUNT"): Bearer.MARKETPLACE})
    line = CanonicalDataBuilder().gross(100_000).discount("PLATFORM_DISCOUNT", 50_000).build()

    result = net_realized_revenue([line], resolver, RecognitionState.REALIZED)
    assert result.value == Paise(100_000)  # AC4: unchanged

    disclosed = marketplace_funded_discounts([line], resolver)
    assert disclosed == Paise(50_000)  # disclosed separately, never subtracted


def test_t4_unknown_bearer_treated_as_seller_and_flagged_derived(empty_bearer_resolver):
    # empty_bearer_resolver has no mapping at all -> falls to Bearer.UNKNOWN (D2 default)
    line = CanonicalDataBuilder().gross(100_000).discount("PLATFORM_DISCOUNT", 50_000).build()
    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(50_000)  # treated seller-borne
    assert result.confidence == Confidence.DERIVED  # flagged, per D2/E13


def test_t5_seller_overrides_bearer_to_marketplace():
    # T4 treated PLATFORM_DISCOUNT as seller-borne under an empty resolver (UNKNOWN -> SELLER).
    # T5: the seller overrides that bearer to MARKETPLACE. The override mechanism is the
    # bearer_resolver itself — a manual_adjustment(discount_bearer) is what would populate a
    # discount_bearer_config row in production, but the formula layer only ever sees the
    # resolved bearer, never the adjustment record, so simulating the override here is a
    # faithful test of this layer without needing a real manual_adjustment_repo (§7.1, AC6).
    line = CanonicalDataBuilder().gross(100_000).discount("PLATFORM_DISCOUNT", 50_000).build()
    original_amount = next(c.amount for c in line.components if c.component_code == "PLATFORM_DISCOUNT")

    overridden_resolver = make_bearer_resolver({("MEESHO", "PLATFORM_DISCOUNT"): Bearer.MARKETPLACE})
    result = net_realized_revenue([line], overridden_resolver, RecognitionState.REALIZED)

    assert result.value == Paise(100_000)  # revenue increases back to the full gross amount
    # the source component's own amount is untouched — the override lives in the resolver,
    # never in the canonical row (AC6: source data byte-identical before/after adjustment)
    assert original_amount == Paise(50_000)
    assert next(c.amount for c in line.components if c.component_code == "PLATFORM_DISCOUNT") == Paise(50_000)


def test_t6_full_return_refund_settled_releases_cogs(empty_bearer_resolver):
    line = CanonicalDataBuilder().quantity(1).gross(100_000).returned(1, refunded_amount_paise=100_000).build()

    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(0)  # revenue fully reversed in the original period

    assert billable_quantity(line) == 0  # inventory sellable -> COGS released, not consumed
    assert cogs(line, Paise(8_000)) == Paise(0)


def test_t11_cancelled_after_dispatch_forward_logistics_retained_cogs_unavailable_until_classified(empty_bearer_resolver):
    line = (
        CanonicalDataBuilder()
        .gross(100_000)
        .dispatched_on(date(2026, 8, 18))
        .cancelled()
        .logistics("SHIPPING_CHARGE", 4_000)
        .build()
    )

    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(0)  # revenue still reversed (E15)

    # forward logistics is retained as a cost: a cancelled line is never excluded from
    # ShippingLogistics by exclude_rto_lines (only actual RETURNED/RTO lines are)
    shipping = sum_components([line], component_codes=frozenset({"SHIPPING_CHARGE"}), exclude_rto_lines=True)
    assert shipping == Paise(4_000)

    # but COGS cannot be guessed without knowing whether the dispatched goods came back —
    # UNAVAILABLE, not a silent assumption of "recovered" or "lost"
    unclassified_cost = billable_quantity(line)
    assert isinstance(unclassified_cost, Unavailable)

    # once classified, it resolves like an RTO outcome would
    line_recovered = (
        CanonicalDataBuilder()
        .gross(100_000)
        .dispatched_on(date(2026, 8, 18))
        .cancelled()
        .rto(0, outcome="RECOVERED_SELLABLE")  # rto_qty irrelevant here; only rto_outcome is consulted for cancellation
        .build()
    )
    assert billable_quantity(line_recovered) == 0


def test_t7_partial_return_prorated(empty_bearer_resolver):
    line = CanonicalDataBuilder().quantity(5).gross(100_000).returned(2, refunded_amount_paise=40_000).build()

    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(60_000)  # 100000 - 40000

    assert billable_quantity(line) == 3  # 5 - 2


def test_t8_rto_recovered_sellable(empty_bearer_resolver):
    line = CanonicalDataBuilder().gross(100_000).rto(1, outcome="RECOVERED_SELLABLE").build()

    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(0)  # fully unrecovered revenue

    assert billable_quantity(line) == 0  # RTO'd unit excluded regardless of outcome
    cogs_value = cogs(line, Paise(8_000))
    assert cogs_value == Paise(0)  # goods intact -> no cost consumed

    losses = return_rto_losses(
        line,
        unit_cost=Paise(8_000),
        forward_logistics=Paise(6_000),
        reverse_logistics=Paise(6_000),
        non_refunded_fees_retained=ZERO,
    )
    assert losses == Paise(12_000)  # 0 COGS + 6000 + 6000 + 0


def test_t9_rto_damaged(empty_bearer_resolver):
    line = CanonicalDataBuilder().gross(100_000).rto(1, outcome="RECOVERED_DAMAGED").build()

    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(0)

    assert billable_quantity(line) == 0  # excluded from ordinary COGS (the §5.6 fix)
    assert cogs(line, Paise(8_000)) == Paise(0)

    losses = return_rto_losses(
        line,
        unit_cost=Paise(8_000),
        forward_logistics=Paise(6_000),
        reverse_logistics=Paise(6_000),
        non_refunded_fees_retained=ZERO,
    )
    # damaged unit's cost appears exactly once, here, never also in ordinary COGS
    assert losses == Paise(8_000 + 6_000 + 6_000)


def test_t10a_meesho_cancelled_before_dispatch(empty_bearer_resolver):
    line = CanonicalDataBuilder().marketplace("MEESHO").gross(100_000).cancelled().build()

    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(0)
    assert billable_quantity(line) == 0  # no COGS consumed


def test_t10b_amazon_unresolved_cancellation_is_unavailable(empty_bearer_resolver):
    line = CanonicalDataBuilder().marketplace("AMAZON").gross(100_000).unresolved_cancellation().build()

    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.RECOGNISED)
    # the whole line is excluded and disclosed, never silently treated as "not cancelled"
    assert isinstance(result, Unavailable) or (
        len(result.exclusions) == 1 and result.exclusions[0]["rule"] == "REVENUE_STATUS_UNRESOLVED"
    )


def test_t12_missing_cogs_makes_contribution_profit_unavailable_not_revenue(empty_bearer_resolver):
    line = CanonicalDataBuilder().gross(100_000).build()
    nrr = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert nrr.value == Paise(100_000)  # NRR still reported (E9)

    unit_cost = weighted_average_cost("SKU-1", date(2026, 8, 15), cost_history=[])
    assert isinstance(unit_cost, Unavailable)

    cp = contribution_profit(
        net_realized_revenue=nrr.value,
        cogs=cogs(line, unit_cost),
        marketplace_fees=ZERO,
        shipping_logistics=ZERO,
        advertising_costs=ZERO,
        return_rto_losses=ZERO,
        other_allocated_costs=ZERO,
    )
    assert isinstance(cp, Unavailable)  # ContributionProfit UNAVAILABLE, not a number


def test_t13_weighted_average_cost_as_of_document_date():
    history = [
        CostEntry(Paise(8_000), date(2026, 8, 1)),
        CostEntry(Paise(8_500), date(2026, 8, 15)),
    ]
    line_a_cost = weighted_average_cost("SKU-1", date(2026, 8, 10), history)
    line_b_cost = weighted_average_cost("SKU-1", date(2026, 8, 20), history)
    assert line_a_cost == Paise(8_000)
    assert line_b_cost == Paise(8_500)


def test_t14_allocation_largest_remainder_sums_exactly():
    from calc_engine.formulas.allocation import AllocationBasis, allocate_pool

    weights = [("SKU-A", Fraction(1)), ("SKU-B", Fraction(1)), ("SKU-C", Fraction(1))]
    result = allocate_pool(Paise(10), weights, AllocationBasis.NET_REVENUE)

    assert result == {"SKU-A": Paise(4), "SKU-B": Paise(3), "SKU-C": Paise(3)}
    assert sum(p.value for p in result.values()) == 10  # AC7


def test_t15_ad_spend_zero_net_revenue_reported_unallocated():
    from calc_engine.formulas.allocation import AllocationBasis, allocate_pool

    weights = [("SKU-A", Fraction(0)), ("SKU-B", Fraction(0))]
    result = allocate_pool(Paise(10_000), weights, AllocationBasis.NET_REVENUE)

    assert result == {"SKU-A": Paise(0), "SKU-B": Paise(0)}  # unallocated, not dropped


def test_t21_returns_exceed_sales_negative_not_floored(empty_bearer_resolver):
    line = CanonicalDataBuilder().gross(50_000).returned(1, refunded_amount_paise=80_000).build()
    result = net_realized_revenue([line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(-30_000)  # negative, reported as-is (E7)


def test_t22_zero_net_revenue_margin_is_undefined_string():
    margin = contribution_margin_pct(Paise(5_000), ZERO)
    assert margin == "UNDEFINED"
    assert margin != 0  # never the number zero
