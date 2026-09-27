"""`backend.services.cfo_actions.narrate_period_comparison` — end-to-end at the unit level,
real engine functions (`compute_metric_delta`, `calc_engine.formulas.metric_delta`) and real
`cfo.reasoning.narrate.narrate_figures`. The two DB-touching calls this composition makes
(`metric_result_repo.get`/`.save`) and the data-request insert are monkeypatched — no live
Postgres in this session, mirroring `test_cfo_actions_pricing.py`'s own
`_stub_persistence`/`insert_data_request` monkeypatch conventions exactly.

Activates twinkly-mapping-canyon.md CP A3 / cfo-agent.md §7.4.4's "once built" rule and its
T37/T42 "once built" test variants (see `test_deferred_blockers.py`'s corrected entry and
`cfo-agent.md` §12's corrected T37/T42 rows).

Covers:
  - two available `MetricResult`s, same `metric_code` -> delta computed correctly (real
    `compute_metric_delta`), persisted, narration called with correctly-formatted
    `FigureToken`s (AC26/AC27 — Brain 3 never sees a raw number).
  - mismatched `metric_code` -> `ValueError` propagates uncaught (matches CP3's own
    established convention for `compute_metric_delta`/`metric_delta`).
  - one or both `metric_result` ids not found (`metric_result_repo.get` returns `None`) ->
    exactly one `agent_data_request` raised, `compute_metric_delta`/`narrate_figures` never
    called.
  - one input `is_available=False` -> the real `compute_metric_delta` returns an `UNAVAILABLE`
    delta (verified by calling it for real, not assumed) -> narration still happens, explains
    the unavailability rather than being skipped.
  - `_metric_result_from_row`'s dict -> dataclass round-trip, exercised directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from calc_engine.api.compute_metric import MetricResult
from calc_engine.types import RecognitionState

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    PeriodComparisonRequest,
    _format_paise_for_narration,
    _metric_result_from_row,
    _register_for,
    narrate_period_comparison,
)

_AS_OF = date(2026, 9, 23)
_COMPUTED_AT = datetime(2026, 9, 23, tzinfo=timezone.utc)


@dataclass
class _StubProvider:
    """Deterministic `LlmProvider` stand-in — mirrors `test_narrate_no_numbers.py`'s own
    `_StubProvider` pattern exactly (never a real model call in this test file)."""

    response: str = "Your Contribution Profit moved between the two periods."
    captured_prompts: list[str] = field(default_factory=list)

    def complete(self, *, model: str, prompt: str) -> str:
        self.captured_prompts.append(prompt)
        return self.response


def _metric_result(
    *,
    metric_code: str = "CONTRIBUTION_PROFIT",
    value_paise: int | None = 500_00,
    is_available: bool = True,
    confidence: str = "VERIFIED",
    unavailable_reason: str | None = None,
    result_id: UUID | None = None,
) -> MetricResult:
    return MetricResult(
        id=result_id or uuid4(),
        metric_code=metric_code,
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


def _row_for(result: MetricResult, *, period: str = "2026-08-01/2026-08-31") -> dict[str, object]:
    """The raw dict shape `metric_result_repo.get` returns — every column `_GET_SQL` selects,
    including the persistence-only ones (`grain`/`target_ref`/`period`/`config_version`/
    `is_trial`) `_metric_result_from_row` deliberately does not read."""
    return {
        "id": result.id,
        "metric_code": result.metric_code,
        "grain": "TENANT_PERIOD",
        "target_ref": "tenant-1",
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


@pytest.fixture(autouse=True)
def _stub_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", lambda *a, **k: None)


def _request(result_a_id: UUID, result_b_id: UUID) -> PeriodComparisonRequest:
    return PeriodComparisonRequest(
        result_a_id=result_a_id,
        result_b_id=result_b_id,
        as_of_date=_AS_OF,
        requested_by=uuid4(),
        computed_at=_COMPUTED_AT,
    )


# ---------------------------------------------------------------------------------------
# _metric_result_from_row — the dict -> dataclass round-trip, the one genuinely new plumbing.
# ---------------------------------------------------------------------------------------


def test_metric_result_from_row_round_trips_every_dataclass_field() -> None:
    original = _metric_result()
    row = _row_for(original)
    row["manual_adjustment_set"] = ["adj-1", "adj-2"]
    row["input_refs"] = ["ref-1"]
    row["exclusions"] = [{"code": "X", "reason": "y"}]

    reconstructed = _metric_result_from_row(row)

    assert reconstructed.id == original.id
    assert isinstance(reconstructed.id, UUID)
    assert reconstructed.metric_code == original.metric_code
    assert reconstructed.value_paise == original.value_paise
    assert reconstructed.recognition_state == RecognitionState.RECOGNISED
    assert reconstructed.confidence == "VERIFIED"
    assert isinstance(reconstructed.confidence, str)
    assert reconstructed.calculation_basis == original.calculation_basis
    assert reconstructed.formula_version == original.formula_version
    assert reconstructed.canonical_data_version == original.canonical_data_version
    assert reconstructed.as_of_date == original.as_of_date
    assert reconstructed.input_refs == ("ref-1",)
    assert reconstructed.exclusions == ({"code": "X", "reason": "y"},)
    assert reconstructed.computed_at == original.computed_at
    assert reconstructed.is_available is True
    assert reconstructed.manual_adjustment_set == ("adj-1", "adj-2")
    assert reconstructed.unavailable_reason is None


def test_metric_result_from_row_handles_string_id_and_none_json_columns() -> None:
    """A driver that returns `id` as a `str` (not already `UUID`) and `None` for empty jsonb
    columns (rather than `[]`) must still round-trip correctly — defence, not assumed."""
    original = _metric_result(is_available=False, value_paise=None, unavailable_reason="NRR unavailable")
    row = _row_for(original)
    row["id"] = str(original.id)
    row["manual_adjustment_set"] = None
    row["input_refs"] = None
    row["exclusions"] = None

    reconstructed = _metric_result_from_row(row)

    assert reconstructed.id == original.id
    assert isinstance(reconstructed.id, UUID)
    assert reconstructed.manual_adjustment_set == ()
    assert reconstructed.input_refs == ()
    assert reconstructed.exclusions == ()
    assert reconstructed.is_available is False
    assert reconstructed.value_paise is None
    assert reconstructed.unavailable_reason == "NRR unavailable"


# ---------------------------------------------------------------------------------------
# _register_for — §7.4.7 mapping.
# ---------------------------------------------------------------------------------------


def test_register_for_maps_unavailable_first() -> None:
    result = _metric_result(is_available=False, confidence="VERIFIED")
    assert _register_for(result) == "UNAVAILABLE"


@pytest.mark.parametrize("confidence", ["VERIFIED", "DERIVED", "MANUAL"])
def test_register_for_maps_known_confidence_directly(confidence: str) -> None:
    result = _metric_result(confidence=confidence)
    assert _register_for(result) == confidence


def test_register_for_maps_provisional_to_derived() -> None:
    result = _metric_result(confidence="PROVISIONAL")
    assert _register_for(result) == "DERIVED"


# ---------------------------------------------------------------------------------------
# _format_paise_for_narration — presentation only, never a raw number reaches FigureToken.
# ---------------------------------------------------------------------------------------


def test_format_paise_for_narration_formats_rupees_and_paise() -> None:
    assert _format_paise_for_narration(123_456, is_available=True) == "₹1,234.56"


def test_format_paise_for_narration_handles_negative_values() -> None:
    assert _format_paise_for_narration(-50_00, is_available=True) == "-₹50.00"


def test_format_paise_for_narration_unavailable() -> None:
    assert _format_paise_for_narration(None, is_available=False) == "UNAVAILABLE"
    assert _format_paise_for_narration(100_00, is_available=False) == "UNAVAILABLE"


# ---------------------------------------------------------------------------------------
# narrate_period_comparison — the full composition.
# ---------------------------------------------------------------------------------------


def test_two_available_results_same_metric_code_compute_persist_and_narrate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_a = _metric_result(value_paise=400_00)
    result_b = _metric_result(value_paise=550_00)
    row_a, row_b = _row_for(result_a), _row_for(result_b)

    def _fake_get(tenant_id: UUID, result_id: UUID) -> dict[str, object] | None:
        if result_id == result_a.id:
            return row_a
        if result_id == result_b.id:
            return row_b
        return None

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "get", _fake_get)

    saved: list[MetricResult] = []
    monkeypatch.setattr(
        cfo_actions_module.metric_result_repo,
        "save",
        lambda tenant_id, result, **kwargs: saved.append(result),
    )

    provider = _StubProvider()
    outcome = narrate_period_comparison(
        uuid4(), _request(result_a.id, result_b.id), provider, model="test-model"
    )

    # Real engine arithmetic, unchanged: 550_00 - 400_00 = 150_00.
    assert outcome.delta is not None
    assert outcome.delta.metric_code == "CONTRIBUTION_PROFIT_DELTA"
    assert outcome.delta.value_paise == 150_00
    assert outcome.delta.is_available is True
    assert outcome.data_request_id is None
    assert len(saved) == 1
    assert saved[0] is outcome.delta

    assert outcome.narration == provider.response
    assert len(provider.captured_prompts) == 1
    prompt = provider.captured_prompts[0]
    # AC26/AC27 — the prompt carries only pre-formatted strings, never a bare int/Paise.
    assert "₹4.00" in prompt or "₹400.00" in prompt  # result_a display value present
    assert "₹5.50" in prompt or "₹550.00" in prompt  # result_b display value present
    assert "₹1.50" in prompt or "₹150.00" in prompt  # delta display value present


def test_mismatched_metric_code_raises_value_error_uncaught(monkeypatch: pytest.MonkeyPatch) -> None:
    result_a = _metric_result(metric_code="CONTRIBUTION_PROFIT")
    result_b = _metric_result(metric_code="NET_REALIZED_REVENUE")
    row_a, row_b = _row_for(result_a), _row_for(result_b)

    def _fake_get(tenant_id: UUID, result_id: UUID) -> dict[str, object] | None:
        return row_a if result_id == result_a.id else row_b

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "get", _fake_get)

    provider = _StubProvider()
    with pytest.raises(ValueError, match="metric_delta requires both results to share a metric_code"):
        narrate_period_comparison(uuid4(), _request(result_a.id, result_b.id), provider, model="test-model")

    # No narration attempted for a caller-bug mismatch.
    assert provider.captured_prompts == []


def test_missing_result_a_raises_data_request_no_narration(monkeypatch: pytest.MonkeyPatch) -> None:
    result_b = _metric_result()
    row_b = _row_for(result_b)
    missing_id = uuid4()

    def _fake_get(tenant_id: UUID, result_id: UUID) -> dict[str, object] | None:
        return None if result_id == missing_id else row_b

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "get", _fake_get)

    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    provider = _StubProvider()
    outcome = narrate_period_comparison(uuid4(), _request(missing_id, result_b.id), provider, model="test-model")

    assert outcome.delta is None
    assert outcome.narration is None
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["blocking_metric"] == "PERIOD_COMPARISON_DELTA"
    assert str(missing_id) in captured_requests[0]["reason"]
    assert provider.captured_prompts == []  # narrate_figures never called


def test_missing_result_b_raises_data_request_no_narration(monkeypatch: pytest.MonkeyPatch) -> None:
    result_a = _metric_result()
    row_a = _row_for(result_a)
    missing_id = uuid4()

    def _fake_get(tenant_id: UUID, result_id: UUID) -> dict[str, object] | None:
        return row_a if result_id == result_a.id else None

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "get", _fake_get)
    monkeypatch.setattr(cfo_actions_module, "insert_data_request", lambda tenant_id, **kwargs: uuid4())

    provider = _StubProvider()
    outcome = narrate_period_comparison(uuid4(), _request(result_a.id, missing_id), provider, model="test-model")

    assert outcome.delta is None
    assert outcome.narration is None
    assert outcome.data_request_id is not None
    assert provider.captured_prompts == []


def test_both_results_missing_raises_one_data_request_naming_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "get", lambda tenant_id, result_id: None)

    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    result_a_id, result_b_id = uuid4(), uuid4()
    provider = _StubProvider()
    outcome = narrate_period_comparison(uuid4(), _request(result_a_id, result_b_id), provider, model="test-model")

    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    reason = captured_requests[0]["reason"]
    assert str(result_a_id) in reason
    assert str(result_b_id) in reason


def test_one_result_unavailable_delta_comes_back_unavailable_and_is_narrated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verified against the REAL `compute_metric_delta`, not assumed: per CP3's own
    `metric_delta.py`, either input being unavailable makes the whole delta UNAVAILABLE."""
    result_a = _metric_result(is_available=False, value_paise=None, unavailable_reason="NRR unavailable")
    result_b = _metric_result(value_paise=550_00)
    row_a, row_b = _row_for(result_a), _row_for(result_b)

    def _fake_get(tenant_id: UUID, result_id: UUID) -> dict[str, object] | None:
        return row_a if result_id == result_a.id else row_b

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "get", _fake_get)

    saved: list[MetricResult] = []
    monkeypatch.setattr(
        cfo_actions_module.metric_result_repo,
        "save",
        lambda tenant_id, result, **kwargs: saved.append(result),
    )

    provider = _StubProvider()
    outcome = narrate_period_comparison(
        uuid4(), _request(result_a.id, result_b.id), provider, model="test-model"
    )

    # The delta itself: real compute_metric_delta -> real metric_delta.py -> Unavailable.
    assert outcome.delta is not None
    assert outcome.delta.is_available is False
    assert outcome.delta.value_paise is None
    assert "result_a (earlier period) unavailable" in (outcome.delta.unavailable_reason or "")

    # Still persisted (mirrors compute_contribution_profit persisting its own UNAVAILABLE result).
    assert len(saved) == 1
    assert saved[0].is_available is False

    # Narration is NOT skipped — §7.4.4's newly-activated rule.
    assert outcome.narration is not None
    assert len(provider.captured_prompts) == 1
    prompt = provider.captured_prompts[0]
    assert "UNAVAILABLE" in prompt
