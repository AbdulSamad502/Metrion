"""`calc_engine.api.reconcile.reconcile` against REAL ingested Meesho data — real Payments
workbook + real `tcs_sales.xlsx`, run through the real ingestion pipeline
(`data_foundation.ingestion.pipeline.run_ingestion`), the real `meesho.tcs_sales.v1` /
`meesho.payments.v1` adapters, and real persistence (`sales_line_repo.insert_sales_line` for
the sales side; raw SQL for `settlement_line`/`line_component` on the settlement side, mirroring
`tests/integration/test_settlement_repo.py::_insert_settlement_line`'s own pattern — no
`settlement_line_repo` module exists in this codebase, out of scope to add here).

Three real rows join on `sub_order_num`/`line_ref`: `239871537625475904_1`,
`240849400556604608_1`, `244352098423318720_1`. Six more real `tcs_sales.xlsx` rows have no
corresponding settlement row in this Payments file: `246865984816980480_1`,
`240700366923023424_1`, `242637300059658752_1`, `242613738627306496_1`,
`244823982080303616_1`, `239267741698403136_1`.

Requires a live Postgres with both calc-engine's and data-foundation's migrations applied
(skipped automatically otherwise, via this directory's own conftest.py).

**`settlement_line.settlement_date` — real data, not invented.** No adapter in this codebase
maps any column on the Payments workbook to `settlement_date` (`meesho_payments_v1.py`'s own
`date_formats={}` — "§2.4 gives only the value format... never a column header"). This test
therefore reads the real "Order Date" column directly (not through the adapter, since the
adapter itself doesn't bind it) and uses it as `settlement_date` for the raw-SQL insert — a
real value from the real file, not a fabricated one, needed only because
`settlement_lines_in_period()` filters on `settlement_date BETWEEN period_start AND period_end`
and a NULL would silently exclude these real rows from the query the assertions below depend on.
"""

from __future__ import annotations

import uuid
import warnings
from datetime import date, datetime, timezone

import openpyxl
import pandas as pd
import pytest
from sqlalchemy import text

from calc_engine.api.reconcile import reconcile
from calc_engine.repositories.tenant_context import tenant_scope as engine_tenant_scope
from data_foundation.adapters import meesho_payments_v1, meesho_tcs_sales_v1
from data_foundation.ingestion.pipeline import run_ingestion
from data_foundation.repositories import ingestion_run_repo, sales_line_repo
from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope
from data_foundation.types import FileSample, RawFile

pytestmark = [pytest.mark.usefixtures("_clean_engine_tables")]

_PAYMENTS_PATH = (
    r"C:\Users\ABDULS~1\AppData\Local\Temp\claude\C--Users-ABDUL-SAMAD-Desktop-Metrion"
    r"\db95d1bb-7e64-4a1c-b28d-bbf9f608f9ea\scratchpad\meesho_export\payments"
    r"\3609938_SP_ORDER_ADS_REFERRAL_PAYMENT_FILE_PREVIOUS_PAYMENT_2026-01-01_2026-01-31.xlsx"
)
_TCS_SALES_PATH = (
    r"C:\Users\ABDULS~1\AppData\Local\Temp\claude\C--Users-ABDUL-SAMAD-Desktop-Metrion"
    r"\db95d1bb-7e64-4a1c-b28d-bbf9f608f9ea\scratchpad\meesho_export\gst\tcs_sales.xlsx"
)

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_AS_OF = date(2026, 9, 25)  # today — deliberately far past any real settlement lag


def _insert_report_file(tenant_id: uuid.UUID, *, marketplace: str, report_category: str, filename: str) -> uuid.UUID:
    file_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_file
                    (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                     byte_size, storage_uri, uploaded_by, uploaded_at)
                VALUES
                    (:id, :tenant_id, :marketplace, :report_category, :sha, :filename, 100,
                     's3://bucket/x', :uploaded_by, :uploaded_at)
                """
            ),
            {
                "id": str(file_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "report_category": report_category,
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                "filename": filename,
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": datetime.now(timezone.utc),
            },
        )
    return file_id


def _insert_settlement_line(
    tenant_id: uuid.UUID,
    *,
    ingestion_run_id: uuid.UUID,
    line_ref: str,
    gross_settlement_amount: int,
    settlement_date_: date,
    confidence: str,
    source_row_number: int,
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
                    (:id, :tenant_id, :ingestion_run_id, 'MEESHO', NULL, :line_ref,
                     NULL, :gross_settlement_amount, 'INR', :settlement_date,
                     'Order Payments', :source_row_number, '{}'::jsonb, :confidence)
                """
            ),
            {
                "id": str(settlement_line_id),
                "tenant_id": str(tenant_id),
                "ingestion_run_id": str(ingestion_run_id),
                "line_ref": line_ref,
                "gross_settlement_amount": gross_settlement_amount,
                "settlement_date": settlement_date_,
                "source_row_number": source_row_number,
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
                     'SETTLEMENT', :amount, NULL, NULL, 'Fixed Fee (Incl. GST)', false, NULL)
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


def _load_tcs_sales_raw_file() -> tuple[FileSample, RawFile]:
    warnings.filterwarnings("ignore", category=UserWarning)  # openpyxl "no default style" noise
    df = pd.read_excel(_TCS_SALES_PATH)
    columns = tuple(df.columns.tolist())
    rows = [
        {c: ("" if pd.isna(v) else str(v)) for c, v in row.items()}
        for _, row in df.iterrows()
    ]
    return FileSample(columns=columns), RawFile(columns=columns, rows=rows)


def _load_payments_raw_file() -> tuple[FileSample, RawFile, list[object]]:
    """openpyxl, NOT pandas — pandas silently renames the real duplicate "Fixed Fee (Incl.
    GST)" header, hiding the exact ambiguity `meesho_payments_v1.py` was built to handle.
    Header row is index 1, formula-letter row is index 2, data starts at index 3 (real
    workbook shape, verified by direct inspection this session)."""
    warnings.filterwarnings("ignore", category=UserWarning)
    wb = openpyxl.load_workbook(_PAYMENTS_PATH, data_only=True)
    ws = wb["Order Payments"]
    all_rows = list(ws.iter_rows(values_only=True))
    header = all_rows[1]
    data_rows = all_rows[3:]

    order_dates: list[object] = []
    rows: list[list[tuple[str, str]]] = []
    for row in data_rows:
        pairs = [(header[i], "" if row[i] is None else str(row[i])) for i in range(len(header))]
        rows.append(pairs)
        order_dates.append(row[1])  # "Order Date" column, index 1 — real value, not the adapter's

    return FileSample(columns=tuple(header)), RawFile(columns=tuple(header), rows=rows), order_dates


@pytest.fixture(autouse=True)
def _clean_data_foundation_tables(migrate_engine):
    """This test's own real-data tables aren't covered by calc-engine's `_clean_engine_tables`
    fixture (data-foundation-owned + this session's new reconciliation_* tables) — cleaned
    before and after, same convention."""
    tables = (
        "reconciliation_exception",
        "reconciliation_match",
        "reconciliation_run",
        "line_component",
        "sales_line",
        "settlement_line",
        "ingestion_run",
        "report_file",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def test_reconcile_against_real_meesho_export(two_tenants):
    tenant_a, _ = two_tenants

    # --- sales side: real tcs_sales.xlsx through the real pipeline + real adapter ------------
    sales_sample, sales_raw = _load_tcs_sales_raw_file()
    sales_adapter = meesho_tcs_sales_v1.adapter
    detection = sales_adapter.detect(sales_sample)
    assert detection.matched, detection.missing_columns

    sales_result = run_ingestion(sales_adapter, sales_sample, sales_raw, required_fields=(), plausible_gst_rates=frozenset())
    assert sales_result.row_count_read == 9
    assert sales_result.row_count_accepted == 9  # verified this session: none quarantined

    sales_report_file_id = _insert_report_file(
        tenant_a, marketplace="MEESHO", report_category="TAX", filename="tcs_sales.xlsx"
    )
    sales_run_id = ingestion_run_repo.insert_ingestion_run(
        tenant_a,
        report_file_id=sales_report_file_id,
        adapter_id=sales_adapter.adapter_id,
        adapter_version=sales_adapter.format_version,
        started_at=datetime.now(timezone.utc),
    )
    for row_result in sales_result.row_results:
        if row_result.quarantined:
            continue
        sales_line_repo.insert_sales_line(
            tenant_a,
            ingestion_run_id=sales_run_id,
            marketplace="MEESHO",
            canonical_fields=row_result.row.canonical_fields,
            source_row_number=row_result.row.source_row_number,
            source_row_json=row_result.row.source_row_json,
            confidence=row_result.confidence.value,
        )

    # --- settlement side: real Payments workbook through the real pipeline + real adapter ----
    settlement_sample, settlement_raw, order_dates = _load_payments_raw_file()
    settlement_adapter = meesho_payments_v1.adapter
    detection2 = settlement_adapter.detect(settlement_sample)
    assert detection2.matched, detection2.missing_columns

    settlement_result = run_ingestion(
        settlement_adapter, settlement_sample, settlement_raw, required_fields=(), plausible_gst_rates=frozenset()
    )
    assert settlement_result.row_count_read == 3
    assert settlement_result.row_count_accepted == 3  # verified this session: none quarantined

    settlement_report_file_id = _insert_report_file(
        tenant_a, marketplace="MEESHO", report_category="SETTLEMENT", filename="payments.xlsx"
    )
    settlement_run_id = ingestion_run_repo.insert_ingestion_run(
        tenant_a,
        report_file_id=settlement_report_file_id,
        adapter_id=settlement_adapter.adapter_id,
        adapter_version=settlement_adapter.format_version,
        started_at=datetime.now(timezone.utc),
    )
    for row_result, order_date in zip(settlement_result.row_results, order_dates):
        if row_result.quarantined:
            continue
        canonical = row_result.row.canonical_fields
        settlement_line_id = _insert_settlement_line(
            tenant_a,
            ingestion_run_id=settlement_run_id,
            line_ref=canonical["line_ref"],
            gross_settlement_amount=canonical["gross_settlement_amount"],
            settlement_date_=order_date.date() if hasattr(order_date, "date") else order_date,
            confidence=row_result.confidence.value,
            source_row_number=row_result.row.source_row_number,
        )
        for component in row_result.row.components:
            _insert_settlement_component(
                tenant_a,
                settlement_line_id=settlement_line_id,
                component_code=component.component_code,
                amount_paise=component.amount_paise,
            )

    # --- real reconcile() ---------------------------------------------------------------------
    result = reconcile(
        tenant_a,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=datetime.now(timezone.utc),
    )

    with engine_tenant_scope(tenant_a) as conn:
        run_row = conn.execute(
            text("SELECT * FROM reconciliation_run WHERE id = :id"), {"id": str(result.reconciliation_run_id)}
        ).mappings().first()
        match_rows = conn.execute(text("SELECT * FROM reconciliation_match")).mappings().all()
        exception_rows = conn.execute(text("SELECT * FROM reconciliation_exception")).mappings().all()

    assert run_row is not None
    assert run_row["status"] == "COMPLETE"
    assert run_row["settlement_line_count"] == 3
    assert run_row["sales_line_count"] == 9

    # Decision A, confirmed-expected: no adapter in this codebase produces INVOICE-side
    # line_component rows at all — meesho_tcs_sales_v1.py maps zero component_codes. The 3
    # real matched pairs therefore have zero shared component_codes between the two sides,
    # so classify_variance() is never invoked and zero reconciliation_match rows are written.
    assert result.match_count == 0
    assert len(match_rows) == 0

    # Consequently: zero VARIANCE_EXCEEDS_TOLERANCE exceptions (no match rows exist to exceed
    # tolerance from).
    variance_exceptions = [r for r in exception_rows if r["exception_type"] == "VARIANCE_EXCEEDS_TOLERANCE"]
    assert variance_exceptions == []

    # Decision B, confirmed-expected: meesho_tcs_sales_v1.py maps no date column at all, so all
    # 6 real unmatched sales_lines have invoice_date/dispatch_date/order_date all None —
    # resolve_document_date() is never called for them, they are counted and skipped instead.
    assert result.dates_missing_count == 6
    unsettled_exceptions = [r for r in exception_rows if r["exception_type"] == "UNSETTLED_BEYOND_LAG"]
    assert unsettled_exceptions == []

    # Every one of the 3 real settlement rows here has exactly one real single match — no
    # collisions, no duplicates, no orphans in this real dataset.
    orphan_exceptions = [r for r in exception_rows if r["exception_type"] == "ORPHAN_SETTLEMENT"]
    duplicate_exceptions = [r for r in exception_rows if r["exception_type"] == "DUPLICATE_SETTLEMENT"]
    ambiguous_exceptions = [r for r in exception_rows if r["exception_type"] == "AMBIGUOUS_MATCH"]
    assert orphan_exceptions == []
    assert duplicate_exceptions == []
    assert ambiguous_exceptions == []

    assert result.exception_count == 0
    assert len(exception_rows) == 0
    assert result.aggregate_metric_result.value_paise == 0
