"""`classify_leak_category` — cfo-agent.md §6.3/§6.4, PROVISIONAL mapping (Q12).

Exercises every `ReconciliationOutcome` the PROVISIONAL table in
`cfo.leak.classification` covers, including the outcome-context combinations that
disambiguate `VARIANCE_EXCEEDS_TOLERANCE`, and confirms `None` for the three
non-leak outcomes.
"""

from __future__ import annotations

import pytest
from calc_engine.formulas.leak import ReconciliationOutcome

from cfo.leak.classification import ExceptionContext, LeakCategory, classify_leak_category


@pytest.mark.parametrize(
    "outcome",
    [
        ReconciliationOutcome.MATCHED_EXACT,
        ReconciliationOutcome.MATCHED_WITHIN_TOLERANCE,
        ReconciliationOutcome.UNSETTLED_WITHIN_LAG,
    ],
)
def test_non_leak_outcomes_return_none(outcome: ReconciliationOutcome) -> None:
    assert classify_leak_category(ExceptionContext(outcome=outcome)) is None


def test_unsettled_beyond_lag_is_missing_settlement() -> None:
    ctx = ExceptionContext(outcome=ReconciliationOutcome.UNSETTLED_BEYOND_LAG)
    assert classify_leak_category(ctx) == LeakCategory.MISSING_SETTLEMENT


def test_orphan_settlement_is_unexpected_deduction() -> None:
    ctx = ExceptionContext(outcome=ReconciliationOutcome.ORPHAN_SETTLEMENT)
    assert classify_leak_category(ctx) == LeakCategory.UNEXPECTED_DEDUCTION


def test_duplicate_settlement_is_duplicate_deduction() -> None:
    ctx = ExceptionContext(outcome=ReconciliationOutcome.DUPLICATE_SETTLEMENT)
    assert classify_leak_category(ctx) == LeakCategory.DUPLICATE_DEDUCTION


def test_variance_return_linked_is_return_not_credited() -> None:
    ctx = ExceptionContext(
        outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE,
        is_return_linked=True,
        # is_return_linked takes priority even if the component also looks levy-bearing —
        # the classifier checks return-linkage first.
        is_levy_component=True,
    )
    assert classify_leak_category(ctx) == LeakCategory.RETURN_NOT_CREDITED


def test_variance_levy_component_is_tcs_tds_mismatch() -> None:
    ctx = ExceptionContext(
        outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE,
        is_levy_component=True,
    )
    assert classify_leak_category(ctx) == LeakCategory.TCS_TDS_MISMATCH


def test_variance_fee_settlement_higher_is_fee_overcharge() -> None:
    ctx = ExceptionContext(
        outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE,
        component_kind="FEE",
        variance_is_settlement_higher=True,
    )
    assert classify_leak_category(ctx) == LeakCategory.FEE_OVERCHARGE


def test_variance_fee_settlement_not_higher_is_short_settlement() -> None:
    ctx = ExceptionContext(
        outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE,
        component_kind="FEE",
        variance_is_settlement_higher=False,
    )
    assert classify_leak_category(ctx) == LeakCategory.SHORT_SETTLEMENT


def test_variance_non_fee_defaults_to_short_settlement() -> None:
    ctx = ExceptionContext(
        outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE,
        component_kind="CHARGE",
        variance_is_settlement_higher=None,
    )
    assert classify_leak_category(ctx) == LeakCategory.SHORT_SETTLEMENT


def test_all_seven_categories_are_reachable() -> None:
    """Guardrail: every §6.3 category has at least one context that produces it — if a
    future edit to the mapping drops a category's only path, this test catches it."""
    reachable: set[LeakCategory] = set()
    contexts = [
        ExceptionContext(outcome=ReconciliationOutcome.UNSETTLED_BEYOND_LAG),
        ExceptionContext(outcome=ReconciliationOutcome.ORPHAN_SETTLEMENT),
        ExceptionContext(outcome=ReconciliationOutcome.DUPLICATE_SETTLEMENT),
        ExceptionContext(outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE, is_return_linked=True),
        ExceptionContext(outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE, is_levy_component=True),
        ExceptionContext(
            outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE,
            component_kind="FEE",
            variance_is_settlement_higher=True,
        ),
        ExceptionContext(
            outcome=ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE,
            component_kind="FEE",
            variance_is_settlement_higher=False,
        ),
    ]
    for ctx in contexts:
        category = classify_leak_category(ctx)
        assert category is not None
        reachable.add(category)
    assert reachable == set(LeakCategory)
