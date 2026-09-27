"""`backend.services.cfo_actions.assemble_funding_readiness_reduced` — cfo-agent.md §6.13/D7
"funding readiness", the REDUCED slice (twinkly-mapping-canyon.md CP B2): Contribution Profit
history and trend, with data-completeness stated, plus explicit gaps (periods missing, COGS/
RTO-classification absent). Margin stability, revenue concentration and cash-conversion timing
are explicitly NOT assembled by this slice — `FundingReadinessOutcome.deferred_sections` must
say so structurally.

`metric_result_repo.list_by_metric_code`/`.save` and `insert_data_request` are monkeypatched —
no live Postgres in this session, mirroring `test_cfo_actions_period_comparison.py`'s own
monkeypatch conventions exactly. `compute_metric_delta` is the REAL, unchanged engine function
(`calc_engine.formulas.metric_delta`) — never stubbed, so trend deltas are verified against
real arithmetic, not assumed.

Covers:
  - multiple periods of CP history, some with gaps (a missing period per `expected_periods`,
    an UNAVAILABLE COGS-less period) -> every gap named, never silently dropped.
  - trend deltas computed correctly between consecutive periods in the fetched history, via the
    real `compute_metric_delta`.
  - AC19 guardrail: no score/valuation/rating field exists anywhere on `FundingReadinessOutcome`
    or `FundingReadinessGap` or `DeferredFundingReadinessSection` (structural, dataclass-field
    inspection, not just an assertion in prose).
  - explicit-deferral: `deferred_sections` names margin stability, revenue concentration and
    cash-conversion timing as deferred pending Phase D.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from calc_engine.api.compute_metric import MetricResult
from calc_engine.types import RecognitionState

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    DeferredFundingReadinessSection,
    FundingReadinessGap,
    FundingReadinessOutcome,
    FundingReadinessRequest,
    assemble_funding_readiness_reduced,
)

_AS_OF = date(2026, 9, 23)
_COMPUTED_AT = datetime(2026, 9, 23, tzinfo=timezone.utc)
_TENANT = uuid4()


def _metric_result(
    *,
    value_paise: int | None = 500_00,
    is_available: bool = True,
    confidence: str = "VERIFIED",
    unavailable_reason: str | None = None,
) -> MetricResult:
    return MetricResult(
        id=uuid4(),
        metric_code="CONTRIBUTION_PROFIT",
        value_paise=value_paise,
        recognition_state=RecognitionState.RECOGNISED if is_available else RecognitionState.UNAVAILABLE,
        confidence=confidence,
        calculation_basis="ContributionProfit (§5.8)",
        formula_version="CONTRIBUTION_PROFIT.v1",
        canonical_data_version="cdv-1",
        as_of_date=_AS_OF,
        input_refs=(),
        exclusions=(),
        computed_at=_COMPUTED_AT,
        is_available=is_available,
        manual_adjustment_set=(),
        unavailable_reason=unavailable_reason,
    )


def _row_for(result: MetricResult, *, period: str) -> dict[str, object]:
    """The raw dict shape `metric_result_repo.list_by_metric_code` returns — same column set
    `test_cfo_actions_period_comparison.py`'s own `_row_for` uses for `.get`."""
    return {
        "id": result.id,
        "metric_code": result.metric_code,
        "grain": "TENANT_PERIOD",
        "target_ref": str(_TENANT),
        "period": period,
        "value_paise": result.value_paise,
        "recognition_state": result.recognition_state.value,
        "confidence": result.confidence,
        "calculation_basis": result.calculation_basis,
        "formula_version": result.formula_version,
        "config_version": "CFO_PERIOD_PNL.v1",
        "canonical_data_version": result.canonical_data_version,
        "manual_adjustment_set": list(result.manual_adjustment_set),
        "as_of_date": result.as_of_date,
        "input_refs": list(result.input_refs),
        "exclusions": list(result.exclusions),
        "is_trial": False,
        "is_available": result.is_available,
        "unavailable_reason": result.unavailable_reason,
        "computed_at": result.computed_at,
    }


def _request(*, expected_periods: tuple[str, ...] = ()) -> FundingReadinessRequest:
    return FundingReadinessRequest(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        as_of_date=_AS_OF,
        requested_by=uuid4(),
        expected_periods=expected_periods,
        computed_at=_COMPUTED_AT,
    )


@pytest.fixture(autouse=True)
def _stub_save(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", lambda *a, **k: None)


# ---------------------------------------------------------------------------------------
# Gaps — named, never silently dropped.
# ---------------------------------------------------------------------------------------


def test_missing_expected_period_and_unavailable_result_both_named_as_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jan = _metric_result(value_paise=400_00)
    feb = _metric_result(is_available=False, value_paise=None, unavailable_reason="cogs_per_unit unavailable")
    # March is expected but absent from history entirely.
    rows = [
        _row_for(jan, period="2026-01-01/2026-01-31"),
        _row_for(feb, period="2026-02-01/2026-02-28"),
    ]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = assemble_funding_readiness_reduced(
        _TENANT,
        _request(
            expected_periods=(
                "2026-01-01/2026-01-31",
                "2026-02-01/2026-02-28",
                "2026-03-01/2026-03-31",
            )
        ),
    )

    missing = [g for g in outcome.gaps if g.kind == "MISSING_PERIOD"]
    unavailable = [g for g in outcome.gaps if g.kind == "UNAVAILABLE_RESULT"]
    assert len(missing) == 1
    assert missing[0].period == "2026-03-01/2026-03-31"
    assert len(unavailable) == 1
    assert unavailable[0].period == "2026-02-01/2026-02-28"
    assert unavailable[0].reason == "cogs_per_unit unavailable"

    # Non-blocking, informational data request naming the gaps (C8 discipline).
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert "2026-03-01/2026-03-31" in captured_requests[0]["reason"]
    assert "2026-02-01/2026-02-28" in captured_requests[0]["reason"]

    # History still contains both fetched results — a gap never removes a row that DOES exist.
    assert len(outcome.contribution_profit_history) == 2


def test_no_gaps_no_data_request(monkeypatch: pytest.MonkeyPatch) -> None:
    jan = _metric_result(value_paise=400_00)
    rows = [_row_for(jan, period="2026-01-01/2026-01-31")]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)
    monkeypatch.setattr(
        cfo_actions_module, "insert_data_request", lambda *a, **k: pytest.fail("should not be called")
    )

    outcome = assemble_funding_readiness_reduced(
        _TENANT, _request(expected_periods=("2026-01-01/2026-01-31",))
    )

    assert outcome.gaps == []
    assert outcome.data_request_id is None


def test_empty_expected_periods_means_no_missing_period_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty `expected_periods` is 'no missing-period check requested', not 'every period is
    missing' — a caller-supplied absence of expectations, never inferred by CFO itself."""
    jan = _metric_result(value_paise=400_00)
    rows = [_row_for(jan, period="2026-01-01/2026-01-31")]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    outcome = assemble_funding_readiness_reduced(_TENANT, _request(expected_periods=()))

    assert [g for g in outcome.gaps if g.kind == "MISSING_PERIOD"] == []


def test_zero_history_rows_produces_no_arithmetic_error_and_names_every_expected_period_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: [])
    monkeypatch.setattr(cfo_actions_module, "insert_data_request", lambda tenant_id, **kwargs: uuid4())

    outcome = assemble_funding_readiness_reduced(
        _TENANT, _request(expected_periods=("2026-01-01/2026-01-31",))
    )

    assert outcome.contribution_profit_history == []
    assert outcome.trend == []
    assert len(outcome.gaps) == 1
    assert outcome.gaps[0].kind == "MISSING_PERIOD"


# ---------------------------------------------------------------------------------------
# Trend — real compute_metric_delta, per consecutive pair.
# ---------------------------------------------------------------------------------------


def test_trend_deltas_computed_via_real_compute_metric_delta_between_consecutive_periods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jan = _metric_result(value_paise=400_00)
    feb = _metric_result(value_paise=550_00)
    mar = _metric_result(value_paise=500_00)
    rows = [
        _row_for(jan, period="2026-01-01/2026-01-31"),
        _row_for(feb, period="2026-02-01/2026-02-28"),
        _row_for(mar, period="2026-03-01/2026-03-31"),
    ]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    saved: list[MetricResult] = []
    monkeypatch.setattr(
        cfo_actions_module.metric_result_repo,
        "save",
        lambda tenant_id, result, **kwargs: saved.append(result),
    )

    outcome = assemble_funding_readiness_reduced(_TENANT, _request())

    assert len(outcome.trend) == 2  # two consecutive pairs across three periods
    # Real engine arithmetic, unchanged: 550_00 - 400_00, then 500_00 - 550_00.
    assert outcome.trend[0].value_paise == 150_00
    assert outcome.trend[1].value_paise == -50_00
    assert all(d.metric_code == "CONTRIBUTION_PROFIT_DELTA" for d in outcome.trend)
    assert len(saved) == 2
    assert saved == list(outcome.trend)


def test_single_period_history_produces_no_trend(monkeypatch: pytest.MonkeyPatch) -> None:
    jan = _metric_result(value_paise=400_00)
    rows = [_row_for(jan, period="2026-01-01/2026-01-31")]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    outcome = assemble_funding_readiness_reduced(_TENANT, _request())

    assert outcome.trend == []
    assert len(outcome.contribution_profit_history) == 1


def test_history_sorted_chronologically_regardless_of_fetch_order(monkeypatch: pytest.MonkeyPatch) -> None:
    jan = _metric_result(value_paise=100_00)
    feb = _metric_result(value_paise=300_00)
    # Deliberately returned out of chronological order.
    rows = [
        _row_for(feb, period="2026-02-01/2026-02-28"),
        _row_for(jan, period="2026-01-01/2026-01-31"),
    ]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    outcome = assemble_funding_readiness_reduced(_TENANT, _request())

    assert outcome.contribution_profit_history[0].value_paise == 100_00
    assert outcome.contribution_profit_history[1].value_paise == 300_00
    assert outcome.trend[0].value_paise == 200_00  # 300_00 - 100_00, correctly ordered


# ---------------------------------------------------------------------------------------
# AC19 — no score, valuation or lending judgement anywhere. Structural, not prose.
# ---------------------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = ("score", "rating", "valuation", "recommend", "grade")


def test_ac19_no_score_valuation_or_rating_field_on_any_funding_readiness_dataclass() -> None:
    for dataclass_type in (FundingReadinessOutcome, FundingReadinessGap, DeferredFundingReadinessSection):
        field_names = [f.name.lower() for f in dataclasses.fields(dataclass_type)]
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            offending = [name for name in field_names if forbidden in name]
            assert offending == [], (
                f"{dataclass_type.__name__} carries a field matching forbidden term "
                f"{forbidden!r}: {offending} — AC19 violation"
            )


def test_ac19_outcome_instance_has_no_numeric_or_categorical_judgement_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Instance-level check, not just class-level field names: every field's VALUE is either a
    `MetricResult`/list of them, a list of named gaps, or the deferred-sections tuple — never a
    bare number or a category label that could be read as a rating."""
    rows = [_row_for(_metric_result(value_paise=400_00), period="2026-01-01/2026-01-31")]
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: rows)

    outcome = assemble_funding_readiness_reduced(_TENANT, _request())

    field_names = {f.name for f in dataclasses.fields(FundingReadinessOutcome)}
    assert field_names == {
        "contribution_profit_history",
        "trend",
        "gaps",
        "deferred_sections",
        "data_request_id",
    }
    assert isinstance(outcome.contribution_profit_history, list)
    assert isinstance(outcome.trend, list)
    assert isinstance(outcome.gaps, list)
    assert isinstance(outcome.deferred_sections, tuple)


# ---------------------------------------------------------------------------------------
# Explicit deferral — margin stability / revenue concentration / cash-conversion timing.
# ---------------------------------------------------------------------------------------


def test_deferred_sections_name_margin_stability_revenue_concentration_and_cash_conversion_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: [])

    outcome = assemble_funding_readiness_reduced(_TENANT, _request())

    names = {section.name for section in outcome.deferred_sections}
    assert "margin_stability" in names
    assert "revenue_concentration_by_sku_and_marketplace" in names
    assert "cash_conversion_timing" in names
    for section in outcome.deferred_sections:
        assert "Phase D" in section.blocked_on
        assert section.reason  # non-empty, names why — never a blank placeholder


def test_deferred_sections_present_even_when_history_and_gaps_are_both_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deferral statement is unconditional — it must never look like it depends on there
    being any data at all, or any gaps found (never silently absent because 'nothing to
    report')."""
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "list_by_metric_code", lambda *a, **k: [])

    outcome = assemble_funding_readiness_reduced(_TENANT, _request(expected_periods=()))

    assert outcome.contribution_profit_history == []
    assert outcome.gaps == []
    assert len(outcome.deferred_sections) == 3
