"""Streaming ingestion — real Postgres (cfo-data-intelligence.md AC-D2, AC-D5, AC-D6, TD1, TD8, TD9, TD15).

The streamed result must be IDENTICAL to the legacy whole-file path, a failed or over-quarantined file must
leave nothing behind, and an overlapping re-upload must not double-count.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from data_foundation.ingestion.file_reader import read_csv_file  # noqa: E402
from data_foundation.ingestion.persist import ingest_and_persist  # noqa: E402
from data_foundation.ingestion.pipeline import AdapterMismatchError, RunQuarantineThresholdExceeded  # noqa: E402
from data_foundation.ingestion.stream_persist import ingest_stream_and_persist  # noqa: E402
from data_foundation.ingestion.streaming import RowStream, StreamHeader, StreamLimits, open_csv  # noqa: E402
from data_foundation.repositories.tenant_context import tenant_scope  # noqa: E402

LIM = StreamLimits(chunk_rows=700, max_rows=500_000, header_scan_rows=30, min_header_fill=Fraction(6, 10),
                   max_uncompressed_bytes=50 * 1024 * 1024, max_zip_ratio=200, max_zip_members=200, max_sheets=20)
HEADER = "Meesho Order Number,Sub Order No,Reason for Credit Entry,Return Status\n"


def csv_text(n: int, start: int = 0) -> str:
    return HEADER + "".join(f"ORD-{i},ORD-{i}_1,DELIVERED,Delivered\n" for i in range(start, start + n))


def report_file(tenant_id: uuid.UUID) -> uuid.UUID:
    fid = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(text("""INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                              byte_size, storage_uri, uploaded_by, uploaded_at)
                             VALUES (:id, :t, 'MEESHO', 'ORDER_STATUS', :sha, 'orders.csv', 100, 'file://x', :u, :at)"""),
                     {"id": str(fid), "t": str(tenant_id), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4()),
                      "at": datetime.now(timezone.utc)})
    return fid


def persisted(tenant_id: uuid.UUID) -> list[tuple]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text("""SELECT order_ref, line_ref, source_row_number, source_row_json::text, confidence, marketplace
                                    FROM sales_line WHERE tenant_id = :t ORDER BY source_row_number, order_ref"""), {"t": str(tenant_id)}).all()
    return [tuple(r) for r in rows]


def run_status(tenant_id: uuid.UUID, run_id: uuid.UUID) -> str:
    with tenant_scope(tenant_id) as conn:
        return str(conn.execute(text("SELECT status FROM ingestion_run WHERE id = :i"), {"i": str(run_id)}).scalar_one())


def stream_ingest(tenant_id: uuid.UUID, path: Path, **kw):  # type: ignore[no-untyped-def]
    return ingest_stream_and_persist(tenant_id, report_file_id=report_file(tenant_id), adapter_id="meesho.orders.v1",
                                     stream=open_csv(path, LIM), started_at=datetime.now(timezone.utc), **kw)


def test_streamed_result_is_identical_to_the_legacy_path_across_chunks(tmp_path: Path) -> None:
    body = csv_text(2500)
    path = tmp_path / "o.csv"
    path.write_text(body, encoding="utf-8")

    legacy_tenant, stream_tenant = uuid.uuid4(), uuid.uuid4()
    sample, raw = read_csv_file(body.encode())
    old = ingest_and_persist(legacy_tenant, report_file_id=report_file(legacy_tenant), adapter_id="meesho.orders.v1",
                             sample=sample, raw_file=raw, started_at=datetime.now(timezone.utc))
    progress: list[int] = []
    new = stream_ingest(stream_tenant, path, on_progress=progress.append)

    assert (new.row_count_read, new.row_count_accepted, new.row_count_rejected, new.row_count_duplicate) == (
        old.row_count_read, old.row_count_accepted, old.row_count_rejected, old.row_count_duplicate) == (2500, 2500, 0, 0)
    assert new.persisted_row_count == len(old.persisted_sales_line_ids) == 2500
    assert new.chunks == 4 and progress == [700, 1400, 2100, 2500]
    assert persisted(stream_tenant) == persisted(legacy_tenant)  # byte-identical rows, incl. source_row_number 1..2500
    rows = persisted(stream_tenant)
    assert rows[0][2] == 1 and rows[-1][2] == 2500 and len({r[2] for r in rows}) == 2500
    assert run_status(stream_tenant, new.ingestion_run_id) == "VALIDATED"


def test_overlapping_reupload_is_deduplicated_not_double_counted(tmp_path: Path) -> None:
    t = uuid.uuid4()
    first = tmp_path / "a.csv"
    first.write_text(csv_text(1000), encoding="utf-8")
    stream_ingest(t, first)
    overlap = tmp_path / "b.csv"
    overlap.write_text(csv_text(1000, start=500), encoding="utf-8")  # ORD-500..1499: 500 already exist
    out = stream_ingest(t, overlap)
    assert out.row_count_read == 1000 and out.row_count_duplicate == 500 and out.persisted_row_count == 500
    assert len(persisted(t)) == 1500


def test_quarantine_threshold_exceeded_rolls_the_whole_file_back(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = tmp_path / "q.csv"
    p.write_text(csv_text(2000), encoding="utf-8")
    fid = report_file(t)
    with pytest.raises(RunQuarantineThresholdExceeded):
        ingest_stream_and_persist(t, report_file_id=fid, adapter_id="meesho.orders.v1", stream=open_csv(p, LIM),
                                  started_at=datetime.now(timezone.utc), required_fields=("order_ref", "nonexistent_field"))
    assert persisted(t) == []  # chunks 1..3 were written then rolled back with the file
    with tenant_scope(t) as conn:
        statuses = [r[0] for r in conn.execute(text("SELECT status FROM ingestion_run WHERE report_file_id = :f"), {"f": str(fid)})]
    assert statuses == ["QUARANTINE_EXCEEDED"]


def test_a_failure_part_way_leaves_no_partial_file(tmp_path: Path) -> None:
    t = uuid.uuid4()
    cols = ("Meesho Order Number", "Sub Order No", "Reason for Credit Entry", "Return Status")

    def rows():  # type: ignore[no-untyped-def]
        for i in range(1500):
            yield [f"ORD-{i}", f"ORD-{i}_1", "DELIVERED", "Delivered"]
        raise RuntimeError("worker killed mid-parse")

    stream = RowStream(StreamHeader(columns=cols, header_row_index=0, sheet_name=None, has_duplicate_headers=False, encoding="utf-8"),
                       rows(), LIM)
    fid = report_file(t)
    with pytest.raises(RuntimeError):
        ingest_stream_and_persist(t, report_file_id=fid, adapter_id="meesho.orders.v1", stream=stream, started_at=datetime.now(timezone.utc))
    assert persisted(t) == []  # two full chunks were written, then rolled back
    with tenant_scope(t) as conn:
        assert [r[0] for r in conn.execute(text("SELECT status FROM ingestion_run WHERE report_file_id = :f"), {"f": str(fid)})] == ["FAILED"]


def test_wrong_adapter_is_a_mismatch_and_persists_nothing(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = tmp_path / "w.csv"
    p.write_text("Totally,Different,Columns\n1,2,3\n", encoding="utf-8")
    with pytest.raises(AdapterMismatchError):
        stream_ingest(t, p)
    assert persisted(t) == []


def test_tenant_isolation_streamed_rows_are_invisible_to_another_tenant(tmp_path: Path) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    p = tmp_path / "i.csv"
    p.write_text(csv_text(800), encoding="utf-8")
    stream_ingest(a, p)
    assert len(persisted(a)) == 800 and persisted(b) == []
    with tenant_scope(b) as conn:  # even asking for A's tenant id under B's context returns nothing (RLS)
        assert conn.execute(text("SELECT count(*) FROM sales_line WHERE tenant_id = :t"), {"t": str(a)}).scalar_one() == 0


def test_blank_and_ragged_rows_are_counted_not_dropped_silently(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = tmp_path / "r.csv"
    p.write_text(HEADER + "ORD-1,ORD-1_1,DELIVERED,Delivered\n\nORD-2,ORD-2_1\n", encoding="utf-8")
    out = stream_ingest(t, p)
    assert out.row_count_read == 2 and out.blank_rows_skipped == 1 and out.ragged_rows == 1
