"""Legacy equivalence across EVERY registered adapter (cfo-data-intelligence.md AC-D2): for the same file, the streaming path must
produce exactly what the legacy whole-file path produces — the same counts, the same persisted rows and components, the same
rejected-row findings — or fail the same way. Real Postgres. Files are synthesised from each adapter's own column map (synthetic
values, clearly not seller data)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from fractions import Fraction  # noqa: E402

from data_foundation.adapters.registry import ADAPTER_REGISTRY  # noqa: E402
from data_foundation.ingestion.file_reader import read_csv_file  # noqa: E402
from data_foundation.ingestion.persist import ingest_and_persist  # noqa: E402
from data_foundation.ingestion.pipeline import RunQuarantineThresholdExceeded  # noqa: E402
from data_foundation.ingestion.stream_persist import ingest_stream_and_persist  # noqa: E402
from data_foundation.ingestion.streaming import StreamLimits, open_csv  # noqa: E402
from data_foundation.repositories.tenant_context import tenant_scope  # noqa: E402

LIM = StreamLimits(chunk_rows=7, max_rows=100_000, header_scan_rows=30, min_header_fill=Fraction(6, 10),
                   max_uncompressed_bytes=50 * 1024 * 1024, max_zip_ratio=200, max_zip_members=200, max_sheets=20)  # tiny chunks: many chunk boundaries
N = 60
_MONEY_CANONICAL = {"gross_item_amount", "taxable_amount", "total_invoice_amount", "gross_settlement_amount", "total_sale_amount", "settlement_amount_value",
                    "component_amount", "_ignored_legacy_tax_column"}


def headers_of(adapter) -> list[str]:  # type: ignore[no-untyped-def]
    seen: list[str] = []
    for key in adapter.column_map:
        h = key[0] if isinstance(key, tuple) else key
        if h not in seen:
            seen.append(h)
    return seen


def cell(adapter, header: str, i: int) -> str:  # type: ignore[no-untyped-def]
    binding = next(b for k, b in adapter.column_map.items() if (k[0] if isinstance(k, tuple) else k) == header)
    cf = binding.canonical_field
    if binding.component_code is not None:
        return f"{5 + i % 9}.50"
    if cf in _MONEY_CANONICAL:
        return f"{100 + i}.00"
    if cf in adapter.enum_maps:
        # a mapped enum value when the adapter has any; otherwise a plain value, which exercises the unmapped-value warning path
        return next(iter(adapter.enum_maps[cf]), f"{cf}-unmapped")
    if cf.endswith("_date") or cf == "cancel_return_date":
        return f"2026-10-{1 + i % 27:02d}"
    if cf == "gst_rate":
        return "18"
    if cf in ("order_ref", "line_ref", "settlement_id", "merchant_order_id", "merchant_order_item_id", "order_item_code", "shipment_id"):
        return f"{cf[:3].upper()}-{i:05d}"
    return f"{cf}-{i % 5}"


def csv_for(adapter) -> str:  # type: ignore[no-untyped-def]
    hs = headers_of(adapter)
    lines = [",".join(hs)]
    for i in range(N):
        lines.append(",".join(cell(adapter, h, i) for h in hs))
    return "\n".join(lines) + "\n"


def report_file(tenant: uuid.UUID, adapter) -> uuid.UUID:  # type: ignore[no-untyped-def]
    fid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text("""INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at)
                             VALUES (:id, :t, :m, :c, :sha, 'x.csv', 1, 'file://x', :u, :at)"""),
                     {"id": str(fid), "t": str(tenant), "m": adapter.marketplace, "c": adapter.report_category, "sha": uuid.uuid4().hex * 2,
                      "u": str(uuid.uuid4()), "at": datetime.now(timezone.utc)})
    return fid


def snapshot(tenant: uuid.UUID, settlement: bool) -> dict[str, list[tuple]]:
    table, parent_col = ("settlement_line", "settlement_line_id") if settlement else ("sales_line", "sales_line_id")
    cols = ("order_ref, line_ref, settlement_id, gross_settlement_amount, settlement_date, document_type, source_row_number, source_row_json::text, confidence"
            if settlement else
            "order_ref, line_ref, invoice_ref, sku, marketplace_item_id, quantity, gross_item_amount, taxable_amount, total_invoice_amount, order_date, "
            "dispatch_date, invoice_date, document_type, return_status, source_row_number, source_row_json::text, confidence")
    with tenant_scope(tenant) as conn:
        lines = [tuple(r) for r in conn.execute(text(f"SELECT {cols} FROM {table} WHERE tenant_id = :t ORDER BY source_row_number"), {"t": str(tenant)})]
        comps = [tuple(r) for r in conn.execute(text(
            f"SELECT p.source_row_number, c.component_kind, c.component_code, c.source_side, c.amount, c.tax_amount, c.rate_pct, c.source_column, c.is_verified "
            f"FROM line_component c JOIN {table} p ON p.id = c.{parent_col} WHERE c.tenant_id = :t ORDER BY p.source_row_number, c.component_code, c.source_column"),
            {"t": str(tenant)})]
        finds = [tuple(r) for r in conn.execute(text(
            "SELECT rule_id, severity, source_row_number FROM validation_finding WHERE tenant_id = :t ORDER BY source_row_number, rule_id, severity"), {"t": str(tenant)})]
    return {"lines": lines, "components": comps, "findings": finds}


@pytest.mark.parametrize("adapter_id", sorted(ADAPTER_REGISTRY))
def test_streaming_equals_legacy_for_every_adapter(adapter_id: str, tmp_path: Path) -> None:
    adapter = ADAPTER_REGISTRY[adapter_id]
    body = csv_for(adapter)
    path = tmp_path / "f.csv"
    path.write_text(body, encoding="utf-8")
    settlement = adapter.report_category == "SETTLEMENT"
    legacy_t, stream_t = uuid.uuid4(), uuid.uuid4()

    sample, raw = read_csv_file(body.encode())
    legacy_err = stream_err = None
    legacy = streamed = None
    try:
        legacy = ingest_and_persist(legacy_t, report_file_id=report_file(legacy_t, adapter), adapter_id=adapter_id, sample=sample, raw_file=raw,
                                    started_at=datetime.now(timezone.utc))
    except RunQuarantineThresholdExceeded as exc:
        legacy_err = (exc.rejected, exc.total)
    try:
        streamed = ingest_stream_and_persist(stream_t, report_file_id=report_file(stream_t, adapter), adapter_id=adapter_id, stream=open_csv(path, LIM),
                                             started_at=datetime.now(timezone.utc))
    except RunQuarantineThresholdExceeded as exc:
        stream_err = (exc.rejected, exc.total)

    # Same failure, or same success — never one of each.
    assert legacy_err == stream_err, (adapter_id, legacy_err, stream_err)
    if legacy_err is not None:
        assert snapshot(stream_t, settlement)["lines"] == [] == snapshot(legacy_t, settlement)["lines"]  # both refuse the whole file, nothing persisted
        return
    assert legacy is not None and streamed is not None
    assert (streamed.row_count_read, streamed.row_count_accepted, streamed.row_count_rejected) == (legacy.row_count_read, legacy.row_count_accepted, legacy.row_count_rejected)
    assert streamed.row_count_read == N
    assert streamed.persisted_row_count == len(legacy.persisted_sales_line_ids)
    assert streamed.duplicates_in_file == streamed.duplicates_cross_file == streamed.held_conflicts == streamed.held_ambiguous == 0  # synthetic rows are unique
    a, b = snapshot(legacy_t, settlement), snapshot(stream_t, settlement)
    assert a["lines"] == b["lines"], f"{adapter_id}: persisted lines differ"
    assert a["components"] == b["components"], f"{adapter_id}: persisted components differ"
    assert a["findings"] == b["findings"], f"{adapter_id}: rejected-row findings differ"


def test_the_nine_adapters_are_all_exercised() -> None:
    """If an adapter is added to the registry this suite covers it automatically; this pins today's count so a silent drop is noticed."""
    assert len(ADAPTER_REGISTRY) == 9
