"""`metric_result_repo.list_by_metric_code` against a real Postgres (twinkly-mapping-canyon.md
CP B2) — proves the text-range period filter/ordering behaves correctly against the REAL
`"{start}/{end}"` compound label shape `save()` persists, not merely against the SQL read in
isolation. Mirrors `test_fee_reference_config_repo.py`'s own seed-via-real-function,
read-via-real-function pattern, and `test_rls_isolation.py`'s own `tenant_scope`/`two_tenants`
conventions.

**NOTE (honest reporting, same standard as CP2/CP3):** this file was written against the
established integration-test pattern (`conftest.py`'s `pytestmark`/`_clean_engine_tables`
fixtures) but could not be executed in this session — Postgres was not reachable
(`docker ps` failed: no Docker daemon running), so `DATABASE_URL_APP`/`DATABASE_URL` are unset
and `pytestmark` in `conftest.py` skips the whole module. This is a written-but-unexecuted test,
not a fabricated pass.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from calc_engine.api.compute_metric import MetricResult
from calc_engine.repositories import metric_result_repo
from calc_engine.types import RecognitionState

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")

_COMPUTED_AT = datetime(2026, 9, 24, tzinfo=timezone.utc)


def _cp_result(*, value_paise: int, as_of: date) -> MetricResult:
    return MetricResult(
        id=uuid.uuid4(),
        metric_code="CONTRIBUTION_PROFIT",
        value_paise=value_paise,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="VERIFIED",
        calculation_basis="ContributionProfit (§5.8)",
        formula_version="CONTRIBUTION_PROFIT.v1",
        canonical_data_version="cdv-1",
        as_of_date=as_of,
        input_refs=(),
        exclusions=(),
        computed_at=_COMPUTED_AT,
        is_available=True,
        manual_adjustment_set=(),
    )


def test_returns_only_this_tenants_rows_for_the_requested_metric_code(two_tenants):
    tenant_a, tenant_b = two_tenants
    metric_result_repo.save(
        tenant_a,
        _cp_result(value_paise=400_00, as_of=date(2026, 1, 31)),
        grain="TENANT_PERIOD",
        target_ref=str(tenant_a),
        period="2026-01-01/2026-01-31",
        config_version="CFO_PERIOD_PNL.v1",
    )
    metric_result_repo.save(
        tenant_b,
        _cp_result(value_paise=999_00, as_of=date(2026, 1, 31)),
        grain="TENANT_PERIOD",
        target_ref=str(tenant_b),
        period="2026-01-01/2026-01-31",
        config_version="CFO_PERIOD_PNL.v1",
    )

    rows = metric_result_repo.list_by_metric_code(tenant_a, metric_code="CONTRIBUTION_PROFIT")

    assert len(rows) == 1
    assert rows[0]["value_paise"] == 400_00


def test_orders_by_period_ascending_and_filters_by_iso_date_range(two_tenants):
    tenant_a, _ = two_tenants
    for month, value in (("01", 100_00), ("02", 300_00), ("03", 200_00)):
        metric_result_repo.save(
            tenant_a,
            _cp_result(value_paise=value, as_of=date(2026, int(month), 28)),
            grain="TENANT_PERIOD",
            target_ref=str(tenant_a),
            period=f"2026-{month}-01/2026-{month}-28",
            config_version="CFO_PERIOD_PNL.v1",
        )

    # Full range: chronological order, regardless of insertion order.
    all_rows = metric_result_repo.list_by_metric_code(tenant_a, metric_code="CONTRIBUTION_PROFIT")
    assert [r["value_paise"] for r in all_rows] == [100_00, 300_00, 200_00]

    # Range filter excludes March.
    jan_feb_only = metric_result_repo.list_by_metric_code(
        tenant_a,
        metric_code="CONTRIBUTION_PROFIT",
        period_start="2026-01-01",
        period_end="2026-02-28",
    )
    assert [r["value_paise"] for r in jan_feb_only] == [100_00, 300_00]


def test_different_metric_code_excluded(two_tenants):
    tenant_a, _ = two_tenants
    nrr = MetricResult(
        id=uuid.uuid4(),
        metric_code="NET_REALIZED_REVENUE",
        value_paise=1000_00,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="VERIFIED",
        calculation_basis="NRR",
        formula_version="NET_REALIZED_REVENUE.v1",
        canonical_data_version="cdv-1",
        as_of_date=date(2026, 1, 31),
        input_refs=(),
        exclusions=(),
        computed_at=_COMPUTED_AT,
        is_available=True,
        manual_adjustment_set=(),
    )
    metric_result_repo.save(
        tenant_a,
        nrr,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_a),
        period="2026-01-01/2026-01-31",
        config_version="CFO_PERIOD_PNL.v1",
    )

    rows = metric_result_repo.list_by_metric_code(tenant_a, metric_code="CONTRIBUTION_PROFIT")
    assert rows == []


def test_null_period_rows_excluded_by_a_period_range_filter(two_tenants):
    """A SKU-grain result (e.g. pricing curve) persists `period=None` — it can never satisfy a
    `period_start`/`period_end` filter, which is correct: it has no period to compare."""
    tenant_a, _ = two_tenants
    metric_result_repo.save(
        tenant_a,
        _cp_result(value_paise=50_00, as_of=date(2026, 1, 15)),
        grain="SKU",
        target_ref="SKU-1",
        period=None,
        config_version="CFO_PRICING_CURVE.v1",
    )

    filtered = metric_result_repo.list_by_metric_code(
        tenant_a, metric_code="CONTRIBUTION_PROFIT", period_start="2026-01-01", period_end="2026-01-31"
    )
    assert filtered == []

    unfiltered = metric_result_repo.list_by_metric_code(tenant_a, metric_code="CONTRIBUTION_PROFIT")
    assert len(unfiltered) == 1
