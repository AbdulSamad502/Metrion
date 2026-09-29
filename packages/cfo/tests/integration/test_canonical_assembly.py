"""`backend.services.cfo_actions.assemble_canonical_lines_for_period` — cfo-agent.md §6.16
(the ingestion-to-canonical composition layer), real Postgres.

Fixtures insert real `sales_line`/`line_component`/`manual_adjustment` rows (the exact shapes
real adapters/`enter_expense`-style writers would produce) and call the composition function
for real — proving the whole "DB rows + manual_adjustment overlay -> real CanonicalLine" chain
works, not just its pieces in isolation.

Covers:
  - a fully-resolved line (real `return_status` column, real quantity/amount) assembles with no
    override needed at all.
  - `return_status_override`/`returned_qty_override`/`return_refund_amount` together fill a
    genuine gap (column NULL) end-to-end.
  - a line whose resolved status says a return occurred, with NO known unit count anywhere, is
    BLOCKED with a real reason — never silently zeroed.
  - a line missing `quantity` is BLOCKED — never silently defaulted.
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
_ORDER_DATE = date(2026, 9, 10)


@pytest.fixture
def migrate_engine():
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(migrate_engine):
    tables = ("manual_adjustment", "line_component", "sales_line", "ingestion_run", "report_file")
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


def _insert_sales_line(
    tenant_id: uuid.UUID,
    ingestion_run_id: uuid.UUID,
    *,
    quantity: int | None = 2,
    gross_item_amount: int | None = 10_000,
    return_status: str | None = "NOT_RETURNED",
    order_date: date = _ORDER_DATE,
    sku: str | None = None,
) -> uuid.UUID:
    from data_foundation.repositories.sales_line_repo import insert_sales_line

    return insert_sales_line(
        tenant_id,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        canonical_fields={
            "order_ref": f"ORD-{uuid.uuid4().hex[:8]}",
            "quantity": quantity,
            "gross_item_amount": gross_item_amount,
            "taxable_amount": gross_item_amount,
            "order_date": order_date,
            "return_status": return_status,
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


def _insert_manual_adjustment(
    tenant_id: uuid.UUID, *, target_ref: str, field: str, value: object
) -> None:
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment

    insert_adjustment(
        tenant_id,
        target_type="LINE",
        target_ref=target_ref,
        field=field,
        value=value,
        created_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
    )


def test_fully_resolved_line_assembles_with_no_override_needed() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)
    sales_line_id = _insert_sales_line(tenant_id, run_id, return_status="NOT_RETURNED")
    _insert_invoice_component(tenant_id, sales_line_id, code="COMMISSION", amount=500)

    outcome = cfo_actions_module.assemble_canonical_lines_for_period(
        tenant_id, period_start=_PERIOD_START, period_end=_PERIOD_END
    )

    assert outcome.blocked == ()
    assert len(outcome.lines) == 1
    line = outcome.lines[0]
    assert line.sales_line_id == sales_line_id
    assert line.return_status == "NOT_RETURNED"
    assert line.returned_qty == 0
    assert line.rto_status is None  # no adapter column, no override -> genuinely unresolved
    assert line.rto_qty == 0  # unresolved status is not evidence of RTO -> the dataclass's own default, never blocked
    assert line.quantity == 2
    assert line.gross_item_amount.value == 10_000
    assert len(line.components) == 1
    assert line.components[0].component_code == "COMMISSION"
    assert outcome.ingestion_run_ids == (run_id,)
    assert outcome.sku_by_line == {}  # no sku on this fixture's sales_line row


def test_overrides_fill_a_genuine_gap_end_to_end() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)
    # return_status column NULL — this marketplace/report carries no resolvable status at all.
    sales_line_id = _insert_sales_line(tenant_id, run_id, return_status=None)

    _insert_manual_adjustment(
        tenant_id, target_ref=str(sales_line_id), field="return_status_override", value="RETURNED"
    )
    _insert_manual_adjustment(
        tenant_id, target_ref=str(sales_line_id), field="returned_qty_override", value=1
    )
    _insert_manual_adjustment(
        tenant_id, target_ref=str(sales_line_id), field="return_refund_amount", value=9_500
    )

    outcome = cfo_actions_module.assemble_canonical_lines_for_period(
        tenant_id, period_start=_PERIOD_START, period_end=_PERIOD_END
    )

    assert outcome.blocked == ()
    assert len(outcome.lines) == 1
    line = outcome.lines[0]
    assert line.return_status == "RETURNED"
    assert line.returned_qty == 1
    assert line.refunded_amount is not None
    assert line.refunded_amount.value == 9_500
    assert len(outcome.active_adjustment_ids) == 1  # the return_refund_amount row actually applied


def test_return_confirmed_with_no_known_count_is_blocked_not_zeroed() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)
    # real column says RETURNED, but nothing anywhere says how many units.
    sales_line_id = _insert_sales_line(tenant_id, run_id, return_status="RETURNED")

    outcome = cfo_actions_module.assemble_canonical_lines_for_period(
        tenant_id, period_start=_PERIOD_START, period_end=_PERIOD_END
    )

    assert outcome.lines == ()
    assert len(outcome.blocked) == 1
    assert outcome.blocked[0].sales_line_id == sales_line_id
    assert "returned_qty_override" in outcome.blocked[0].missing_inputs


def test_missing_quantity_is_blocked_not_defaulted() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)
    sales_line_id = _insert_sales_line(tenant_id, run_id, quantity=None)

    outcome = cfo_actions_module.assemble_canonical_lines_for_period(
        tenant_id, period_start=_PERIOD_START, period_end=_PERIOD_END
    )

    assert outcome.lines == ()
    assert len(outcome.blocked) == 1
    assert outcome.blocked[0].sales_line_id == sales_line_id
    assert "quantity" in outcome.blocked[0].missing_inputs


def test_sku_by_line_is_derived_from_the_real_sales_line_column() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)
    sales_line_id = _insert_sales_line(tenant_id, run_id, sku="SKU-001")

    outcome = cfo_actions_module.assemble_canonical_lines_for_period(
        tenant_id, period_start=_PERIOD_START, period_end=_PERIOD_END
    )

    assert outcome.sku_by_line == {str(sales_line_id): "SKU-001"}


def test_lines_outside_the_period_are_not_assembled() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    run_id = _insert_ingestion_run(tenant_id)
    _insert_sales_line(tenant_id, run_id, order_date=date(2026, 1, 1))

    outcome = cfo_actions_module.assemble_canonical_lines_for_period(
        tenant_id, period_start=_PERIOD_START, period_end=_PERIOD_END
    )

    assert outcome.lines == ()
    assert outcome.blocked == ()
