"""`is_trial` read-layer exclusion against a real Postgres (engine spec §9.2; F2).

A trial result (`is_trial = true`, written by the G7 validation run) must be invisible to `get` and `list_by_metric_code` by default and
visible only when a caller opts in with `include_trial=True`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from calc_engine.api.compute_metric import MetricResult
from calc_engine.repositories import metric_result_repo
from calc_engine.types import RecognitionState

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")

_AT = datetime(2026, 10, 16, tzinfo=timezone.utc)


def _cp(value_paise: int, version: str = "CONTRIBUTION_PROFIT.v1") -> MetricResult:
    return MetricResult(
        id=uuid.uuid4(), metric_code="CONTRIBUTION_PROFIT", value_paise=value_paise, recognition_state=RecognitionState.RECOGNISED,
        confidence="VERIFIED", calculation_basis="t", formula_version=version, canonical_data_version="cdv", as_of_date=date(2026, 9, 30),
        input_refs=(), exclusions=(), computed_at=_AT, is_available=True, manual_adjustment_set=(),
    )


def _save(tenant, result, *, is_trial):
    metric_result_repo.save(tenant, result, grain="TENANT_PERIOD", target_ref=str(tenant), period="2026-09-01/2026-09-30",
                            config_version="CFO_PERIOD_PNL.v1", is_trial=is_trial)


def test_get_hides_a_trial_result_by_default(two_tenants):
    tenant, _ = two_tenants
    real, trial = _cp(100), _cp(999, "CONTRIBUTION_PROFIT.v2-trial")
    _save(tenant, real, is_trial=False)
    _save(tenant, trial, is_trial=True)
    assert metric_result_repo.get(tenant, real.id) is not None
    assert metric_result_repo.get(tenant, trial.id) is None
    row = metric_result_repo.get(tenant, trial.id, include_trial=True)
    assert row is not None and row["is_trial"] is True


def test_list_by_metric_code_hides_trial_results_by_default(two_tenants):
    tenant, _ = two_tenants
    _save(tenant, _cp(100), is_trial=False)
    _save(tenant, _cp(999, "CONTRIBUTION_PROFIT.v2-trial"), is_trial=True)
    rows = metric_result_repo.list_by_metric_code(tenant, metric_code="CONTRIBUTION_PROFIT")
    assert [r["value_paise"] for r in rows] == [100]
    both = metric_result_repo.list_by_metric_code(tenant, metric_code="CONTRIBUTION_PROFIT", include_trial=True)
    assert sorted(r["value_paise"] for r in both) == [100, 999]
