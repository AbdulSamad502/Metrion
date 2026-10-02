"""`sales_lines_in_period` / `settlement_lines_in_period` gained an OPTIONAL `marketplace` filter
(perf: `reconcile()` and cash reconciliation fetched every marketplace's rows — including each
row's `source_row_json` — and discarded all but one in Python). The default must stay exactly as
before for every other caller (P&L, GST), and the scoped result must equal "fetch all, filter in
Python"."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from calc_engine.repositories import canonical_repo, settlement_repo
from data_foundation.repositories import ingestion_run_repo, report_file_repo, sales_line_repo, settlement_line_repo

pytestmark = [pytest.mark.usefixtures("_clean_engine_tables")]

_START, _END = date(2026, 1, 1), date(2026, 1, 31)


def _run(tenant_id: uuid.UUID, category: str) -> uuid.UUID:
    file_id = report_file_repo.insert_report_file(
        tenant_id, marketplace="MEESHO", report_category=category, content_sha256=uuid.uuid4().hex * 2,
        original_filename="f.csv", byte_size=1, storage_uri="file://x", uploaded_by=uuid.uuid4(),
        uploaded_at=datetime.now(timezone.utc),
    )
    return ingestion_run_repo.insert_ingestion_run(
        tenant_id, report_file_id=file_id, adapter_id="t", adapter_version="v1", started_at=datetime.now(timezone.utc)
    )


def _seed(tenant_id: uuid.UUID) -> None:
    sales_run, settle_run = _run(tenant_id, "TAX"), _run(tenant_id, "SETTLEMENT")
    for i, marketplace in enumerate(["MEESHO", "AMAZON", "FLIPKART", "MEESHO", "AMAZON", "MEESHO"]):
        # row 5 falls outside the period; row 3 has no dates at all (excluded by the period query either way)
        order_date = date(2026, 3, 1) if i == 5 else (None if i == 3 else date(2026, 1, 10 + i))
        sales_line_repo.insert_sales_line(
            tenant_id, ingestion_run_id=sales_run, marketplace=marketplace,
            canonical_fields={"order_ref": f"O{i}", "line_ref": f"L{i}", "order_date": order_date, "quantity": 1},
            source_row_number=i, source_row_json={}, confidence="VERIFIED",
        )
        settlement_line_repo.insert_settlement_line(
            tenant_id, ingestion_run_id=settle_run, marketplace=marketplace,
            canonical_fields={"order_ref": f"O{i}", "line_ref": f"L{i}", "gross_settlement_amount": 1000 + i,
                              "settlement_date": date(2026, 3, 1) if i == 5 else date(2026, 1, 12 + i)},
            source_row_number=i, source_row_json={}, confidence="VERIFIED",
        )


def _ids(rows, key):
    return sorted(str(r[key]) for r in rows)


def test_default_is_unchanged_and_returns_every_marketplace(two_tenants):
    tenant, _ = two_tenants
    _seed(tenant)
    sales = canonical_repo.sales_lines_in_period(tenant, period_start=_START, period_end=_END)
    settle = settlement_repo.settlement_lines_in_period(tenant, period_start=_START, period_end=_END)
    assert {r["marketplace"] for r in sales} == {"MEESHO", "AMAZON", "FLIPKART"}
    assert {r["marketplace"] for r in settle} == {"MEESHO", "AMAZON", "FLIPKART"}
    assert len(sales) == 4 and len(settle) == 5  # period + dateless exclusions still apply


@pytest.mark.parametrize("marketplace", ["MEESHO", "AMAZON", "FLIPKART", "SNAPDEAL"])
def test_scoped_result_equals_fetch_all_then_filter_in_python(two_tenants, marketplace):
    tenant, _ = two_tenants
    _seed(tenant)
    all_sales = canonical_repo.sales_lines_in_period(tenant, period_start=_START, period_end=_END)
    all_settle = settlement_repo.settlement_lines_in_period(tenant, period_start=_START, period_end=_END)

    scoped_sales = canonical_repo.sales_lines_in_period(tenant, period_start=_START, period_end=_END, marketplace=marketplace)
    scoped_settle = settlement_repo.settlement_lines_in_period(
        tenant, period_start=_START, period_end=_END, marketplace=marketplace
    )

    expected_sales = [r for r in all_sales if r["marketplace"] == marketplace]
    expected_settle = [r for r in all_settle if r["marketplace"] == marketplace]
    assert _ids(scoped_sales, "sales_line_id") == _ids(expected_sales, "sales_line_id")
    assert _ids(scoped_settle, "settlement_line_id") == _ids(expected_settle, "settlement_line_id")
    assert all(r["marketplace"] == marketplace for r in scoped_sales + scoped_settle)
    if marketplace != "SNAPDEAL":  # guard against both sides being trivially empty
        assert scoped_sales and scoped_settle


def test_scoped_query_never_crosses_tenants(two_tenants):
    tenant_a, tenant_b = two_tenants
    _seed(tenant_a)
    assert canonical_repo.sales_lines_in_period(tenant_b, period_start=_START, period_end=_END, marketplace="MEESHO") == []
    assert settlement_repo.settlement_lines_in_period(tenant_b, period_start=_START, period_end=_END, marketplace="MEESHO") == []
