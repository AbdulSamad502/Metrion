"""`backend.services.cfo_actions.compute_period_pnl_for_tenant` — cfo-agent.md §6.16, real
Postgres. The end-to-end proof that the ingestion-to-canonical composition layer actually
closes the gap: real `sales_line`/`line_component`/`manual_adjustment` rows in, a real
persisted `CONTRIBUTION_PROFIT` `MetricResult` out — with zero hand-assembled `CanonicalLine`s
anywhere in this test.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)
_AS_OF = date(2026, 9, 27)
_ORDER_DATE = date(2026, 9, 10)


@pytest.fixture
def migrate_engine():
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(migrate_engine):
    tables = (
        "manual_adjustment",
        "line_component",
        "sales_line",
        "ingestion_run",
        "report_file",
        "metric_result",
        "agent_data_request",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def _insert_report_file(tenant_id: uuid.UUID) -> uuid.UUID:
    from data_foundation.repositories.tenant_context import tenant_scope

    file_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_file
                    (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                     byte_size, storage_uri, uploaded_by, uploaded_at)
                VALUES
                    (:id, :tenant_id, 'MEESHO', 'TAX', :sha, 'synthetic.csv', 100,
                     'file://x', :uploaded_by, :uploaded_at)
                """
            ),
            {
                "id": str(file_id),
                "tenant_id": str(tenant_id),
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": datetime.now(timezone.utc),
            },
        )
    return file_id


def _insert_ingestion_run(tenant_id: uuid.UUID) -> uuid.UUID:
    from data_foundation.repositories import ingestion_run_repo

    report_file_id = _insert_report_file(tenant_id)
    return ingestion_run_repo.insert_ingestion_run(
        tenant_id,
        report_file_id=report_file_id,
        adapter_id="meesho.orders.v1",
        adapter_version="v1",
        started_at=datetime.now(timezone.utc),
    )


def _insert_sales_line(tenant_id: uuid.UUID, ingestion_run_id: uuid.UUID, *, sku: str) -> uuid.UUID:
    from data_foundation.repositories.sales_line_repo import insert_sales_line

    return insert_sales_line(
        tenant_id,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        canonical_fields={
            "order_ref": f"ORD-{uuid.uuid4().hex[:8]}",
            "quantity": 2,
            "gross_item_amount": 20_000,
            "taxable_amount": 20_000,
            "order_date": _ORDER_DATE,
            "return_status": "NOT_RETURNED",
            "sku": sku,
        },
        source_row_number=1,
        source_row_json={},
        confidence="PROVISIONAL",
    )


def _insert_invoice_component(tenant_id: uuid.UUID, sales_line_id: uuid.UUID, *, code: str, amount: int) -> None:
    from data_foundation.repositories.tenant_context import tenant_scope

    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, :sales_line_id, NULL, 'FEE', :code, 'INVOICE', :amount,
                     NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_id), "sales_line_id": str(sales_line_id), "code": code, "amount": amount},
        )


def _insert_cogs_per_unit(tenant_id: uuid.UUID, *, sku: str, amount_paise: int) -> None:
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment

    insert_adjustment(
        tenant_id,
        target_type="SKU",
        target_ref=sku,
        field="cogs_per_unit",
        value=amount_paise,
        created_by=uuid.uuid4(),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _insert_line_status_override(tenant_id: uuid.UUID, sales_line_id: uuid.UUID, *, field: str, value: str) -> None:
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment

    insert_adjustment(
        tenant_id,
        target_type="LINE",
        target_ref=str(sales_line_id),
        field=field,
        value=value,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )


def test_real_uploaded_data_produces_a_real_persisted_contribution_profit() -> None:
    import backend.services.cfo_actions as cfo_actions_module
    from calc_engine.types import RecognitionState

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)

    line_1 = _insert_sales_line(tenant_id, run_id, sku="SKU-001")
    _insert_invoice_component(tenant_id, line_1, code="COMMISSION", amount=2_000)
    line_2 = _insert_sales_line(tenant_id, run_id, sku="SKU-001")
    _insert_invoice_component(tenant_id, line_2, code="COMMISSION", amount=2_000)

    # Meesho's real "Return Status" column resolves return_status, but no adapter/column
    # anywhere resolves cancellation_state/rto_status (C1/C2) — the seller declares both here
    # via the §7.2.1 overrides this session added, exactly the real flow this closes end-to-end.
    for line_id in (line_1, line_2):
        _insert_line_status_override(tenant_id, line_id, field="cancellation_state_override", value="NOT_CANCELLED")
        _insert_line_status_override(tenant_id, line_id, field="rto_status_override", value="NOT_RTO")

    _insert_cogs_per_unit(tenant_id, sku="SKU-001", amount_paise=5_000)

    outcome = cfo_actions_module.compute_period_pnl_for_tenant(
        tenant_id,
        cfo_actions_module.PeriodPnlForTenantRequest(
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            as_of_date=_AS_OF,
            recognition_state=RecognitionState.RECOGNISED,
            fee_component_codes=frozenset({"COMMISSION"}),
            forward_logistics_codes=frozenset(),
            reverse_logistics_codes=frozenset(),
            non_refunded_fee_codes=frozenset(),
            requested_by=uuid.uuid4(),
        ),
    )

    assert outcome.blocked_lines == ()
    assert outcome.data_request_ids == ()
    assert outcome.assembled_line_count == 2
    assert outcome.pnl is not None

    pnl = outcome.pnl
    assert pnl.nrr.is_available
    # 2 lines x Rs.200.00 gross each, real return_status resolved "NOT_RETURNED" -> no reversal.
    assert pnl.nrr.value_paise == 40_000
    assert pnl.contribution_profit.is_available
    # Contribution Profit = NRR (40,000) - fees (2,000 + 2,000) - COGS (5,000 x 2 units x 2 lines = 20,000)
    assert pnl.contribution_profit.value_paise == 40_000 - 4_000 - 20_000

    # Real, persisted, independently re-readable — not just an in-memory result.
    from calc_engine.repositories import metric_result_repo

    persisted = metric_result_repo.get(tenant_id, pnl.contribution_profit.id)
    assert persisted is not None
    assert persisted["value_paise"] == pnl.contribution_profit.value_paise


def test_blocked_lines_raise_one_aggregated_data_request_not_one_per_line() -> None:
    import backend.services.cfo_actions as cfo_actions_module
    from calc_engine.types import RecognitionState

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)
    from data_foundation.repositories.sales_line_repo import insert_sales_line

    # Two lines, both confirmed RETURNED, neither with a known returned_qty -> both blocked,
    # same missing_inputs reason -> ONE data request, not two.
    for _ in range(2):
        insert_sales_line(
            tenant_id,
            ingestion_run_id=run_id,
            marketplace="MEESHO",
            canonical_fields={
                "order_ref": f"ORD-{uuid.uuid4().hex[:8]}",
                "quantity": 2,
                "gross_item_amount": 20_000,
                "taxable_amount": 20_000,
                "order_date": _ORDER_DATE,
                "return_status": "RETURNED",
            },
            source_row_number=1,
            source_row_json={},
            confidence="PROVISIONAL",
        )

    outcome = cfo_actions_module.compute_period_pnl_for_tenant(
        tenant_id,
        cfo_actions_module.PeriodPnlForTenantRequest(
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            as_of_date=_AS_OF,
            recognition_state=RecognitionState.RECOGNISED,
            fee_component_codes=frozenset(),
            forward_logistics_codes=frozenset(),
            reverse_logistics_codes=frozenset(),
            non_refunded_fee_codes=frozenset(),
            requested_by=uuid.uuid4(),
        ),
    )

    assert outcome.pnl is None
    assert outcome.assembled_line_count == 0
    assert len(outcome.blocked_lines) == 2
    assert len(outcome.data_request_ids) == 1  # aggregated, not one per blocked line

    from cfo.repositories.agent_data_request_repo import list_for_tenant

    rows = list_for_tenant(tenant_id)
    assert len(rows) == 1
    assert "2 sales_line row(s)" in rows[0]["reason"]
