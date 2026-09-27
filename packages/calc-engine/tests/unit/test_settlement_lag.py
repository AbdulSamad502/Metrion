"""formulas/settlement_lag.py — anomaly-detection.md §6.1/§6.6's `SETTLEMENT_LAG_DAYS`
aggregate's pure formula (closing §10 P1)."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

from calc_engine.formulas.settlement_lag import SettlementLagAggregate, settlement_lag_days_aggregate
from calc_engine.types import Confidence, Unavailable


def _pair(
    *,
    order_date: date | None = None,
    invoice_date: date | None = None,
    dispatch_date: date | None = None,
    settlement_date: date | None,
    match_confidence: str = "VERIFIED",
) -> dict:
    return {
        "invoice_date": invoice_date,
        "dispatch_date": dispatch_date,
        "order_date": order_date,
        "settlement_date": settlement_date,
        "match_confidence": match_confidence,
    }


def test_empty_pairs_is_unavailable_never_a_fabricated_zero_day_mean():
    result = settlement_lag_days_aggregate([])
    assert isinstance(result, Unavailable)


def test_happy_path_mean_over_multiple_pairs():
    pairs = [
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 11)),  # 10 days
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 21)),  # 20 days
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 31)),  # 30 days
    ]
    result = settlement_lag_days_aggregate(pairs)

    assert isinstance(result, SettlementLagAggregate)
    assert result.mean_lag_days == Fraction(60, 3)
    assert result.pair_count == 3
    assert result.dates_missing_count == 0
    assert result.negative_lag_excluded_count == 0
    assert isinstance(result.mean_lag_days, Fraction)


def test_negative_lag_is_excluded_and_counted_not_included_as_is():
    pairs = [
        _pair(order_date=date(2026, 1, 20), settlement_date=date(2026, 1, 10)),  # -10 days, excluded
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 11)),  # 10 days, kept
    ]
    result = settlement_lag_days_aggregate(pairs)

    assert isinstance(result, SettlementLagAggregate)
    assert result.mean_lag_days == Fraction(10)
    assert result.pair_count == 1
    assert result.negative_lag_excluded_count == 1


def test_every_pair_negative_is_unavailable():
    pairs = [_pair(order_date=date(2026, 1, 20), settlement_date=date(2026, 1, 10))]
    result = settlement_lag_days_aggregate(pairs)
    assert isinstance(result, Unavailable)


def test_pair_with_no_resolvable_sales_date_is_skipped_and_counted_never_crashed_on():
    pairs = [
        _pair(settlement_date=date(2026, 1, 11)),  # all three sales dates None
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 11)),  # kept, 10 days
    ]
    result = settlement_lag_days_aggregate(pairs)

    assert isinstance(result, SettlementLagAggregate)
    assert result.pair_count == 1
    assert result.dates_missing_count == 1
    assert result.mean_lag_days == Fraction(10)


def test_pair_with_null_settlement_date_is_skipped_defensively():
    pairs = [_pair(order_date=date(2026, 1, 1), settlement_date=None)]
    result = settlement_lag_days_aggregate(pairs)
    assert isinstance(result, Unavailable)


def test_invoice_date_preferred_over_dispatch_and_order_per_resolve_document_date():
    pairs = [
        _pair(
            invoice_date=date(2026, 1, 5),
            dispatch_date=date(2026, 1, 1),
            order_date=date(2026, 1, 1),
            settlement_date=date(2026, 1, 15),
        )
    ]
    result = settlement_lag_days_aggregate(pairs)
    assert isinstance(result, SettlementLagAggregate)
    # resolved sales date = invoice_date (Jan 5) -> lag = 10 days, not 14
    assert result.mean_lag_days == Fraction(10)


def test_confidence_carried_through_per_pair_never_dropped():
    pairs = [
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 11), match_confidence="VERIFIED"),
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 11), match_confidence="PROVISIONAL"),
    ]
    result = settlement_lag_days_aggregate(pairs)
    assert isinstance(result, SettlementLagAggregate)
    assert result.confidences == (Confidence.VERIFIED, Confidence.PROVISIONAL)


def test_zero_lag_same_day_settlement_is_a_legitimate_value():
    pairs = [_pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 1))]
    result = settlement_lag_days_aggregate(pairs)
    assert isinstance(result, SettlementLagAggregate)
    assert result.mean_lag_days == Fraction(0)
    assert result.pair_count == 1


def test_never_a_float_anywhere():
    pairs = [
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 11)),
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 12)),
        _pair(order_date=date(2026, 1, 1), settlement_date=date(2026, 1, 13)),
    ]
    result = settlement_lag_days_aggregate(pairs)
    assert isinstance(result, SettlementLagAggregate)
    assert isinstance(result.mean_lag_days, Fraction)
    assert not isinstance(result.mean_lag_days, float)
