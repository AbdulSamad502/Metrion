"""`SETTLEMENT_LAG_DAYS` end-to-end against real Postgres — anomaly-detection.md §6.1/§6.6,
closing §10 P1 ("no period-level aggregate function anywhere in packages/calc-engine").

Proves the full chain against REAL `reconcile()` output (not seeded/monkeypatched):
`reconcile()` -> real `reconciliation_match` rows -> `reconciliation_repo.
settlement_lag_pairs_for_run` -> `formulas.settlement_lag.settlement_lag_days_aggregate` ->
`compute_metric.compute_settlement_lag_days` -> a real `MetricResult`. Fixture style mirrors
`test_reconcile_amazon_flipkart_extension.py`'s own helpers exactly (same insert functions, same
`_clean_extension_tables` convention), so this file is deliberately close in shape to that one.

Assertions map to this checkpoint's own test list:
  (a) A Meesho run producing MATCHED_EXACT pairs yields a real, available SETTLEMENT_LAG_DAYS
      MetricResult with confidence VERIFIED (Meesho's real join-key ceiling).
  (b) An Amazon run producing MATCHED_EXACT/MATCHED_WITHIN_TOLERANCE pairs yields a
      SETTLEMENT_LAG_DAYS MetricResult capped at PROVISIONAL, even though the underlying rows
      are VERIFIED — proving the join-key confidence cap flows all the way through, not just in
      theory.
  (c) A run with zero matched pairs yields UNAVAILABLE, never a fabricated 0-day lag.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.api.compute_metric import compute_settlement_lag_days
from calc_engine.api.reconcile import reconcile
from calc_engine.formulas.settlement_lag import SettlementLagAggregate, settlement_lag_days_aggregate
from calc_engine.repositories import reconciliation_repo
from calc_engine.repositories.tenant_context import tenant_scope as engine_tenant_scope
from calc_engine.types import Unavailable
from data_foundation.repositories import ingestion_run_repo, sales_line_repo
from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

pytestmark = [pytest.mark.usefixtures("_clean_engine_tables")]

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_AS_OF = date(2026, 1, 20)
_COMPUTED_AT = datetime(2026, 1, 20, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_settlement_lag_tables(migrate_engine):
    tables = (
        "reconciliation_exception",
        "reconciliation_match",
        "reconciliation_run",
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


def _insert_settlement_component(
    tenant_id: uuid.UUID, *, settlement_line_id: uuid.UUID, component_code: str, amount_paise: int
) -> None:
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, NULL, :settlement_line_id, 'FEE', :component_code,
                     'SETTLEMENT', :amount, NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "settlement_line_id": str(settlement_line_id),
                "component_code": component_code,
                "amount": amount_paise,
            },
        )


def _insert_invoice_component(
    tenant_id: uuid.UUID, *, sales_line_id: uuid.UUID, component_code: str, amount_paise: int
) -> None:
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, :sales_line_id, NULL, 'FEE', :component_code,
                     'INVOICE', :amount, NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "sales_line_id": str(sales_line_id),
                "component_code": component_code,
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


def _run_settlement_lag_pipeline(tenant_id: uuid.UUID, reconciliation_run_id: uuid.UUID):
    """The real, end-to-end chain this checkpoint builds: repo fetch -> pure aggregate ->
    MetricResult minting — exactly what `run_leak_shield_reconciliation` now does, extracted
    here so each assertion below can inspect the aggregate AND the MetricResult separately."""
    pairs = reconciliation_repo.settlement_lag_pairs_for_run(tenant_id, reconciliation_run_id)
    aggregate = settlement_lag_days_aggregate(pairs)
    result = compute_settlement_lag_days(
        aggregate,
        reconciliation_run_id=reconciliation_run_id,
        computed_at=_COMPUTED_AT,
        as_of_date=_AS_OF,
    )
    return aggregate, result


# --- (a) Meesho: real MATCHED_EXACT pair -> real, available, VERIFIED SETTLEMENT_LAG_DAYS ----


def test_meesho_matched_pair_yields_verified_settlement_lag_days(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="MEESHO")

    sales_id = _insert_sales_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        order_ref="M-1",
        line_ref="M-1_1",
        order_date=date(2026, 1, 5),
        confidence="VERIFIED",
    )
    _insert_invoice_component(tenant_a, sales_line_id=sales_id, component_code="COMMISSION", amount_paise=5_000)
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
        confidence="VERIFIED",
    )
    _insert_settlement_component(tenant_a, settlement_line_id=settlement_id, component_code="COMMISSION", amount_paise=5_000)

    result = reconcile(
        tenant_a,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )
    assert result.match_count == 1

    aggregate, metric_result = _run_settlement_lag_pipeline(tenant_a, result.reconciliation_run_id)

    assert isinstance(aggregate, SettlementLagAggregate)
    assert aggregate.pair_count == 1
    assert aggregate.mean_lag_days == 10

    assert metric_result.metric_code == "SETTLEMENT_LAG_DAYS"
    assert metric_result.is_available is True
    assert metric_result.value_paise is None
    assert metric_result.value_fraction == 10
    assert metric_result.confidence == "VERIFIED"  # Meesho's real join-key ceiling


# --- (b) Amazon: real MATCHED pair -> SETTLEMENT_LAG_DAYS capped at PROVISIONAL --------------


def test_amazon_matched_pair_settlement_lag_days_capped_at_provisional(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="AMAZON")

    sales_id = _insert_sales_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="AMAZON",
        order_ref="AMZ-1",
        order_date=date(2026, 1, 3),
        confidence="VERIFIED",
    )
    _insert_invoice_component(tenant_a, sales_line_id=sales_id, component_code="COMMISSION", amount_paise=7_000)
    _insert_tolerance(tenant_a, marketplace="AMAZON", component_code="COMMISSION", tolerance_paise=0, tolerance_bps=0)
    _insert_tolerance(tenant_a, marketplace="AMAZON", component_code="*", tolerance_paise=0, tolerance_bps=0)

    settlement_id = _insert_settlement_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="AMAZON",
        order_ref="AMZ-1",
        gross_settlement_amount=7_000,
        settlement_date_=date(2026, 1, 18),  # 15 days after order_date
        confidence="VERIFIED",
    )
    _insert_settlement_component(tenant_a, settlement_line_id=settlement_id, component_code="COMMISSION", amount_paise=7_000)

    result = reconcile(
        tenant_a,
        marketplace="AMAZON",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )
    assert result.match_count == 1

    aggregate, metric_result = _run_settlement_lag_pipeline(tenant_a, result.reconciliation_run_id)

    assert isinstance(aggregate, SettlementLagAggregate)
    assert aggregate.pair_count == 1
    assert aggregate.mean_lag_days == 15
    # Every contributing pair's own confidence is already PROVISIONAL (reconcile()'s own
    # join-key cap, deterministic-engine.md §5.12.2) even though the underlying rows were
    # inserted as VERIFIED — proving the cap flows through reconciliation_match itself.
    assert aggregate.confidences == ("PROVISIONAL",)

    assert metric_result.is_available is True
    assert metric_result.confidence == "PROVISIONAL"  # never better, despite VERIFIED inputs


# --- (c) Zero matched pairs -> UNAVAILABLE, never a fabricated 0-day lag ---------------------


def test_zero_matched_pairs_yields_unavailable_never_a_fabricated_zero(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="MEESHO")
    # An orphan settlement row -- no matching sales_line at all, so match_count == 0.
    _insert_settlement_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        order_ref=None,
        line_ref="M-ORPHAN",
        gross_settlement_amount=1_000,
        settlement_date_=date(2026, 1, 15),
    )

    result = reconcile(
        tenant_a,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )
    assert result.match_count == 0

    aggregate, metric_result = _run_settlement_lag_pipeline(tenant_a, result.reconciliation_run_id)

    assert isinstance(aggregate, Unavailable)
    assert metric_result.is_available is False
    assert metric_result.value_paise is None
    assert metric_result.value_fraction is None
    assert metric_result.unavailable_reason is not None
