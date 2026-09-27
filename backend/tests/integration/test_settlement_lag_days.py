"""`SETTLEMENT_LAG_DAYS` wired end-to-end through `run_leak_shield_reconciliation` and
`run_anomaly_check` — anomaly-detection.md §6.1/§6.6, closing §10 P1 ("no period-level
aggregate function anywhere in packages/calc-engine"). Real Postgres, real `reconcile()` (NOT
monkeypatched) — mirrors `packages/calc-engine/tests/integration/
test_reconcile_amazon_flipkart_extension.py`'s own seeding helpers.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

_AS_OF = date(2026, 1, 20)
_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_COMPUTED_AT = datetime(2026, 1, 20, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_reconciliation_tables(migrate_engine):
    tables = (
        "reconciliation_exception",
        "reconciliation_match",
        "reconciliation_run",
        "leak_finding",
        "metric_result",
        "line_component",
        "sales_line",
        "settlement_line",
        "ingestion_run",
        "report_file",
        "reconciliation_tolerance_config",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def _insert_report_file(tenant_id: uuid.UUID, *, marketplace: str) -> uuid.UUID:
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    file_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_file
                    (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                     byte_size, storage_uri, uploaded_by, uploaded_at)
                VALUES
                    (:id, :tenant_id, :marketplace, 'SETTLEMENT', :sha, 'synthetic.xlsx', 100,
                     's3://bucket/x', :uploaded_by, :uploaded_at)
                """
            ),
            {
                "id": str(file_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": datetime.now(timezone.utc),
            },
        )
    return file_id


def _insert_ingestion_run(tenant_id: uuid.UUID, *, marketplace: str) -> uuid.UUID:
    from data_foundation.repositories import ingestion_run_repo

    report_file_id = _insert_report_file(tenant_id, marketplace=marketplace)
    return ingestion_run_repo.insert_ingestion_run(
        tenant_id,
        report_file_id=report_file_id,
        adapter_id=f"{marketplace.lower()}.synthetic.v1",
        adapter_version="v1",
        started_at=datetime.now(timezone.utc),
    )


def _insert_sales_line(
    tenant_id: uuid.UUID,
    *,
    ingestion_run_id: uuid.UUID,
    marketplace: str,
    order_ref: str,
    line_ref: str | None = None,
    taxable_amount: int = 10_000,
    order_date: date = date(2026, 1, 5),
    confidence: str = "VERIFIED",
) -> uuid.UUID:
    from data_foundation.repositories import sales_line_repo

    return sales_line_repo.insert_sales_line(
        tenant_id,
        ingestion_run_id=ingestion_run_id,
        marketplace=marketplace,
        canonical_fields={
            "order_ref": order_ref,
            "line_ref": line_ref,
            "taxable_amount": taxable_amount,
            "order_date": order_date,
        },
        source_row_number=1,
        source_row_json={},
        confidence=confidence,
    )


def _insert_settlement_line(
    tenant_id: uuid.UUID,
    *,
    ingestion_run_id: uuid.UUID,
    marketplace: str,
    order_ref: str | None,
    line_ref: str | None = None,
    gross_settlement_amount: int | None,
    settlement_date_: date,
    confidence: str = "VERIFIED",
) -> uuid.UUID:
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    settlement_line_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO settlement_line
                    (id, tenant_id, ingestion_run_id, marketplace, order_ref, line_ref,
                     settlement_id, gross_settlement_amount, currency, settlement_date,
                     document_type, source_row_number, source_row_json, confidence)
                VALUES
                    (:id, :tenant_id, :ingestion_run_id, :marketplace, :order_ref, :line_ref,
                     NULL, :gross_settlement_amount, 'INR', :settlement_date,
                     'SETTLEMENT', 1, '{}'::jsonb, :confidence)
                """
            ),
            {
                "id": str(settlement_line_id),
                "tenant_id": str(tenant_id),
                "ingestion_run_id": str(ingestion_run_id),
                "marketplace": marketplace,
                "order_ref": order_ref,
                "line_ref": line_ref,
                "gross_settlement_amount": gross_settlement_amount,
                "settlement_date": settlement_date_,
                "confidence": confidence,
            },
        )
    return settlement_line_id


def _insert_component(
    tenant_id: uuid.UUID,
    *,
    sales_line_id: uuid.UUID | None,
    settlement_line_id: uuid.UUID | None,
    source_side: str,
    component_code: str,
    amount_paise: int,
) -> None:
    from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, :sales_line_id, :settlement_line_id, 'FEE', :component_code,
                     :source_side, :amount, NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "sales_line_id": str(sales_line_id) if sales_line_id else None,
                "settlement_line_id": str(settlement_line_id) if settlement_line_id else None,
                "component_code": component_code,
                "source_side": source_side,
                "amount": amount_paise,
            },
        )


def _insert_tolerance(
    tenant_id: uuid.UUID,
    *,
    marketplace: str,
    component_code: str,
    tolerance_paise: int,
    tolerance_bps: int,
    settlement_lag_days: int = 90,
    grace_period_days: int = 30,
) -> None:
    from calc_engine.repositories.tenant_context import tenant_scope as engine_tenant_scope

    with engine_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id, NULL, :marketplace, :component_code, :tolerance_paise, :tolerance_bps,
                     :settlement_lag_days, :grace_period_days, '2026-01-01', 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "marketplace": marketplace,
                "component_code": component_code,
                "tolerance_paise": tolerance_paise,
                "tolerance_bps": tolerance_bps,
                "settlement_lag_days": settlement_lag_days,
                "grace_period_days": grace_period_days,
            },
        )


def test_run_leak_shield_reconciliation_persists_a_real_settlement_lag_days_result(two_tenants):
    """Real `reconcile()`, real Meesho MATCHED_EXACT pair -> a real, available
    `SETTLEMENT_LAG_DAYS` `MetricResult`, threaded through `LeakShieldOutcome` and resolvable
    back via `metric_result_repo.get`."""
    from backend.services.cfo_actions import run_leak_shield_reconciliation
    from calc_engine.repositories import metric_result_repo

    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="MEESHO")

    sales_id = _insert_sales_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        order_ref="M-1",
        line_ref="M-1_1",
        order_date=date(2026, 1, 5),
    )
    _insert_component(
        tenant_a, sales_line_id=sales_id, settlement_line_id=None, source_side="INVOICE",
        component_code="COMMISSION", amount_paise=5_000,
    )
    _insert_tolerance(tenant_a, marketplace="MEESHO", component_code="COMMISSION", tolerance_paise=0, tolerance_bps=0)
    _insert_tolerance(tenant_a, marketplace="MEESHO", component_code="*", tolerance_paise=0, tolerance_bps=0)

    settlement_id = _insert_settlement_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        order_ref=None,
        line_ref="M-1_1",
        gross_settlement_amount=5_000,
        settlement_date_=date(2026, 1, 15),  # 10 days after order_date
    )
    _insert_component(
        tenant_a, sales_line_id=None, settlement_line_id=settlement_id, source_side="SETTLEMENT",
        component_code="COMMISSION", amount_paise=5_000,
    )

    outcome = run_leak_shield_reconciliation(
        tenant_a,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
    )

    assert outcome.match_count == 1
    assert outcome.settlement_lag_is_available is True
    assert outcome.settlement_lag_mean_days == "10"
    assert outcome.settlement_lag_pair_count == 1

    resolved = metric_result_repo.get(tenant_a, uuid.UUID(outcome.settlement_lag_engine_result_ref))
    assert resolved is not None
    assert resolved["metric_code"] == "SETTLEMENT_LAG_DAYS"
    assert resolved["value_fraction_numerator"] == 10
    assert resolved["value_fraction_denominator"] == 1
    assert resolved["confidence"] == "VERIFIED"


def test_run_anomaly_check_runs_against_real_settlement_lag_days_history(two_tenants):
    """Extends `run_anomaly_check` (E3's original MARGIN_PCT-only scope, generalized this
    checkpoint) to `SETTLEMENT_LAG_DAYS`: seeds two real `SETTLEMENT_LAG_DAYS` `metric_result`
    rows via a real `run_leak_shield_reconciliation` call per period, then confirms
    `run_anomaly_check(metric=METRIC_SETTLEMENT_LAG_DAYS)` finds that real history (no crash,
    no MARGIN_PCT-only special-casing) — with no `anomaly_detection_config` row seeded, every
    method reports a real `AnomalyConfigurationGap`, never a silently-assumed threshold."""
    from calc_engine.anomaly.types import METRIC_SETTLEMENT_LAG_DAYS
    from backend.services.cfo_actions import AnomalyCheckRequest, run_anomaly_check, run_leak_shield_reconciliation

    tenant_a, _ = two_tenants

    for month_start, month_end, order_date, settlement_date in (
        (date(2026, 1, 1), date(2026, 1, 31), date(2026, 1, 5), date(2026, 1, 15)),
        (date(2026, 2, 1), date(2026, 2, 28), date(2026, 2, 5), date(2026, 2, 20)),
    ):
        ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="MEESHO")
        line_ref = f"M-{order_date.isoformat()}_1"
        sales_id = _insert_sales_line(
            tenant_a,
            ingestion_run_id=ingestion_run_id,
            marketplace="MEESHO",
            order_ref=f"M-{order_date.isoformat()}",
            line_ref=line_ref,
            order_date=order_date,
        )
        _insert_component(
            tenant_a, sales_line_id=sales_id, settlement_line_id=None, source_side="INVOICE",
            component_code="COMMISSION", amount_paise=5_000,
        )
        _insert_tolerance(
            tenant_a, marketplace="MEESHO", component_code="COMMISSION", tolerance_paise=0, tolerance_bps=0,
        )
        _insert_tolerance(tenant_a, marketplace="MEESHO", component_code="*", tolerance_paise=0, tolerance_bps=0)
        settlement_id = _insert_settlement_line(
            tenant_a,
            ingestion_run_id=ingestion_run_id,
            marketplace="MEESHO",
            order_ref=None,
            line_ref=line_ref,
            gross_settlement_amount=5_000,
            settlement_date_=settlement_date,
        )
        _insert_component(
            tenant_a, sales_line_id=None, settlement_line_id=settlement_id, source_side="SETTLEMENT",
            component_code="COMMISSION", amount_paise=5_000,
        )

        run_leak_shield_reconciliation(
            tenant_a,
            marketplace="MEESHO",
            period_start=month_start,
            period_end=month_end,
            as_of_date=month_end,
        )

    request = AnomalyCheckRequest(
        target_ref="MEESHO",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        as_of_date=date(2026, 12, 31),
        requested_by=uuid.uuid4(),
        metric=METRIC_SETTLEMENT_LAG_DAYS,
    )
    outcome = run_anomaly_check(tenant_a, request)

    assert outcome.metric == METRIC_SETTLEMENT_LAG_DAYS
    assert outcome.series_length == 2  # both real SETTLEMENT_LAG_DAYS periods found
    for method_outcome in outcome.methods:
        # No anomaly_detection_config row seeded for SETTLEMENT_LAG_DAYS -> every method must
        # report a real configuration gap, never a silently-assumed threshold (E9/AC13).
        assert method_outcome.configuration_gap is not None
        assert method_outcome.configuration_gap.metric == METRIC_SETTLEMENT_LAG_DAYS
