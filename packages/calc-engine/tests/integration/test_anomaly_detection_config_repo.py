"""resolve_anomaly_detection_config (docs/specs/anomaly-detection.md §6.5) against a real
Postgres — resolution order (tenant beats platform default, latest effective_from wins) and
RLS (platform-default row visible to every tenant, a tenant row not visible to another
tenant) are proven here, not assumed from the SQL alone. Mirrors
test_reconciliation_config_repo.py's structure.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from calc_engine.repositories.config_repo import resolve_anomaly_detection_config
from calc_engine.repositories.tenant_context import tenant_scope
from tests.integration.owner_db import owner_tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")


def _insert(
    tenant_id,
    metric,
    method,
    min_series_length,
    *,
    connect_as_tenant=None,
    z_score_threshold=None,
    percentile_low=None,
    percentile_high=None,
    delta_severity_bands=None,
    effective_from="2026-01-01",
    version=1,
):
    with owner_tenant_scope(connect_as_tenant if connect_as_tenant is not None else tenant_id) as conn:  # configuration is written by an operator (owner role)
        conn.execute(
            text(
                """
                INSERT INTO anomaly_detection_config
                    (id, tenant_id, metric, method, min_series_length, z_score_threshold,
                     percentile_low, percentile_high, delta_severity_bands, effective_from, version)
                VALUES
                    (:id, :tenant_id, :metric, :method, :min_series_length, :z_score_threshold,
                     :percentile_low, :percentile_high, CAST(:delta_severity_bands AS jsonb),
                     :effective_from, :version)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id) if tenant_id else None,
                "metric": metric,
                "method": method,
                "min_series_length": min_series_length,
                "z_score_threshold": z_score_threshold,
                "percentile_low": percentile_low,
                "percentile_high": percentile_high,
                "delta_severity_bands": delta_severity_bands,
                "effective_from": effective_from,
                "version": version,
            },
        )


def test_platform_default_row_visible_to_every_tenant(two_tenants):
    tenant_a, tenant_b = two_tenants
    _insert(None, "MARGIN_PCT", "Z_SCORE", 8, connect_as_tenant=tenant_a, z_score_threshold="2.500")

    row_a = resolve_anomaly_detection_config(tenant_a, metric="MARGIN_PCT", method="Z_SCORE", as_of_date=date(2026, 9, 25))
    row_b = resolve_anomaly_detection_config(tenant_b, metric="MARGIN_PCT", method="Z_SCORE", as_of_date=date(2026, 9, 25))

    assert row_a is not None
    assert row_b is not None
    assert row_a["min_series_length"] == 8
    assert row_b["min_series_length"] == 8


def test_tenant_override_beats_platform_default(two_tenants):
    tenant_a, _ = two_tenants
    _insert(None, "MARGIN_PCT", "Z_SCORE", 8, connect_as_tenant=tenant_a, z_score_threshold="2.500")
    _insert(tenant_a, "MARGIN_PCT", "Z_SCORE", 12, z_score_threshold="3.000")

    row = resolve_anomaly_detection_config(tenant_a, metric="MARGIN_PCT", method="Z_SCORE", as_of_date=date(2026, 9, 25))
    assert row["min_series_length"] == 12  # tenant override wins, not the platform default's 8


def test_missing_config_row_returns_none(two_tenants):
    tenant_a, _ = two_tenants
    row = resolve_anomaly_detection_config(tenant_a, metric="RETURN_RATE_PCT", method="PERCENTILE_THRESHOLD", as_of_date=date(2026, 9, 25))
    assert row is None


def test_latest_effective_from_wins(two_tenants):
    tenant_a, _ = two_tenants
    _insert(tenant_a, "FEE_RATIO_PCT", "PERIOD_OVER_PERIOD_DELTA", 5, effective_from="2026-01-01", version=1, delta_severity_bands='{"high": "3.0", "medium": "2.0", "low": "1.0"}')
    _insert(tenant_a, "FEE_RATIO_PCT", "PERIOD_OVER_PERIOD_DELTA", 6, effective_from="2026-06-01", version=2, delta_severity_bands='{"high": "3.0", "medium": "2.0", "low": "1.0"}')

    row = resolve_anomaly_detection_config(tenant_a, metric="FEE_RATIO_PCT", method="PERIOD_OVER_PERIOD_DELTA", as_of_date=date(2026, 9, 25))
    assert row["version"] == 2
    assert row["min_series_length"] == 6


def test_a_tenant_never_sees_another_tenants_row(two_tenants):
    tenant_a, tenant_b = two_tenants
    _insert(tenant_a, "MARGIN_PCT", "Z_SCORE", 20, z_score_threshold="4.000")

    row_b = resolve_anomaly_detection_config(tenant_b, metric="MARGIN_PCT", method="Z_SCORE", as_of_date=date(2026, 9, 25))
    assert row_b is None  # tenant_a's row is invisible to tenant_b; no platform default exists either
