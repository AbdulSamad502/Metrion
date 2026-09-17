"""severity.py — rank_findings, window_status, severity combination (deterministic-engine.md
§5.13.1, §5.14.1, confirmed 'worst dimension wins' amendment).
"""

from __future__ import annotations

from datetime import date

from calc_engine.formulas.severity import (
    Finding,
    SeverityBand,
    SeverityConfigRow,
    WindowStatus,
    finding_severity,
    rank_findings,
    window_status,
)
from calc_engine.types import Unavailable

AS_OF = date(2026, 9, 17)


def test_window_status_expired():
    assert window_status(claim_window_days=0, closing_soon_days=14) == WindowStatus.EXPIRED
    assert window_status(claim_window_days=-3, closing_soon_days=14) == WindowStatus.EXPIRED


def test_window_status_closing_soon():
    assert window_status(claim_window_days=10, closing_soon_days=14) == WindowStatus.CLOSING_SOON


def test_window_status_open():
    assert window_status(claim_window_days=30, closing_soon_days=14) == WindowStatus.OPEN


def test_window_status_unknown_when_no_claim_window():
    assert window_status(claim_window_days=None, closing_soon_days=14) == WindowStatus.UNKNOWN


def test_finding_severity_worst_dimension_wins():
    # AMOUNT_PAISE says LOW, AGE_DAYS says HIGH -> overall HIGH
    finding = Finding(exception_id="e1", amount_paise=100, age_days=100, claim_window_days=None)
    config = [
        SeverityConfigRow(metric="AMOUNT_PAISE", high_threshold=100_000, medium_threshold=10_000),
        SeverityConfigRow(metric="AGE_DAYS", high_threshold=60, medium_threshold=30),
    ]
    result = finding_severity(finding, as_of_date=AS_OF, config_rows=config)
    assert result == SeverityBand.HIGH


def test_finding_severity_skips_metric_with_no_applicable_data():
    # WINDOW_DAYS_REMAINING config exists but this finding has no claim window at all
    finding = Finding(exception_id="e1", amount_paise=5_000, age_days=5, claim_window_days=None)
    config = [
        SeverityConfigRow(metric="AMOUNT_PAISE", high_threshold=100_000, medium_threshold=1_000),
        SeverityConfigRow(metric="WINDOW_DAYS_REMAINING", high_threshold=None, medium_threshold=3),
    ]
    result = finding_severity(finding, as_of_date=AS_OF, config_rows=config)
    assert result == SeverityBand.MEDIUM  # only AMOUNT_PAISE applied


def test_finding_severity_unavailable_when_no_metric_applies():
    finding = Finding(exception_id="e1", amount_paise=5_000, age_days=5, claim_window_days=None)
    result = finding_severity(finding, as_of_date=AS_OF, config_rows=[])
    assert isinstance(result, Unavailable)


def test_rank_findings_window_then_amount_orders_expired_first():
    findings = [
        Finding(exception_id="a", amount_paise=1_000, age_days=1, claim_window_days=30),  # OPEN
        Finding(exception_id="b", amount_paise=500, age_days=1, claim_window_days=0),      # EXPIRED
        Finding(exception_id="c", amount_paise=2_000, age_days=1, claim_window_days=10),   # CLOSING_SOON
    ]
    ranked = rank_findings(findings, as_of_date=AS_OF, config_rows=[], ordering_basis="WINDOW_THEN_AMOUNT")
    assert [item[0].exception_id for item in ranked] == ["b", "c", "a"]


def test_rank_findings_amount_only_ignores_window():
    findings = [
        Finding(exception_id="a", amount_paise=1_000, age_days=1, claim_window_days=30),
        Finding(exception_id="b", amount_paise=5_000, age_days=1, claim_window_days=0),
        Finding(exception_id="c", amount_paise=2_000, age_days=1, claim_window_days=10),
    ]
    ranked = rank_findings(findings, as_of_date=AS_OF, config_rows=[], ordering_basis="AMOUNT_ONLY")
    assert [item[0].exception_id for item in ranked] == ["b", "c", "a"]


def test_rank_findings_no_claim_window_falls_back_to_amount_within_unknown_bucket():
    findings = [
        Finding(exception_id="a", amount_paise=1_000, age_days=1, claim_window_days=None),
        Finding(exception_id="b", amount_paise=5_000, age_days=1, claim_window_days=None),
    ]
    ranked = rank_findings(findings, as_of_date=AS_OF, config_rows=[], ordering_basis="WINDOW_THEN_AMOUNT")
    assert [item[0].exception_id for item in ranked] == ["b", "a"]


def test_rank_findings_ties_broken_by_exception_id_not_insertion_order():
    findings = [
        Finding(exception_id="z", amount_paise=1_000, age_days=1, claim_window_days=None),
        Finding(exception_id="a", amount_paise=1_000, age_days=1, claim_window_days=None),
    ]
    ranked = rank_findings(findings, as_of_date=AS_OF, config_rows=[], ordering_basis="AMOUNT_ONLY")
    assert [item[0].exception_id for item in ranked] == ["a", "z"]
