"""`calc_engine.api.cash_reconciliation.cash_reconciliation` — deterministic-engine.md §5.13.3,
against a real Postgres.

Mirrors `test_reconcile_amazon_flipkart_extension.py`'s fixture conventions exactly (synthetic
rows shaped to match each real adapter's actual output, inserted directly via the same real
repositories/raw SQL — no adapter is actually run here).

Covers:
  (a) CASH_RECEIVED sums real settlement_line.gross_settlement_amount rows; a null amount
      (Amazon's real shape) is excluded, never treated as a zero contribution.
  (b) CASH_RECEIVED is UNAVAILABLE (not a fabricated zero) when no settlement_line exists at all.
  (c) CASH_EXPECTED/CASH_VARIANCE are structurally UNAVAILABLE for every marketplace, always,
      this pass — the core, disclosed scope limit this checkpoint's spec extension names.
  (d) TCS_COLLECTED is real for FLIPKART (sums invoice-side component_code='TCS' rows) and
      structurally UNAVAILABLE for MEESHO/AMAZON (no adapter maps that component there).
  (e) TDS_DEDUCTED is UNAVAILABLE for every marketplace, always, this pass.
  (f) Timing counts: a sales_line with no matching settlement, well within the configured lag,
      counts as settled_within_lag; past lag+grace, counts as unsettled_beyond_lag; an
      already-settled sales_line (shares a settlement's join key) is excluded from both counts.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.api.cash_reconciliation import cash_reconciliation
from calc_engine.repositories.tenant_context import tenant_scope as engine_tenant_scope
from data_foundation.repositories import ingestion_run_repo, sales_line_repo
from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

pytestmark = [pytest.mark.usefixtures("_clean_engine_tables")]

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_AS_OF = date(2026, 1, 20)
_COMPUTED_AT = datetime(2026, 1, 20, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_extension_tables(migrate_engine):
    tables = (
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
    order_date: date = date(2026, 1, 10),
    confidence: str = "VERIFIED",
) -> uuid.UUID:
    return sales_line_repo.insert_sales_line(
        tenant_id,
        ingestion_run_id=ingestion_run_id,
        marketplace=marketplace,
        canonical_fields={"order_ref": order_ref, "line_ref": line_ref, "order_date": order_date},
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
                    (:id, :tenant_id, :sales_line_id, NULL, 'TAX', :component_code,
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
    settlement_lag_days: int = 90,
    grace_period_days: int = 30,
) -> None:
    from tests.integration.owner_db import owner_tenant_scope  # configuration is written by an operator (owner role), not the app role

    with owner_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id, NULL, :marketplace, '*', 0, 0, :settlement_lag_days, :grace_period_days,
                     '2026-01-01', 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "marketplace": marketplace,
                "settlement_lag_days": settlement_lag_days,
                "grace_period_days": grace_period_days,
            },
        )


# --- (a)/(b) CASH_RECEIVED --------------------------------------------------------------------


def test_cash_received_sums_real_settlement_amounts_excluding_null(two_tenants):
    tenant_a, _ = two_tenants
    run_id = _insert_ingestion_run(tenant_a, marketplace="AMAZON")
    _insert_tolerance(tenant_a, marketplace="AMAZON")

    _insert_settlement_line(
        tenant_a, ingestion_run_id=run_id, marketplace="AMAZON", order_ref="A-1",
        gross_settlement_amount=5_000, settlement_date_=date(2026, 1, 15),
    )
    _insert_settlement_line(
        tenant_a, ingestion_run_id=run_id, marketplace="AMAZON", order_ref="A-2",
        gross_settlement_amount=3_000, settlement_date_=date(2026, 1, 16),
    )
    _insert_settlement_line(
        tenant_a, ingestion_run_id=run_id, marketplace="AMAZON", order_ref="A-3",
        gross_settlement_amount=None, settlement_date_=date(2026, 1, 17),
    )

    result = cash_reconciliation(
        tenant_a, marketplace="AMAZON", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    assert result.cash_received.is_available is True
    assert result.cash_received.value_paise == 8_000


def test_cash_received_unavailable_when_no_settlement_lines_exist(two_tenants):
    tenant_a, _ = two_tenants
    _insert_tolerance(tenant_a, marketplace="MEESHO")

    result = cash_reconciliation(
        tenant_a, marketplace="MEESHO", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    assert result.cash_received.is_available is False
    assert result.cash_received.value_paise is None
    assert result.cash_received.unavailable_reason is not None


# --- (c) CASH_EXPECTED / CASH_VARIANCE — structurally UNAVAILABLE, always -----------------------


@pytest.mark.parametrize("marketplace", ["MEESHO", "AMAZON", "FLIPKART"])
def test_cash_expected_and_variance_structurally_unavailable(two_tenants, marketplace):
    tenant_a, _ = two_tenants
    _insert_tolerance(tenant_a, marketplace=marketplace)

    result = cash_reconciliation(
        tenant_a, marketplace=marketplace, period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    assert result.cash_expected.is_available is False
    assert "invoice-side marketplace-fee component" in result.cash_expected.unavailable_reason
    assert result.cash_variance.is_available is False


# --- (d) TCS_COLLECTED — real for FLIPKART, UNAVAILABLE elsewhere -------------------------------


def test_tcs_collected_sums_flipkart_invoice_side_component(two_tenants):
    tenant_a, _ = two_tenants
    run_id = _insert_ingestion_run(tenant_a, marketplace="FLIPKART")
    _insert_tolerance(tenant_a, marketplace="FLIPKART")

    sales_id_1 = _insert_sales_line(tenant_a, ingestion_run_id=run_id, marketplace="FLIPKART", order_ref="FK-1")
    _insert_invoice_component(tenant_a, sales_line_id=sales_id_1, component_code="TCS", amount_paise=50)
    sales_id_2 = _insert_sales_line(tenant_a, ingestion_run_id=run_id, marketplace="FLIPKART", order_ref="FK-2")
    _insert_invoice_component(tenant_a, sales_line_id=sales_id_2, component_code="TCS", amount_paise=75)

    result = cash_reconciliation(
        tenant_a, marketplace="FLIPKART", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    assert result.tcs_collected.is_available is True
    assert result.tcs_collected.value_paise == 125


def test_tcs_collected_unavailable_for_meesho_and_amazon(two_tenants):
    tenant_a, _ = two_tenants
    for marketplace in ("MEESHO", "AMAZON"):
        _insert_tolerance(tenant_a, marketplace=marketplace)
        result = cash_reconciliation(
            tenant_a, marketplace=marketplace, period_start=_PERIOD_START, period_end=_PERIOD_END,
            as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
        )
        assert result.tcs_collected.is_available is False, marketplace
        assert "TCS component" in result.tcs_collected.unavailable_reason


# --- (e) TDS_DEDUCTED — UNAVAILABLE for every marketplace ---------------------------------------


@pytest.mark.parametrize("marketplace", ["MEESHO", "AMAZON", "FLIPKART"])
def test_tds_deducted_always_unavailable(two_tenants, marketplace):
    tenant_a, _ = two_tenants
    _insert_tolerance(tenant_a, marketplace=marketplace)

    result = cash_reconciliation(
        tenant_a, marketplace=marketplace, period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    assert result.tds_deducted.is_available is False


# --- (f) timing counts ---------------------------------------------------------------------------


def test_timing_within_lag_beyond_lag_and_already_settled(two_tenants):
    tenant_a, _ = two_tenants
    run_id = _insert_ingestion_run(tenant_a, marketplace="MEESHO")
    # as_of_date = 2026-01-20; lag=10, grace=5 -> beyond lag+grace at day 16+.
    _insert_tolerance(tenant_a, marketplace="MEESHO", settlement_lag_days=10, grace_period_days=5)

    # Within lag: ordered 2026-01-15, as_of 2026-01-20 -> elapsed 5 days <= 10.
    _insert_sales_line(
        tenant_a, ingestion_run_id=run_id, marketplace="MEESHO", order_ref="M-WITHIN", line_ref="M-WITHIN_1",
        order_date=date(2026, 1, 15),
    )
    # Beyond lag+grace: ordered 2026-01-03, as_of 2026-01-20 -> elapsed 17 days > 10+5=15.
    # Stays within the period_start..period_end window (2026-01-01..2026-01-31) so
    # sales_lines_in_period's own coalesce(...)-BETWEEN filter still includes it.
    _insert_sales_line(
        tenant_a, ingestion_run_id=run_id, marketplace="MEESHO", order_ref="M-BEYOND", line_ref="M-BEYOND_1",
        order_date=date(2026, 1, 3),
    )
    # Already settled: has a real settlement row sharing its join key (line_ref for MEESHO) ->
    # excluded from both timing counts regardless of its own order_date.
    _insert_sales_line(
        tenant_a, ingestion_run_id=run_id, marketplace="MEESHO", order_ref="M-SETTLED", line_ref="M-SETTLED_1",
        order_date=date(2026, 1, 2),
    )
    _insert_settlement_line(
        tenant_a, ingestion_run_id=run_id, marketplace="MEESHO", order_ref=None, line_ref="M-SETTLED_1",
        gross_settlement_amount=1_000, settlement_date_=date(2026, 1, 5),
    )

    result = cash_reconciliation(
        tenant_a, marketplace="MEESHO", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    assert result.settled_within_lag_count == 1
    assert result.unsettled_beyond_lag_count == 1
