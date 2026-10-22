"""Consolidating advertising across marketplaces (docs/specs/cfo-phase3-scope.md 3b): unknown marketplaces are named and excluded, never summed as zero."""

from __future__ import annotations

from fractions import Fraction

from calc_engine.formulas.ad_spend import AdMarketplaceInput as I, AdSpendStatus as S, ad_ratios, consolidate_ads
from calc_engine.formulas.completeness import Completeness


def test_known_marketplaces_sum_exactly_and_ratios_follow() -> None:
    c = consolidate_ads([I("MEESHO", S.KNOWN_SPEND, 10_000, 40_000, 100_000), I("FLIPKART", S.KNOWN_SPEND, 5_000, 30_000, 50_000)])
    assert (c.spend_paise, c.attributed_sales_paise, c.total_sales_paise, c.status, c.completeness) == (15_000, 70_000, 150_000, S.KNOWN_SPEND, Completeness.COMPLETE)
    r = ad_ratios(status=c.status, spend_paise=c.spend_paise, attributed_sales_paise=c.attributed_sales_paise, total_sales_paise=c.total_sales_paise)
    assert (r.roas, r.acos, r.tacos) == (Fraction(14, 3), Fraction(3, 14), Fraction(1, 10))


def test_an_unknown_marketplace_is_named_and_excluded_and_the_total_is_partial_not_zero_filled() -> None:
    c = consolidate_ads([I("MEESHO", S.KNOWN_SPEND, 10_000, 40_000, 100_000), I("AMAZON", S.UNKNOWN, None, None, None, "no report")])
    assert c.included == ("MEESHO",) and c.excluded == (("AMAZON", "no report"),) and c.spend_paise == 10_000 and c.completeness is Completeness.PARTIAL


def test_a_verified_zero_counts_as_zero_but_only_because_it_was_verified() -> None:
    c = consolidate_ads([I("MEESHO", S.VERIFIED_ZERO, 0, None, 100_000), I("FLIPKART", S.VERIFIED_ZERO, 0, None, 50_000)])
    assert c.spend_paise == 0 and c.status is S.VERIFIED_ZERO and c.attributed_sales_paise is None and c.total_sales_paise == 150_000
    mixed = consolidate_ads([I("MEESHO", S.VERIFIED_ZERO, 0, None, 100_000), I("FLIPKART", S.KNOWN_SPEND, 5_000, 20_000, 50_000)])
    assert mixed.spend_paise == 5_000 and mixed.status is S.KNOWN_SPEND and mixed.attributed_sales_paise == 20_000


def test_attributed_sales_and_revenue_are_unknown_if_any_included_part_lacks_them() -> None:
    c = consolidate_ads([I("MEESHO", S.KNOWN_SPEND, 10_000, None, 100_000), I("FLIPKART", S.KNOWN_SPEND, 5_000, 30_000, None)])
    assert c.spend_paise == 15_000 and c.attributed_sales_paise is None and c.total_sales_paise is None  # never a sum over only the parts that happen to have it


def test_nothing_known_is_unavailable_with_the_worst_status() -> None:
    none = consolidate_ads([I("MEESHO", S.UNKNOWN, None, None, None, "x"), I("AMAZON", S.MISSING_COVERAGE, None, None, None, "gap")])
    assert none.spend_paise is None and none.completeness is Completeness.UNAVAILABLE and none.status is S.UNKNOWN and len(none.excluded) == 2
    gap = consolidate_ads([I("AMAZON", S.MISSING_COVERAGE, None, None, None, "gap")])
    assert gap.status is S.MISSING_COVERAGE
    assert consolidate_ads([]).status is S.UNKNOWN
