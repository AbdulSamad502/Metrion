"""`classify_and_rank_leaks` — cfo-agent.md §6.4, against synthetic `LeakExceptionInput`
fixtures (library logic only — see `cfo.leak.compose`'s own module docstring: these fixtures
are never real seller findings in this checkpoint).

Covers: ordering by claim-window urgency then amount (T7/T8/T9-style), `amount_paise` copied
unchanged from input (AC4), empty input -> empty output, and that no finding is fabricated for
a non-leak outcome (AC16/T14-style).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from calc_engine.formulas.leak import ReconciliationOutcome
from calc_engine.formulas.severity import SeverityConfigRow

from cfo.leak.classification import LeakCategory
from cfo.leak.compose import LeakExceptionInput, classify_and_rank_leaks

_AS_OF = date(2026, 9, 23)


def _config_rows() -> list[SeverityConfigRow]:
    return [
        SeverityConfigRow(metric="AMOUNT_PAISE", high_threshold=100_00, medium_threshold=10_00),
        SeverityConfigRow(metric="AGE_DAYS", high_threshold=60, medium_threshold=30),
        SeverityConfigRow(metric="WINDOW_DAYS_REMAINING", high_threshold=None, medium_threshold=None),
    ]


def _exception(
    *,
    exception_id: str,
    outcome: ReconciliationOutcome = ReconciliationOutcome.UNSETTLED_BEYOND_LAG,
    amount_paise: int = 5_000_00,
    claim_window_days: int | None = 30,
    age_days: int = 10,
    **kwargs: object,
) -> LeakExceptionInput:
    return LeakExceptionInput(
        exception_id=exception_id,
        engine_result_ref=f"ref-{exception_id}",
        marketplace="AMAZON",
        outcome=outcome,
        amount_paise=amount_paise,
        affected_line_count=1,
        first_observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        age_days=age_days,
        claim_window_days=claim_window_days,
        **kwargs,  # type: ignore[arg-type]
    )


def test_empty_input_returns_empty_output() -> None:
    result = classify_and_rank_leaks([], as_of_date=_AS_OF, config_rows=_config_rows())
    assert result == []


def test_amount_paise_copied_unchanged_from_input() -> None:
    """AC4: the composed finding's amount is never recomputed — it is the exact int the
    exception fixture supplied."""
    exc = _exception(exception_id="e1", amount_paise=123_456)
    [composed] = classify_and_rank_leaks([exc], as_of_date=_AS_OF, config_rows=_config_rows())
    assert composed.exception.amount_paise == 123_456
    assert composed.exception is exc


def test_non_leak_outcomes_produce_no_finding_at_all() -> None:
    """AC16/T14-style: a matched/within-lag exception is not merely dropped from ranking, it
    never reaches classification as a finding in the first place — no fabricated finding."""
    exceptions = [
        _exception(exception_id="matched", outcome=ReconciliationOutcome.MATCHED_EXACT),
        _exception(exception_id="within_tol", outcome=ReconciliationOutcome.MATCHED_WITHIN_TOLERANCE),
        _exception(exception_id="within_lag", outcome=ReconciliationOutcome.UNSETTLED_WITHIN_LAG),
    ]
    result = classify_and_rank_leaks(exceptions, as_of_date=_AS_OF, config_rows=_config_rows())
    assert result == []


def test_mixed_leak_and_non_leak_only_ranks_the_leaks() -> None:
    exceptions = [
        _exception(exception_id="matched", outcome=ReconciliationOutcome.MATCHED_EXACT),
        _exception(exception_id="real_leak", outcome=ReconciliationOutcome.ORPHAN_SETTLEMENT),
    ]
    result = classify_and_rank_leaks(exceptions, as_of_date=_AS_OF, config_rows=_config_rows())
    assert len(result) == 1
    assert result[0].exception.exception_id == "real_leak"
    assert result[0].leak_category == LeakCategory.UNEXPECTED_DEDUCTION


def test_ordering_expired_window_beats_open_window_regardless_of_amount() -> None:
    """T7-style: WINDOW_THEN_AMOUNT puts EXPIRED first even when its amount is smaller."""
    small_expired = _exception(exception_id="expired", amount_paise=100_00, claim_window_days=0)
    large_open = _exception(exception_id="open", amount_paise=999_999_00, claim_window_days=90)
    result = classify_and_rank_leaks(
        [large_open, small_expired], as_of_date=_AS_OF, config_rows=_config_rows()
    )
    assert [c.exception.exception_id for c in result] == ["expired", "open"]


def test_ordering_closing_soon_beats_open() -> None:
    """T8-style."""
    closing_soon = _exception(exception_id="closing_soon", amount_paise=100_00, claim_window_days=5)
    open_window = _exception(exception_id="open", amount_paise=999_999_00, claim_window_days=90)
    result = classify_and_rank_leaks(
        [open_window, closing_soon], as_of_date=_AS_OF, config_rows=_config_rows()
    )
    assert [c.exception.exception_id for c in result] == ["closing_soon", "open"]


def test_ordering_within_same_window_bucket_falls_back_to_amount_descending() -> None:
    """T9-style: two OPEN findings order by amount, larger first."""
    small = _exception(exception_id="small", amount_paise=500_00, claim_window_days=90)
    large = _exception(exception_id="large", amount_paise=5_000_00, claim_window_days=90)
    result = classify_and_rank_leaks([small, large], as_of_date=_AS_OF, config_rows=_config_rows())
    assert [c.exception.exception_id for c in result] == ["large", "small"]


def test_unknown_window_falls_back_to_amount_ordering() -> None:
    """§5.14.1: claim_window_days=None -> UNKNOWN bucket, ordered by amount within it."""
    small = _exception(exception_id="small", amount_paise=500_00, claim_window_days=None)
    large = _exception(exception_id="large", amount_paise=5_000_00, claim_window_days=None)
    result = classify_and_rank_leaks([small, large], as_of_date=_AS_OF, config_rows=_config_rows())
    assert [c.exception.exception_id for c in result] == ["large", "small"]
