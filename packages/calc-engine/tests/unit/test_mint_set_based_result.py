"""`mint_set_based_result`: gives an oracle-verified set-based value a citable ref without doing any arithmetic or deciding anything."""

from __future__ import annotations

from datetime import date, datetime, timezone

from calc_engine.api.compute_metric import mint_set_based_result
from calc_engine.types import RecognitionState

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def test_an_available_value_is_carried_unchanged_with_its_data_version_and_exclusions() -> None:
    r = mint_set_based_result("GROSS_SALES", 123_456, exclusions=[{"rule": "NO_QUANTITY_OR_GROSS_AMOUNT", "count": 2}], data_version=7, computed_at=NOW, as_of_date=date(2026, 10, 1))
    assert r.is_available and r.value_paise == 123_456 and r.metric_code == "GROSS_SALES" and r.formula_version == "GROSS_SALES.v1"
    assert r.canonical_data_version == "read-model-v7" and r.exclusions == ({"rule": "NO_QUANTITY_OR_GROSS_AMOUNT", "count": 2},)
    assert r.recognition_state is RecognitionState.RECOGNISED and r.unavailable_reason is None


def test_none_is_unavailable_with_a_reason_never_zero() -> None:
    r = mint_set_based_result("SETTLEMENT_RECEIPTS", None, unavailable_reason="no settled amount", data_version=1, computed_at=NOW)
    assert not r.is_available and r.value_paise is None and r.unavailable_reason == "no settled amount" and r.recognition_state is RecognitionState.UNAVAILABLE


def test_zero_is_a_real_value_distinct_from_unavailable() -> None:
    r = mint_set_based_result("GROSS_SALES", 0, data_version=1, computed_at=NOW)
    assert r.is_available and r.value_paise == 0


def test_every_call_mints_a_fresh_ref() -> None:
    a = mint_set_based_result("GROSS_SALES", 1, data_version=1, computed_at=NOW)
    b = mint_set_based_result("GROSS_SALES", 1, data_version=1, computed_at=NOW)
    assert a.id != b.id
