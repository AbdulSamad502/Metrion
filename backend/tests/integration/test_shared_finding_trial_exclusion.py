"""`shared_finding_repo.resolve_engine_results` must not resolve a trial `metric_result` (engine spec §9.2, F2): a finding may not cite a
validation-run figure as an engine result a seller can see. `include_trial=True` is the explicit internal opt-in."""

from __future__ import annotations

import os
import uuid

import pytest
from calc_engine.api.compute_metric import MetricResult
from calc_engine.repositories import metric_result_repo
from calc_engine.types import RecognitionState
from datetime import date, datetime, timezone

from backend.repositories import shared_finding_repo as repo

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]


def _save(tenant, *, is_trial: bool) -> uuid.UUID:
    result = MetricResult(
        id=uuid.uuid4(), metric_code="CONTRIBUTION_PROFIT", value_paise=100, recognition_state=RecognitionState.RECOGNISED, confidence="VERIFIED",
        calculation_basis="t", formula_version="CONTRIBUTION_PROFIT.v2-trial" if is_trial else "CONTRIBUTION_PROFIT.v1", canonical_data_version="cdv",
        as_of_date=date(2026, 9, 30), input_refs=(), exclusions=(), computed_at=datetime(2026, 10, 16, tzinfo=timezone.utc), is_available=True,
        manual_adjustment_set=(),
    )
    return metric_result_repo.save(tenant, result, grain="TENANT_PERIOD", target_ref=str(tenant), period="2026-09-01/2026-09-30",
                                   config_version="CFO_PERIOD_PNL.v1", is_trial=is_trial)


def test_a_trial_result_does_not_resolve_by_default(two_tenants):
    tenant, _ = two_tenants
    real, trial = _save(tenant, is_trial=False), _save(tenant, is_trial=True)
    assert repo.resolve_engine_results(tenant, [str(real), str(trial)]) == {str(real)}
    assert repo.resolve_engine_results(tenant, [str(real), str(trial)], include_trial=True) == {str(real), str(trial)}
