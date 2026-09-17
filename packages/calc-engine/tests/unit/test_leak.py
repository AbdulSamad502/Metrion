"""leak.py — deterministic-engine.md §5.12.1, data-foundation.md §5.

T19: Meesho line, Settlement Commission > Commission Fee — delta surfaced as a leak candidate.
"""

from __future__ import annotations

from datetime import date

import pytest

from calc_engine.formulas.leak import (
    ReconciliationOutcome,
    classify_settlement_lag,
    classify_variance,
    is_within_tolerance,
    leak_aggregate,
    leak_amount,
    resolve_tolerance_or_unavailable,
    should_report_unsettled_as_leak,
)
from calc_engine.types import Paise, Unavailable


def test_leak_amount_is_settlement_minus_invoice():
    # T19: invoice-side Commission Fee ₹50, settlement-side Settlement Commission ₹65
    assert leak_amount(Paise(5_000), Paise(6_500)) == Paise(1_500)


def test_leak_amount_negative_when_settlement_pays_less():
    assert leak_amount(Paise(5_000), Paise(4_000)) == Paise(-1_000)


def test_is_within_tolerance_paise_side():
    # variance 10 paise, paise tolerance 20, bps tolerance 0 -> within via paise
    assert is_within_tolerance(Paise(10), Paise(100_000), tolerance_paise=Paise(20), tolerance_bps=0) is True


def test_is_within_tolerance_bps_side():
    # invoice ₹1000 (100000 paise), 1% (100 bps) = 1000 paise tolerance; variance 900 paise
    assert is_within_tolerance(Paise(900), Paise(100_000), tolerance_paise=Paise(0), tolerance_bps=100) is True


def test_is_within_tolerance_fails_both():
    assert is_within_tolerance(Paise(5_000), Paise(100_000), tolerance_paise=Paise(10), tolerance_bps=1) is False


def test_classify_variance_matched_exact():
    result = classify_variance(Paise(5_000), Paise(5_000), tolerance_paise=Paise(0), tolerance_bps=0)
    assert result == ReconciliationOutcome.MATCHED_EXACT


def test_classify_variance_within_tolerance():
    result = classify_variance(Paise(5_000), Paise(5_010), tolerance_paise=Paise(20), tolerance_bps=0)
    assert result == ReconciliationOutcome.MATCHED_WITHIN_TOLERANCE


def test_t19_exceeds_tolerance_is_a_leak_candidate():
    # T19 exact numbers: Commission Fee ₹50 (5000 paise) vs Settlement Commission ₹65 (6500 paise)
    result = classify_variance(Paise(5_000), Paise(6_500), tolerance_paise=Paise(50), tolerance_bps=10)
    assert result == ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE


def test_classify_settlement_lag_within():
    result = classify_settlement_lag(document_date=date(2026, 9, 1), as_of_date=date(2026, 9, 10), settlement_lag_days=14)
    assert result == ReconciliationOutcome.UNSETTLED_WITHIN_LAG


def test_classify_settlement_lag_beyond():
    result = classify_settlement_lag(document_date=date(2026, 9, 1), as_of_date=date(2026, 9, 20), settlement_lag_days=14)
    assert result == ReconciliationOutcome.UNSETTLED_BEYOND_LAG


def test_should_report_unsettled_as_leak_only_after_lag_plus_grace():
    # 16 days elapsed: beyond 14-day lag, but within the 5-day grace on top of it
    assert should_report_unsettled_as_leak(
        document_date=date(2026, 9, 1), as_of_date=date(2026, 9, 17), settlement_lag_days=14, grace_period_days=5
    ) is False
    # 20 days elapsed: beyond lag + grace (14 + 5 = 19)
    assert should_report_unsettled_as_leak(
        document_date=date(2026, 9, 1), as_of_date=date(2026, 9, 21), settlement_lag_days=14, grace_period_days=5
    ) is True


def test_leak_aggregate_sums_exception_amounts():
    assert leak_aggregate([Paise(1_500), Paise(-1_000), Paise(200)]) == Paise(700)


def test_leak_aggregate_empty_is_zero():
    assert leak_aggregate([]) == Paise(0)


def test_resolve_tolerance_or_unavailable_missing_row_is_unavailable():
    result = resolve_tolerance_or_unavailable(None)
    assert isinstance(result, Unavailable)
    assert result.missing_inputs == ("reconciliation_tolerance_config",)


def test_resolve_tolerance_or_unavailable_present_row():
    row = {"tolerance_paise": 50, "tolerance_bps": 10, "settlement_lag_days": 14, "grace_period_days": 5}
    result = resolve_tolerance_or_unavailable(row)
    assert result == (Paise(50), 10)
