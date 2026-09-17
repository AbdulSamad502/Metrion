"""Tests for the spec amendments in §D of the approved plan (Checkpoint 1) that aren't
already exercised by test_scenarios.py: cogs_per_unit's two accepted shapes, the
RTO/logistics-vs-ShippingLogistics exclusion, and the gst_slab_reference WARNING-only check.
Bearer resolution (discount_bearer_config) and canonical_data_version order-independence are
covered by test_scenarios.py (T3/T4) and test_versioning.py respectively.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest

from calc_engine.formulas.component_sum import sum_components
from calc_engine.formulas.cost_components import parse_cogs_per_unit_adjustment
from calc_engine.formulas.marketplace_fees import marketplace_fees
from calc_engine.formulas.net_realized_revenue import net_realized_revenue
from calc_engine.formulas.recognition import resolve_recognition_state
from calc_engine.formulas.tax_treatment import apply_fee_gst_treatment
from calc_engine.gst.slab_reference import GstSlabRow, check_rate_plausibility
from calc_engine.types import Paise, RecognitionState, ZERO

from tests.fixtures.canonical_builder import CanonicalDataBuilder


def test_cogs_per_unit_bare_scalar_shape_defaults_effective_from_to_created_at():
    created_at = date(2026, 6, 1)
    entry = parse_cogs_per_unit_adjustment(8_000, created_at)
    assert entry.amount_paise == Paise(8_000)
    assert entry.effective_from == created_at


def test_cogs_per_unit_extended_shape_uses_explicit_effective_from():
    entry = parse_cogs_per_unit_adjustment(
        {"amount_paise": 8_500, "effective_from": "2026-08-15"}, created_at=date(2026, 6, 1)
    )
    assert entry.amount_paise == Paise(8_500)
    assert entry.effective_from == date(2026, 8, 15)


def test_cogs_per_unit_extended_shape_missing_effective_from_defaults_to_created_at():
    created_at = date(2026, 6, 1)
    entry = parse_cogs_per_unit_adjustment({"amount_paise": 8_500}, created_at)
    assert entry.effective_from == created_at


def test_rto_line_logistics_excluded_from_shipping_logistics(empty_bearer_resolver):
    normal_line = CanonicalDataBuilder().gross(100_000).logistics("SHIPPING_CHARGE", 3_000).build()
    rto_line = (
        CanonicalDataBuilder()
        .gross(100_000)
        .rto(1, outcome="RECOVERED_SELLABLE")
        .logistics("SHIPPING_CHARGE", 6_000)
        .build()
    )

    shipping_logistics = sum_components(
        [normal_line, rto_line],
        component_codes=frozenset({"SHIPPING_CHARGE"}),
        exclude_rto_lines=True,
    )
    # only the normal line's charge counts; the RTO line's charge belongs to ReturnRTOLosses
    assert shipping_logistics == Paise(3_000)

    all_logistics_ignoring_rto_flag = sum_components(
        [normal_line, rto_line],
        component_codes=frozenset({"SHIPPING_CHARGE"}),
        exclude_rto_lines=False,
    )
    assert all_logistics_ignoring_rto_flag == Paise(9_000)  # proves exclude_rto_lines is doing the work


def test_gst_slab_reference_unmatched_rate_is_warning_never_error():
    slabs = [
        GstSlabRow(Fraction(18), "18% standard rate", effective_from=date(2025, 1, 1), effective_to=None),
        GstSlabRow(Fraction(5), "5% rate", effective_from=date(2025, 1, 1), effective_to=None),
    ]
    result = check_rate_plausibility(Fraction("12.5"), slabs, as_of=date(2026, 8, 15))
    assert result.matched is False
    assert result.severity == "WARNING"  # never ERROR — this check never blocks aggregation


def test_gst_slab_reference_matched_rate():
    slabs = [GstSlabRow(Fraction(18), "18% standard rate", effective_from=date(2025, 1, 1), effective_to=None)]
    result = check_rate_plausibility(Fraction(18), slabs, as_of=date(2026, 8, 15))
    assert result.matched is True


def test_gst_slab_reference_never_applied_retroactively_before_effective_from():
    slabs = [GstSlabRow(Fraction(18), "18% standard rate", effective_from=date(2026, 1, 1), effective_to=None)]
    # observed rate matches the slab's percentage, but the slab wasn't effective yet on this date
    result = check_rate_plausibility(Fraction(18), slabs, as_of=date(2025, 6, 1))
    assert result.matched is False
    assert result.severity == "WARNING"


def test_t16_quarantined_line_excluded_and_disclosed(empty_bearer_resolver):
    from dataclasses import replace

    good_line = CanonicalDataBuilder().gross(100_000).build()
    bad_line = replace(
        CanonicalDataBuilder().gross(50_000).build(),
        quarantine_rule_ids=("V-TAX-001",),
    )

    result = net_realized_revenue([good_line, bad_line], empty_bearer_resolver, RecognitionState.REALIZED)
    assert result.value == Paise(100_000)  # quarantined line's 50000 never enters the total
    assert len(result.exclusions) == 1
    assert result.exclusions[0]["rule"] == "QUARANTINED"
    assert result.exclusions[0]["quarantine_rule_ids"] == ("V-TAX-001",)


def test_t17_duplicate_fee_counted_once_and_flagged():
    # Amazon reference row: Platform Fee = Marketplace Fee Amount = ₹50 (A2/U1)
    line = (
        CanonicalDataBuilder()
        .marketplace("AMAZON")
        .gross(100_000)
        .fee("PLATFORM_FEE", 5_000)
        .fee("MARKETPLACE_FEE_AMOUNT", 5_000)
        .build()
    )
    total, flags = marketplace_fees(
        [line],
        fee_component_codes=frozenset({"PLATFORM_FEE", "MARKETPLACE_FEE_AMOUNT"}),
        duplicate_candidate_codes=frozenset({"PLATFORM_FEE", "MARKETPLACE_FEE_AMOUNT"}),
    )
    assert total == Paise(5_000)  # counted once, not 10000
    assert len(flags) == 1
    assert flags[0]["rule"] == "V-FEE-002"
    assert set(flags[0]["component_codes"]) == {"PLATFORM_FEE", "MARKETPLACE_FEE_AMOUNT"}


def test_t17_distinct_amounts_are_not_flagged_as_duplicates():
    line = (
        CanonicalDataBuilder()
        .marketplace("AMAZON")
        .gross(100_000)
        .fee("PLATFORM_FEE", 5_000)
        .fee("MARKETPLACE_FEE_AMOUNT", 7_000)
        .build()
    )
    total, flags = marketplace_fees(
        [line],
        fee_component_codes=frozenset({"PLATFORM_FEE", "MARKETPLACE_FEE_AMOUNT"}),
        duplicate_candidate_codes=frozenset({"PLATFORM_FEE", "MARKETPLACE_FEE_AMOUNT"}),
    )
    assert total == Paise(12_000)  # summed normally — different amounts are evidently distinct
    assert flags == ()


def test_t18_amazon_always_recognised_even_with_settlement_present():
    assert resolve_recognition_state("AMAZON", settlement_data_present=True) == RecognitionState.RECOGNISED
    assert resolve_recognition_state("AMAZON", settlement_data_present=False) == RecognitionState.RECOGNISED


def test_t18_meesho_realized_when_settlement_present():
    assert resolve_recognition_state("MEESHO", settlement_data_present=True) == RecognitionState.REALIZED
    assert resolve_recognition_state("MEESHO", settlement_data_present=False) == RecognitionState.RECOGNISED


def test_t18_ac12_enforced_even_if_caller_passes_wrong_value(empty_bearer_resolver):
    amazon_line = CanonicalDataBuilder().marketplace("AMAZON").gross(100_000).build()
    with pytest.raises(ValueError, match="AC12"):
        net_realized_revenue([amazon_line], empty_bearer_resolver, RecognitionState.REALIZED)


def test_t29_fee_gst_treatment_creditable_default_unchanged():
    disclosed, other_costs = apply_fee_gst_treatment(Paise(1_800), "CREDITABLE", Paise(5_000))
    assert disclosed == Paise(1_800)
    assert other_costs == Paise(5_000)


def test_t29_fee_gst_treatment_cost_reclassifies_into_other_allocated_costs():
    disclosed, other_costs = apply_fee_gst_treatment(Paise(1_800), "COST", Paise(5_000))
    assert disclosed == ZERO  # no longer shown as a separate "potentially creditable" line
    assert other_costs == Paise(6_800)  # 5000 + 1800, moved wholesale into OtherAllocatedCosts
