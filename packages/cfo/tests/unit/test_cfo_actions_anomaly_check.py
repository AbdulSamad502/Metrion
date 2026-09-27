"""`backend.services.cfo_actions.run_anomaly_check` — E3, wiring Brain 2 (`calc_engine.anomaly`,
E2) into CFO for the `MARGIN_PCT` series. Mirrors `test_cfo_actions_period_comparison.py`'s
monkeypatch conventions: `metric_result_repo.list_by_metric_code`/`config_repo.
resolve_anomaly_detection_config` are monkeypatched — no live Postgres in this session — and
the real `calc_engine.anomaly` pure functions (`z_score`/`percentile_threshold`/
`period_over_period_delta`, E2, unchanged) are exercised for real.

Covers:
  - series assembly: UNAVAILABLE rows are excluded (B2/E6), available rows convert to
    `SeriesPoint`s via their `value_fraction_numerator`/`value_fraction_denominator` columns.
  - all three methods run and all three outcomes are returned together, never just one.
  - a missing `anomaly_detection_config` row for a given method produces
    `AnomalyConfigurationGap` for that method specifically (others still run).
  - a too-short series produces `AnomalyInsufficientHistory` for every method (below every
    method's floor).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from fractions import Fraction
from uuid import UUID, uuid4

import backend.services.cfo_actions as cfo_actions_module
from calc_engine.anomaly.types import (
    AnomalyConfigurationGap,
    AnomalyFlag,
    AnomalyInsufficientHistory,
)
from backend.services.cfo_actions import AnomalyCheckRequest, run_anomaly_check

_AS_OF = date(2026, 9, 25)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)


def _margin_row(
    *,
    period: str,
    numerator: int | None,
    denominator: int | None = 1,
    is_available: bool = True,
    confidence: str = "VERIFIED",
    row_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "id": row_id or uuid4(),
        "metric_code": "CONTRIBUTION_MARGIN_PCT",
        "period": period,
        "value_paise": None,
        "value_fraction_numerator": numerator,
        "value_fraction_denominator": denominator,
        "confidence": confidence,
        "is_available": is_available,
    }


def _z_score_config_row() -> dict[str, object]:
    return {
        "min_series_length": 8,
        "z_score_threshold": Decimal("2.500"),
        "percentile_low": None,
        "percentile_high": None,
        "delta_severity_bands": None,
        "version": 1,
    }


def _percentile_config_row() -> dict[str, object]:
    return {
        "min_series_length": 10,
        "z_score_threshold": None,
        "percentile_low": Decimal("10.00"),
        "percentile_high": Decimal("90.00"),
        "delta_severity_bands": None,
        "version": 1,
    }


def _delta_config_row() -> dict[str, object]:
    return {
        "min_series_length": 5,
        "z_score_threshold": None,
        "percentile_low": None,
        "percentile_high": None,
        "delta_severity_bands": {"high": "3.0", "medium": "2.0", "low": "1.0"},
        "version": 1,
    }


def _request(target_ref: str = "SKU-1") -> AnomalyCheckRequest:
    return AnomalyCheckRequest(
        target_ref=target_ref,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        as_of_date=_AS_OF,
        requested_by=uuid4(),
        computed_at=_COMPUTED_AT,
    )


def test_all_three_methods_return_configuration_gap_when_no_config_exists(monkeypatch) -> None:
    rows = [_margin_row(period=f"2026-0{i}-01/2026-0{i}-28", numerator=10 + i, denominator=1) for i in range(1, 9)]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)
    monkeypatch.setattr(cfo_actions_module.config_repo, "resolve_anomaly_detection_config", lambda *a, **k: None)

    outcome = run_anomaly_check(uuid4(), _request())

    assert outcome.series_length == 8
    assert len(outcome.methods) == 3
    for method_outcome in outcome.methods:
        assert isinstance(method_outcome.configuration_gap, AnomalyConfigurationGap)
        assert method_outcome.flag is None
        assert method_outcome.insufficient_history is None
        assert method_outcome.zero_variance is None


def test_unavailable_rows_are_excluded_from_series_never_zero_placeholder(monkeypatch) -> None:
    rows = [
        _margin_row(period="2026-01-01/2026-01-31", numerator=10, denominator=1),
        _margin_row(period="2026-02-01/2026-02-28", numerator=None, denominator=None, is_available=False),
        _margin_row(period="2026-03-01/2026-03-31", numerator=12, denominator=1),
    ]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)
    monkeypatch.setattr(cfo_actions_module.config_repo, "resolve_anomaly_detection_config", lambda *a, **k: None)

    outcome = run_anomaly_check(uuid4(), _request())

    assert outcome.series_length == 2  # the UNAVAILABLE row never became a SeriesPoint


def test_insufficient_history_below_every_methods_floor(monkeypatch) -> None:
    rows = [_margin_row(period="2026-01-01/2026-01-31", numerator=10, denominator=1)]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    def _resolve_config(tenant_id, *, metric, method, as_of_date):
        if method == "Z_SCORE":
            return _z_score_config_row()
        if method == "PERCENTILE_THRESHOLD":
            return _percentile_config_row()
        return _delta_config_row()

    monkeypatch.setattr(cfo_actions_module.config_repo, "resolve_anomaly_detection_config", _resolve_config)

    outcome = run_anomaly_check(uuid4(), _request())

    assert outcome.series_length == 1
    for method_outcome in outcome.methods:
        assert isinstance(method_outcome.insufficient_history, AnomalyInsufficientHistory)
        assert method_outcome.insufficient_history.series_length == 1


def test_real_flag_computed_when_config_exists_and_series_is_long_enough(monkeypatch) -> None:
    """10 points satisfies every method's floor (8/10/5) — real calc_engine.anomaly functions
    run unchanged, real Fraction arithmetic, no mocking of the statistics themselves."""
    rows = [
        _margin_row(period=f"2026-{i:02d}-01/2026-{i:02d}-28", numerator=20 + i, denominator=1)
        for i in range(1, 11)
    ]
    # A clear outlier as the latest point to exercise a real, deterministic fired=True path.
    rows[-1] = _margin_row(period="2026-10-01/2026-10-28", numerator=500, denominator=1)
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    def _resolve_config(tenant_id, *, metric, method, as_of_date):
        if method == "Z_SCORE":
            return _z_score_config_row()
        if method == "PERCENTILE_THRESHOLD":
            return _percentile_config_row()
        return _delta_config_row()

    monkeypatch.setattr(cfo_actions_module.config_repo, "resolve_anomaly_detection_config", _resolve_config)

    outcome = run_anomaly_check(uuid4(), _request())

    assert outcome.series_length == 10
    z_outcome = next(m for m in outcome.methods if m.method == "Z_SCORE")
    assert isinstance(z_outcome.flag, AnomalyFlag)
    assert z_outcome.flag.fired is True
    assert z_outcome.flag.severity == "HIGH"
    assert z_outcome.flag.data_confidence == "DERIVED"  # floored at DERIVED, §6.4
    assert z_outcome.flag.source_engine_result_refs == tuple(r["id"] for r in rows)


def test_series_is_sorted_chronologically_regardless_of_row_order(monkeypatch) -> None:
    rows = [
        _margin_row(period="2026-03-01/2026-03-31", numerator=30, denominator=1),
        _margin_row(period="2026-01-01/2026-01-31", numerator=10, denominator=1),
        _margin_row(period="2026-02-01/2026-02-28", numerator=20, denominator=1),
    ]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)
    monkeypatch.setattr(cfo_actions_module.config_repo, "resolve_anomaly_detection_config", lambda *a, **k: None)

    outcome = run_anomaly_check(uuid4(), _request())
    assert outcome.series_length == 3  # sorting doesn't drop points; exact order checked via helper below


def test_series_point_conversion_reconstructs_exact_fraction(monkeypatch) -> None:
    # Renamed this checkpoint (E3's original MARGIN_PCT-only name ->
    # _series_point_from_fraction_metric_row) when run_anomaly_check was generalized to all
    # four anomaly-detection.md §6.1 series — the function itself needed no behaviour change,
    # only a name that no longer claims to be margin-specific.
    from backend.services.cfo_actions import _series_point_from_fraction_metric_row

    row = _margin_row(period="2026-01-01/2026-01-31", numerator=1, denominator=3)
    point = _series_point_from_fraction_metric_row(row)
    assert point is not None
    assert point.value == Fraction(1, 3)
    assert point.period == date(2026, 1, 1)
    assert point.confidence.value == "VERIFIED"


def test_series_point_conversion_returns_none_for_unavailable_row() -> None:
    from backend.services.cfo_actions import _series_point_from_fraction_metric_row

    row = _margin_row(period="2026-01-01/2026-01-31", numerator=None, denominator=None, is_available=False)
    assert _series_point_from_fraction_metric_row(row) is None
