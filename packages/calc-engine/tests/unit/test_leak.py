"""leak.py — deterministic-engine.md §5.12.1, data-foundation.md §5.

T19: Meesho line, Settlement Commission > Commission Fee — delta surfaced as a leak candidate.
"""

from __future__ import annotations

from datetime import date

import pytest

from calc_engine.formulas.leak import (
    Collision,
    NoCandidate,
    ReconciliationOutcome,
    SingleMatch,
    classify_settlement_lag,
    classify_variance,
    is_duplicate_settlement,
    is_within_tolerance,
    leak_aggregate,
    leak_amount,
    resolve_match_candidates,
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


# --- resolve_match_candidates (§5.2 C3 collision handling) ---------------------------------


def test_resolve_match_candidates_zero_is_no_candidate():
    result = resolve_match_candidates([])
    assert isinstance(result, NoCandidate)


def test_resolve_match_candidates_one_is_single_match():
    candidate = {"sales_line_id": "abc", "order_ref": "SUB1"}
    result = resolve_match_candidates([candidate])
    assert isinstance(result, SingleMatch)
    assert result.candidate == candidate


def test_resolve_match_candidates_two_or_more_is_collision():
    candidate_a = {"sales_line_id": "abc", "order_ref": "SUB1"}
    candidate_b = {"sales_line_id": "def", "order_ref": "SUB1"}
    result = resolve_match_candidates([candidate_a, candidate_b])
    assert isinstance(result, Collision)
    assert result.candidates == (candidate_a, candidate_b)


def test_resolve_match_candidates_three_candidates_is_still_a_single_collision():
    candidates = [
        {"sales_line_id": "a"},
        {"sales_line_id": "b"},
        {"sales_line_id": "c"},
    ]
    result = resolve_match_candidates(candidates)
    assert isinstance(result, Collision)
    assert len(result.candidates) == 3


# --- is_duplicate_settlement (§5.2 C4 duplicate detection) ---------------------------------


def test_is_duplicate_settlement_all_three_match():
    candidate = {
        "order_ref": "SUB1",
        "line_ref": None,
        "gross_settlement_amount": 6_500,
        "settlement_date": date(2026, 9, 10),
    }
    already_processed = [
        {
            "order_ref": "SUB1",
            "line_ref": None,
            "gross_settlement_amount": 6_500,
            "settlement_date": date(2026, 9, 10),
        }
    ]
    assert is_duplicate_settlement(candidate, already_processed) is True


def test_is_duplicate_settlement_different_amount_is_not_a_duplicate():
    candidate = {
        "order_ref": "SUB1",
        "line_ref": None,
        "gross_settlement_amount": 6_500,
        "settlement_date": date(2026, 9, 10),
    }
    already_processed = [
        {
            "order_ref": "SUB1",
            "line_ref": None,
            "gross_settlement_amount": 7_000,
            "settlement_date": date(2026, 9, 10),
        }
    ]
    assert is_duplicate_settlement(candidate, already_processed) is False


def test_is_duplicate_settlement_different_date_is_not_a_duplicate():
    # A genuine second, distinct charge on a different date must never be flagged (§5.2).
    candidate = {
        "order_ref": "SUB1",
        "line_ref": None,
        "gross_settlement_amount": 6_500,
        "settlement_date": date(2026, 9, 10),
    }
    already_processed = [
        {
            "order_ref": "SUB1",
            "line_ref": None,
            "gross_settlement_amount": 6_500,
            "settlement_date": date(2026, 10, 1),
        }
    ]
    assert is_duplicate_settlement(candidate, already_processed) is False


def test_is_duplicate_settlement_different_join_key_is_not_a_duplicate():
    candidate = {
        "order_ref": "SUB1",
        "line_ref": None,
        "gross_settlement_amount": 6_500,
        "settlement_date": date(2026, 9, 10),
    }
    already_processed = [
        {
            "order_ref": "SUB2",
            "line_ref": None,
            "gross_settlement_amount": 6_500,
            "settlement_date": date(2026, 9, 10),
        }
    ]
    assert is_duplicate_settlement(candidate, already_processed) is False


def test_is_duplicate_settlement_empty_history_is_not_a_duplicate():
    candidate = {
        "order_ref": "SUB1",
        "line_ref": None,
        "gross_settlement_amount": 6_500,
        "settlement_date": date(2026, 9, 10),
    }
    assert is_duplicate_settlement(candidate, []) is False


# --- is_duplicate_settlement None-amount hardening (data-foundation.md §5.1.5 point 4,
# deterministic-engine.md §5.2 amendment) -----------------------------------------------------


def test_is_duplicate_settlement_none_amount_never_a_duplicate_even_with_same_key_and_date():
    """The bug this closes: unmodified, `None == None` compares equal in Python, so two Amazon
    rows sharing the same order_ref/settlement_date (both with a None gross_settlement_amount,
    since amazon.settlement.v2 never populates it) would wrongly be flagged
    DUPLICATE_SETTLEMENT. An unavailable amount is never "the same amount" as another
    unavailable amount — this must return False, not True."""
    candidate = {
        "order_ref": "AMZ-ORDER-1",
        "line_ref": None,
        "gross_settlement_amount": None,
        "settlement_date": date(2026, 9, 10),
    }
    already_processed = [
        {
            "order_ref": "AMZ-ORDER-1",
            "line_ref": None,
            "gross_settlement_amount": None,
            "settlement_date": date(2026, 9, 10),
        }
    ]
    assert is_duplicate_settlement(candidate, already_processed) is False


def test_is_duplicate_settlement_real_equal_amount_still_correctly_a_duplicate():
    """Regression protection: the None-amount guard must not break the real, genuinely-equal-
    amount case it doesn't apply to (Flipkart/Meesho, whose gross_settlement_amount is real)."""
    candidate = {
        "order_ref": "FK-ORDER-1",
        "line_ref": None,
        "gross_settlement_amount": 6_500,
        "settlement_date": date(2026, 9, 10),
    }
    already_processed = [
        {
            "order_ref": "FK-ORDER-1",
            "line_ref": None,
            "gross_settlement_amount": 6_500,
            "settlement_date": date(2026, 9, 10),
        }
    ]
    assert is_duplicate_settlement(candidate, already_processed) is True
