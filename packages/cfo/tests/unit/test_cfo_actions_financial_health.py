"""`backend.services.cfo_actions.assemble_financial_health` — cfo-agent.md §6.15 (Financial
Health Band). Mirrors `test_cfo_actions_anomaly_check.py`'s monkeypatch conventions:
`metric_result_repo.list_by_metric_code`/`config_repo.financial_health_config_rows` are
monkeypatched — no live Postgres in this session — and the real `calc_engine.formulas.
financial_health.assemble_financial_health` (imported into cfo_actions as
`compute_financial_health_band`) is exercised for real.

Covers:
  - a healthy period across all 3 metrics -> overall_band GOOD, all 3 engine_result_refs cited.
  - one AT_RISK metric outranks two GOOD metrics for the overall band.
  - an UNAVAILABLE metric row is excluded (never a zero-valued placeholder).
  - no metric_result rows at all for the period -> a real, named unavailable_reason, never a
    fabricated GOOD band.
  - more than one row for the same (metric, period) -> the latest by computed_at wins.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import FinancialHealthRequest, HealthBand, assemble_financial_health

_AS_OF = date(2026, 9, 27)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)


def _metric_row(
    *,
    metric_code: str,
    numerator: int | None,
    denominator: int | None = 1,
    is_available: bool = True,
    computed_at: datetime = datetime(2026, 9, 27, tzinfo=timezone.utc),
    row_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "id": row_id or uuid4(),
        "metric_code": metric_code,
        "period": f"{_PERIOD_START.isoformat()}/{_PERIOD_END.isoformat()}",
        "value_paise": None,
        "value_fraction_numerator": numerator,
        "value_fraction_denominator": denominator,
        "is_available": is_available,
        "computed_at": computed_at,
    }


def _config_row(*, metric: str, direction: str, at_risk: str | None, watch: str | None) -> dict[str, object]:
    return {
        "metric": metric,
        "direction": direction,
        "at_risk_threshold_pct": Decimal(at_risk) if at_risk is not None else None,
        "watch_threshold_pct": Decimal(watch) if watch is not None else None,
    }


_CONFIG_ROWS = [
    _config_row(metric="CONTRIBUTION_MARGIN_PCT", direction="LOWER_IS_WORSE", at_risk="5.00", watch="10.00"),
    _config_row(metric="FEE_RATIO_PCT", direction="HIGHER_IS_WORSE", at_risk="35.00", watch="25.00"),
    _config_row(metric="RETURN_RATE_PCT", direction="HIGHER_IS_WORSE", at_risk="20.00", watch="10.00"),
]


def _patch(monkeypatch, rows_by_metric: dict[str, list[dict[str, object]]], config_rows=None):
    def _fake_list_by_metric_code(tenant_id, *, metric_code, period_start=None, period_end=None):
        return rows_by_metric.get(metric_code, [])

    def _fake_config_rows(tenant_id, *, as_of_date):
        return config_rows if config_rows is not None else _CONFIG_ROWS

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", _fake_list_by_metric_code)
    monkeypatch.setattr(cfo_actions_module.config_repo, "financial_health_config_rows", _fake_config_rows)


def test_healthy_period_across_all_three_metrics_is_good(monkeypatch) -> None:
    _patch(
        monkeypatch,
        {
            "CONTRIBUTION_MARGIN_PCT": [_metric_row(metric_code="CONTRIBUTION_MARGIN_PCT", numerator=15, denominator=1)],
            "FEE_RATIO_PCT": [_metric_row(metric_code="FEE_RATIO_PCT", numerator=10, denominator=1)],
            "RETURN_RATE_PCT": [_metric_row(metric_code="RETURN_RATE_PCT", numerator=5, denominator=1)],
        },
    )

    outcome = assemble_financial_health(
        uuid4(), FinancialHealthRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF)
    )

    assert outcome.overall_band == HealthBand.GOOD
    assert set(outcome.per_metric_bands) == {"CONTRIBUTION_MARGIN_PCT", "FEE_RATIO_PCT", "RETURN_RATE_PCT"}
    assert len(outcome.engine_result_refs) == 3
    assert outcome.unavailable_reason is None


def test_one_at_risk_metric_outranks_two_good_metrics(monkeypatch) -> None:
    _patch(
        monkeypatch,
        {
            "CONTRIBUTION_MARGIN_PCT": [_metric_row(metric_code="CONTRIBUTION_MARGIN_PCT", numerator=15, denominator=1)],
            "FEE_RATIO_PCT": [_metric_row(metric_code="FEE_RATIO_PCT", numerator=40, denominator=1)],  # AT_RISK
            "RETURN_RATE_PCT": [_metric_row(metric_code="RETURN_RATE_PCT", numerator=5, denominator=1)],
        },
    )

    outcome = assemble_financial_health(
        uuid4(), FinancialHealthRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF)
    )

    assert outcome.overall_band == HealthBand.AT_RISK
    assert outcome.per_metric_bands["FEE_RATIO_PCT"] == HealthBand.AT_RISK


def test_unavailable_metric_row_is_excluded_not_a_zero_placeholder(monkeypatch) -> None:
    _patch(
        monkeypatch,
        {
            "CONTRIBUTION_MARGIN_PCT": [_metric_row(metric_code="CONTRIBUTION_MARGIN_PCT", numerator=None, is_available=False)],
            "FEE_RATIO_PCT": [_metric_row(metric_code="FEE_RATIO_PCT", numerator=10, denominator=1)],
            "RETURN_RATE_PCT": [_metric_row(metric_code="RETURN_RATE_PCT", numerator=5, denominator=1)],
        },
    )

    outcome = assemble_financial_health(
        uuid4(), FinancialHealthRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF)
    )

    assert "CONTRIBUTION_MARGIN_PCT" not in outcome.per_metric_bands
    assert outcome.overall_band == HealthBand.GOOD
    assert len(outcome.engine_result_refs) == 2


def test_no_metric_result_rows_at_all_yields_named_unavailable_reason_never_a_fabricated_band(
    monkeypatch,
) -> None:
    _patch(monkeypatch, {})

    outcome = assemble_financial_health(
        uuid4(), FinancialHealthRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF)
    )

    assert outcome.overall_band is None
    assert outcome.per_metric_bands == {}
    assert outcome.engine_result_refs == ()
    assert outcome.unavailable_reason is not None


def test_more_than_one_row_for_same_metric_and_period_takes_latest_by_computed_at(monkeypatch) -> None:
    older = _metric_row(
        metric_code="CONTRIBUTION_MARGIN_PCT",
        numerator=15,
        denominator=1,  # GOOD
        computed_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    newer = _metric_row(
        metric_code="CONTRIBUTION_MARGIN_PCT",
        numerator=3,
        denominator=1,  # AT_RISK — this one should win
        computed_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )
    _patch(monkeypatch, {"CONTRIBUTION_MARGIN_PCT": [older, newer]})

    outcome = assemble_financial_health(
        uuid4(), FinancialHealthRequest(period_start=_PERIOD_START, period_end=_PERIOD_END, as_of_date=_AS_OF)
    )

    assert outcome.per_metric_bands["CONTRIBUTION_MARGIN_PCT"] == HealthBand.AT_RISK
