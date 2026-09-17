"""resolve_reconciliation_tolerance / severity_config_rows (§5.12.1, §5.14.1) against a real
Postgres — resolution order (tenant beats platform, exact component_code beats '*') is proven
here, not assumed from the SQL alone.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from calc_engine.repositories.config_repo import (
    resolve_reconciliation_tolerance,
    severity_config_rows,
)
from calc_engine.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")


def _insert_tolerance(tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps, effective_from="2026-01-01"):
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id, :tenant_id, :marketplace, :component_code, :tolerance_paise, :tolerance_bps, 14, 5, :effective_from, 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id) if tenant_id else None,
                "marketplace": marketplace,
                "component_code": component_code,
                "tolerance_paise": tolerance_paise,
                "tolerance_bps": tolerance_bps,
                "effective_from": effective_from,
            },
        )


def test_exact_component_code_beats_wildcard(two_tenants):
    tenant_a, _ = two_tenants
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id1, NULL, 'AMAZON', '*', 100, 50, 14, 5, '2026-01-01', 1),
                    (:id2, NULL, 'AMAZON', 'PLATFORM_FEE', 20, 10, 14, 5, '2026-01-01', 1)
                """
            ),
            {"id1": str(uuid.uuid4()), "id2": str(uuid.uuid4())},
        )

    row = resolve_reconciliation_tolerance(tenant_a, marketplace="AMAZON", component_code="PLATFORM_FEE", as_of_date=date(2026, 9, 17))
    assert row["tolerance_paise"] == 20  # exact match, not the wildcard's 100

    row_other = resolve_reconciliation_tolerance(tenant_a, marketplace="AMAZON", component_code="SHIPPING_CHARGE", as_of_date=date(2026, 9, 17))
    assert row_other["tolerance_paise"] == 100  # falls back to wildcard


def test_tenant_override_beats_platform_default(two_tenants):
    tenant_a, _ = two_tenants
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id1, NULL, 'MEESHO', 'COMMISSION_FEE', 50, 10, 14, 5, '2026-01-01', 1),
                    (:id2, :tenant_id, 'MEESHO', 'COMMISSION_FEE', 200, 100, 14, 5, '2026-01-01', 1)
                """
            ),
            {"id1": str(uuid.uuid4()), "id2": str(uuid.uuid4()), "tenant_id": str(tenant_a)},
        )

    row = resolve_reconciliation_tolerance(tenant_a, marketplace="MEESHO", component_code="COMMISSION_FEE", as_of_date=date(2026, 9, 17))
    assert row["tolerance_paise"] == 200  # tenant override wins


def test_missing_tolerance_row_returns_none(two_tenants):
    tenant_a, _ = two_tenants
    row = resolve_reconciliation_tolerance(tenant_a, marketplace="FLIPKART", component_code="PLATFORM_FEE", as_of_date=date(2026, 9, 17))
    assert row is None


def test_severity_config_rows_returns_latest_per_metric(two_tenants):
    tenant_a, _ = two_tenants
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO severity_config
                    (id, tenant_id, metric, high_threshold, medium_threshold, window_closing_soon_days,
                     ordering_basis, version, effective_from)
                VALUES
                    (:id1, NULL, 'AMOUNT_PAISE', 100000, 10000, 14, 'WINDOW_THEN_AMOUNT', 1, '2026-01-01'),
                    (:id2, NULL, 'AGE_DAYS', 60, 30, 14, 'WINDOW_THEN_AMOUNT', 1, '2026-01-01')
                """
            ),
            {"id1": str(uuid.uuid4()), "id2": str(uuid.uuid4())},
        )

    rows = severity_config_rows(tenant_a, as_of_date=date(2026, 9, 17))
    metrics = {r["metric"] for r in rows}
    assert metrics == {"AMOUNT_PAISE", "AGE_DAYS"}
