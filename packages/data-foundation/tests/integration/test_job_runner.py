"""Background ingestion jobs end to end — real Postgres, mocked mapping proposals, no LLM
(cfo-data-intelligence.md AC-D3, AC-D4, AC-D5, AC-D9, TD1, TD8, TD12). Upload -> job -> (mapping -> confirm) ->
ingest -> quality report -> read-model version."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from calc_engine.repositories import read_model_version_repo as rmv  # noqa: E402

from data_foundation.ingestion.job_runner import JobRunner, RunnerConfig  # noqa: E402
from data_foundation.ingestion.profiling import collect_profile_input  # noqa: E402
from data_foundation.ingestion.streaming import StreamLimits, open_csv, open_report  # noqa: E402
from data_foundation.mapping import service  # noqa: E402
from data_foundation.mapping.validator import MappingLimits  # noqa: E402
from data_foundation.repositories import column_mapping_repo as cm  # noqa: E402
from data_foundation.repositories import data_quality_report_repo as dq  # noqa: E402
from data_foundation.repositories import ingestion_job_repo as jobs  # noqa: E402
from data_foundation.repositories.tenant_context import tenant_scope  # noqa: E402

SLIM = StreamLimits(chunk_rows=500, max_rows=500_000, header_scan_rows=30, min_header_fill=Fraction(6, 10),
                    max_uncompressed_bytes=50 * 1024 * 1024, max_zip_ratio=200, max_zip_members=200, max_sheets=20)
MLIM = MappingLimits(min_parse_rate=Fraction(98, 100), tax_consistency_rate=Fraction(98, 100), tax_tolerance_paise=1,
                     key_unique_rate=Fraction(98, 100), mixed_sign_low=Fraction(2, 100), max_date_span_years=5, unit_fraction_share=Fraction(2, 100))
CFG = RunnerConfig(max_workers=4, stale_after_seconds=600, profile_rows=2000, sample_rows=20)
AS_OF = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

KNOWN_HEADER = "Meesho Order Number,Sub Order No,Reason for Credit Entry,Return Status\n"
UNKNOWN_COLUMNS = ["Order ID", "Line ID", "Qty", "Selling Price", "Invoice Date", "Status"]


def runner(proposer: Any = None, clock: Any = None) -> JobRunner:
    kw: dict[str, Any] = {} if clock is None else {"clock": clock}
    return JobRunner(config=CFG, stream_limits=SLIM, mapping_limits=MLIM, as_of=lambda: AS_OF, proposer=proposer, proposed_by="MODEL:mock", **kw)


def upload(tenant: uuid.UUID, path: Path, *, kind: str = "SALES", marketplace: str = "MEESHO", sheet_name: str | None = None, adapter_id: str | None = None) -> uuid.UUID:
    """Stand in for the upload route: a stored file, a report_file row and a QUEUED job."""
    fid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text("""INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                              byte_size, storage_uri, uploaded_by, uploaded_at)
                             VALUES (:id, :t, :m, 'ORDER_STATUS', :sha, :n, 10, :uri, :u, :at)"""),
                     {"id": str(fid), "t": str(tenant), "m": marketplace, "sha": uuid.uuid4().hex + uuid.uuid4().hex, "n": path.name,
                      "uri": f"file://{path}", "u": str(uuid.uuid4()), "at": NOW})
    return jobs.create_job(tenant, report_file_id=fid, report_kind=kind, created_by=uuid.uuid4(), sheet_name=sheet_name, adapter_id=adapter_id)


def known_csv(tmp: Path, n: int, name: str = "known.csv") -> Path:
    p = tmp / name
    p.write_text(KNOWN_HEADER + "".join(f"ORD-{i},ORD-{i}_1,DELIVERED,Delivered\n" for i in range(n)), encoding="utf-8")
    return p


def unknown_csv(tmp: Path, rows: list[list[str]], name: str = "unknown.csv") -> Path:
    p = tmp / name
    p.write_text(",".join(UNKNOWN_COLUMNS) + "\n" + "".join(",".join(r) + "\n" for r in rows), encoding="utf-8")
    return p


def good_rows(n: int = 40) -> list[list[str]]:
    return [[f"B-{i}", f"B-{i}-1", "2", f"{100 + i}.50", f"{1 + i % 28:02d}/10/2026", "DELIVERED" if i % 4 else "RETURNED"] for i in range(n)]


def sales_rows(tenant: uuid.UUID) -> list[tuple]:
    with tenant_scope(tenant) as conn:
        return [tuple(r) for r in conn.execute(text(
            "SELECT order_ref, line_ref, quantity, gross_item_amount, invoice_date, confidence FROM sales_line WHERE tenant_id = :t ORDER BY order_ref"), {"t": str(tenant)})]


def mock_proposal(**override: Any) -> dict[str, Any]:
    f = [
        {"source_column": "Order ID", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
        {"source_column": "Line ID", "index": 1, "canonical_field": "line_ref", "transform": "IDENTITY"},
        {"source_column": "Qty", "index": 2, "canonical_field": "quantity", "transform": "IDENTITY"},
        {"source_column": "Selling Price", "index": 3, "canonical_field": "gross_item_amount", "transform": "RUPEES_TO_PAISE",
         "tax_inclusion": "EXCLUSIVE", "sign_convention": "AS_IS"},
        {"source_column": "Invoice Date", "index": 4, "canonical_field": "invoice_date", "transform": "DATE_DMY"},
        {"source_column": "Status", "index": 5, "canonical_field": "return_status", "transform": "IDENTITY"},
    ]
    for i, patch in override.items():
        f[int(i)].update(patch)
    return {"fields": f, "unmapped_columns": []}


def confirm_all(tenant: uuid.UUID, job_id: uuid.UUID, path: Path, **kw: Any) -> None:
    job = jobs.get_job(tenant, job_id)
    assert job is not None and job["mapping_id"] is not None
    pinput = collect_profile_input(open_report(path, SLIM, sheet_name=job["sheet_name"]), profile_rows=2000, sample_rows=20, seed=1)
    decisions = {i: "SELLER_CONFIRMED" for i in range(6)}
    service.confirm(tenant, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions=decisions, overrides=kw.get("overrides", {}),
                    pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    assert jobs.transition(tenant, job_id, "QUEUED", mapping_id=job["mapping_id"], now=NOW)


# ============================================================================== known format
def test_known_format_runs_to_done_with_quality_report_and_cache_version(tmp_path: Path) -> None:
    t = uuid.uuid4()
    j = upload(t, known_csv(tmp_path, 1300))
    assert runner().run_job(t, j) == "DONE"
    job = jobs.get_job(t, j)
    assert job["status"] == "DONE" and job["outcome"]["persisted_row_count"] == 1300 and job["outcome"]["chunks"] == 3  # type: ignore[index]
    assert job["error_code"] is None and job["progress_rows"] == 1300 and job["finished_at"] is not None  # type: ignore[index]
    assert len(sales_rows(t)) == 1300
    rep = dq.get_for_job(t, j)
    assert rep["rows"]["read"] == 1300 and rep["rows"]["posted"] == 1300 and rep["confidence"] == "PROVISIONAL" and rep["format"]["mapped"] is False  # type: ignore[index]
    assert rmv.get(t) == 1  # new data and its cache-invalidating version committed together


def test_double_submit_runs_the_job_once(tmp_path: Path) -> None:
    t = uuid.uuid4()
    j = upload(t, known_csv(tmp_path, 300))
    r = runner()
    results = sorted([r.run_job(t, j), r.run_job(t, j)])
    assert results == ["DONE", "SKIPPED"] and len(sales_rows(t)) == 300 and rmv.get(t) == 1


def test_reuploading_identical_data_adds_nothing_and_does_not_bump_the_version(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = known_csv(tmp_path, 200)
    runner().run_job(t, upload(t, p))
    assert rmv.get(t) == 1
    again = upload(t, p)
    assert runner().run_job(t, again) == "DONE"
    assert len(sales_rows(t)) == 200 and rmv.get(t) == 1  # nothing was posted, so no cache invalidation
    assert jobs.get_job(t, again)["outcome"]["duplicates_cross_file"] == 200  # type: ignore[index]


def test_concurrent_jobs_for_different_tenants_all_complete_without_crosstalk(tmp_path: Path) -> None:
    tenants = [uuid.uuid4() for _ in range(4)]
    r = runner()
    futures = [(t, r.submit(t, upload(t, known_csv(tmp_path, 400, f"c{i}.csv")))) for i, t in enumerate(tenants)]
    assert [f.result(timeout=120) for _, f in futures] == ["DONE"] * 4
    for t in tenants:
        assert len(sales_rows(t)) == 400
    r.shutdown()


# ============================================================================== failures
def test_no_matching_format_and_no_proposer_fails_with_a_plain_reason(tmp_path: Path) -> None:
    t = uuid.uuid4()
    j = upload(t, unknown_csv(tmp_path, good_rows()))
    assert runner().run_job(t, j) == "FAILED"
    job = jobs.get_job(t, j)
    assert job["error_code"] == "NO_MATCHING_FORMAT" and "Nothing was saved" in job["error_detail"] and sales_rows(t) == []  # type: ignore[index]


def test_missing_file_and_unsupported_types_and_bombs_fail_cleanly(tmp_path: Path) -> None:
    t = uuid.uuid4()
    ghost = tmp_path / "gone.csv"
    ghost.write_text("A\n1\n")
    j = upload(t, ghost)
    ghost.unlink()
    assert runner().run_job(t, j) == "FAILED" and jobs.get_job(t, j)["error_code"] == "FILE_MISSING"  # type: ignore[index]

    pdf = tmp_path / "x.pdf"
    pdf.write_text("%PDF")
    j2 = upload(t, pdf)
    runner().run_job(t, j2)
    job2 = jobs.get_job(t, j2)
    assert job2["error_code"] == "unsupported_type" and ".csv or .xlsx" in job2["error_detail"]  # type: ignore[index]

    import zipfile

    bomb = tmp_path / "bomb.xlsx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr("xl/worksheets/sheet1.xml", b"\0" * (40 * 1024 * 1024))
    j3 = upload(t, bomb)
    runner().run_job(t, j3)
    assert jobs.get_job(t, j3)["error_code"] == "unsafe_archive"  # type: ignore[index]


def test_quarantine_threshold_failure_saves_nothing_and_says_so(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = tmp_path / "wrong.csv"
    # a Meesho-shaped file whose Return Status column is fine but with required-field style errors is hard to build; use malformed mapped rows instead
    p.write_text(",".join(UNKNOWN_COLUMNS) + "\n" + "".join(f"B-{i},B-{i}-1,two,abc,xx,DELIVERED\n" for i in range(50)), encoding="utf-8")
    j = upload(t, p)
    r = runner(proposer=lambda inp: mock_proposal())
    assert r.run_job(t, j) == "AWAITING_MAPPING_CONFIRMATION"
    # the mock proposal cannot be confirmed: nothing in the file parses as the mapping says
    pinput = collect_profile_input(open_csv(p, SLIM), profile_rows=2000, sample_rows=20, seed=1)
    job = jobs.get_job(t, j)
    with pytest.raises(service.MappingRefused) as e:
        service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(6)},
                        overrides={}, pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    assert any("M-TYP" in x for x in e.value.reasons) and sales_rows(t) == []


def test_cancel_in_the_middle_rolls_everything_back(tmp_path: Path) -> None:
    t = uuid.uuid4()
    j = upload(t, known_csv(tmp_path, 2600))  # 6 chunks of 500
    calls = {"n": 0}

    def clock() -> datetime:
        calls["n"] += 1
        if calls["n"] == 6:  # part-way through the stream (after the 3rd chunk's heartbeat), the seller cancels
            jobs.request_cancel(t, j, now=NOW)
        return NOW + timedelta(seconds=calls["n"])

    assert runner(clock=clock).run_job(t, j) == "CANCELLED"
    assert sales_rows(t) == []  # chunks already written were rolled back with the file
    job = jobs.get_job(t, j)
    assert job["status"] == "CANCELLED" and rmv.get(t) == 0


def test_a_tenant_cannot_run_or_see_another_tenants_job_and_missing_tenant_fails_closed(tmp_path: Path) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    j = upload(a, known_csv(tmp_path, 50))
    assert runner().run_job(b, j) == "SKIPPED"  # B's context cannot even claim A's job
    assert jobs.get_job(a, j)["status"] == "QUEUED" and sales_rows(a) == [] and sales_rows(b) == []  # type: ignore[index]
    with pytest.raises(ValueError):
        runner().run_job(None, j)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        runner().submit(None, j)  # type: ignore[arg-type]


# ============================================================================== mapped formats
def test_unfamiliar_format_waits_for_the_seller_then_ingests_through_the_confirmed_mapping(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = unknown_csv(tmp_path, good_rows(40))
    j = upload(t, p)
    seen: dict[str, Any] = {}

    def proposer(inp: service.ProposerInput) -> dict[str, Any]:
        seen["sample"] = inp.masked_sample
        return mock_proposal()

    assert runner(proposer=proposer).run_job(t, j) == "AWAITING_MAPPING_CONFIRMATION"
    job = jobs.get_job(t, j)
    assert job["status"] == "AWAITING_MAPPING_CONFIRMATION" and job["total_rows_estimate"] == 40
    assert sales_rows(t) == []  # nothing is posted before the seller confirms (AC-D3)
    m = cm.get_mapping(t, job["mapping_id"])
    assert m["status"] == "PROPOSED" and m["proposed_by"] == "MODEL:mock"  # type: ignore[index]
    decisions = {f["source_column"]: f["decision"] for f in m["fields"]}  # type: ignore[index]
    # Only a header a verified adapter already uses (and that passed every rule) may be auto-accepted; the money,
    # status and unrecognised fields always wait for the seller.
    assert decisions["Selling Price"] == "PENDING" and decisions["Status"] == "PENDING" and decisions["Qty"] == "PENDING"
    assert all(f["evidence"]["exact_register_match"] for f in m["fields"] if f["decision"] == "AUTO_ACCEPTED_BY_RULES")  # type: ignore[index]
    assert len(seen["sample"]) == 20  # a bounded, masked sample — never the whole file

    confirm_all(t, j, p)
    assert runner(proposer=proposer).run_job(t, j) == "DONE"
    rows = sales_rows(t)
    assert len(rows) == 40
    first = next(r for r in rows if r[0] == "B-0")
    assert first[2] == 2 and first[3] == 10050 and first[4] == date(2026, 10, 1) and first[5] == "PROVISIONAL"  # rupees -> paise, DD/MM date, never VERIFIED
    run = jobs.get_job(t, j)
    assert run["status"] == "DONE" and run["adapter_id"] is None and run["mapping_id"] == m["id"]  # type: ignore[index]
    with tenant_scope(t) as conn:
        adapter_id, version = conn.execute(text("SELECT adapter_id, adapter_version FROM ingestion_run WHERE tenant_id = :t"), {"t": str(t)}).one()
    assert adapter_id == f"mapped.{m['id']}" and version == "v1"  # every row traces to the exact mapping the seller confirmed
    assert dq.get_for_job(t, j)["format"]["mapped"] is True  # type: ignore[index]
    assert rmv.get(t) == 1


def test_a_confirmed_mapping_is_reused_for_the_same_file_shape_without_asking_again(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p1 = unknown_csv(tmp_path, good_rows(30), "m1.csv")
    j1 = upload(t, p1)
    r = runner(proposer=lambda inp: mock_proposal())
    r.run_job(t, j1)
    confirm_all(t, j1, p1)
    r.run_job(t, j1)
    asked = {"n": 0}

    def counting(inp: service.ProposerInput) -> dict[str, Any]:
        asked["n"] += 1
        return mock_proposal()

    p2 = unknown_csv(tmp_path, [[f"C-{i}", f"C-{i}-1", "1", "50.00", "05/10/2026", "DELIVERED"] for i in range(10)], "m2.csv")
    j2 = upload(t, p2)
    assert runner(proposer=counting).run_job(t, j2) == "DONE" and asked["n"] == 0  # same shape: confirmed mapping reused
    assert len(sales_rows(t)) == 40


def test_gst_inclusive_mapped_amounts_are_refused_not_posted_as_tax_exclusive(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = unknown_csv(tmp_path, good_rows(30))
    j = upload(t, p)
    r = runner(proposer=lambda inp: mock_proposal(**{"3": {"tax_inclusion": "INCLUSIVE"}}))
    r.run_job(t, j)
    confirm_all(t, j, p)  # the seller says the price includes GST; the mapping is valid and confirmed...
    assert r.run_job(t, j) == "FAILED"  # ...but Metrion cannot yet extract GST from a mapped file, so it refuses
    job = jobs.get_job(t, j)
    assert job["error_code"] == "TAX_INCLUSIVE_UNSUPPORTED_FOR_MAPPED" and "overstate revenue" in job["error_detail"] and sales_rows(t) == []  # type: ignore[index]


def test_unreadable_cells_quarantine_the_row_and_name_the_value(tmp_path: Path) -> None:
    t = uuid.uuid4()
    rows = good_rows(100)
    rows[7][3] = "not-a-price"  # 1% of rows: under the mapping's parse threshold, so the mapping is valid, but this row is not
    p = unknown_csv(tmp_path, rows)
    j = upload(t, p)
    r = runner(proposer=lambda inp: mock_proposal())
    r.run_job(t, j)
    confirm_all(t, j, p)
    assert r.run_job(t, j) == "DONE"
    assert len(sales_rows(t)) == 99  # the bad row is excluded, not defaulted to zero
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["row_count_rejected"] == 1
    with tenant_scope(t) as conn:
        f = conn.execute(text("SELECT rule_id, message FROM validation_finding WHERE tenant_id = :t AND rule_id = 'V-MAP-001'"), {"t": str(t)}).one()
    assert "not-a-price" in f[1] and "Selling Price" in f[1]


def test_seller_cannot_confirm_by_silence_or_with_a_still_invalid_mapping(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = unknown_csv(tmp_path, good_rows(40))
    j = upload(t, p)
    runner(proposer=lambda inp: mock_proposal()).run_job(t, j)
    job = jobs.get_job(t, j)
    pinput = collect_profile_input(open_csv(p, SLIM), profile_rows=2000, sample_rows=20, seed=1)
    with pytest.raises(service.MappingRefused) as e:  # no explicit decisions: silence is not confirmation
        service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={}, overrides={}, pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    assert any("needs your confirmation" in x for x in e.value.reasons)
    # an override that makes it wrong (rupees declared as paise) is re-validated and refused
    bad = {3: service.FieldOverride(transform="PAISE_IDENTITY")}
    with pytest.raises(service.MappingRefused) as e2:
        service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(6)}, overrides=bad,
                        pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    assert any("M-UNT" in x for x in e2.value.reasons)
    assert cm.get_mapping(t, job["mapping_id"])["status"] == "PROPOSED"  # type: ignore[index]  # nothing was confirmed


def test_an_unparseable_model_answer_falls_back_to_manual_mapping(tmp_path: Path) -> None:
    t = uuid.uuid4()
    j = upload(t, unknown_csv(tmp_path, good_rows()))
    assert runner(proposer=lambda inp: "I think the first column is the order id").run_job(t, j) == "FAILED"
    job = jobs.get_job(t, j)
    assert job["error_code"] == "MAPPING_PROPOSAL_FAILED" and "map the columns manually" in job["error_detail"] and sales_rows(t) == []  # type: ignore[index]



# ============================================================================== XLSX through the whole job path (AC-D2, AC-D10)
def make_xlsx(path: Path, sheets: dict[str, list[list[Any]]]) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


KNOWN_COLS = ["Meesho Order Number", "Sub Order No", "Reason for Credit Entry", "Return Status"]


def test_xlsx_in_a_known_format_runs_the_job_to_done_with_the_same_rows_as_csv(tmp_path: Path) -> None:
    rows = [[f"ORD-{i}", f"ORD-{i}_1", "DELIVERED", "Delivered"] for i in range(1200)]
    a, b = uuid.uuid4(), uuid.uuid4()
    ja = upload(a, make_xlsx(tmp_path / "k.xlsx", {"Orders": [KNOWN_COLS, *rows]}))
    jb = upload(b, known_csv(tmp_path, 1200, "k.csv"))
    assert runner().run_job(a, ja) == "DONE" and runner().run_job(b, jb) == "DONE"
    out = jobs.get_job(a, ja)["outcome"]  # type: ignore[index]
    assert out["persisted_row_count"] == 1200 and out["chunks"] == 3
    with tenant_scope(a) as ca, tenant_scope(b) as cb:
        q = text("SELECT order_ref, line_ref, source_row_json::text, confidence FROM sales_line ORDER BY order_ref")
        assert [tuple(r) for r in ca.execute(q)] == [tuple(r) for r in cb.execute(q)]  # an .xlsx and a .csv of the same report post identical rows
    assert dq.get_for_job(a, ja)["rows"]["posted"] == 1200  # type: ignore[index]
    assert rmv.get(a) == 1


def test_xlsx_sheet_selection_and_a_title_block_above_the_header(tmp_path: Path) -> None:
    t = uuid.uuid4()
    wb = {"Summary": [["Total orders", 3]],
          "Orders": [["Seller report"], ["Generated 21 Oct"], [], KNOWN_COLS, ["O1", "O1_1", "DELIVERED", "Delivered"], ["O2", "O2_1", "DELIVERED", "Delivered"]]}
    p = make_xlsx(tmp_path / "multi.xlsx", wb)
    right = upload(t, p, sheet_name="Orders")
    assert runner().run_job(t, right) == "DONE" and jobs.get_job(t, right)["outcome"]["persisted_row_count"] == 2  # type: ignore[index]


def test_xlsx_with_no_header_on_the_chosen_sheet_fails_with_a_plain_reason(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = make_xlsx(tmp_path / "nohdr.xlsx", {"Summary": [["Total orders", 3]], "Orders": [KNOWN_COLS, ["O1", "O1_1", "DELIVERED", "Delivered"]]})
    j = upload(t, p)  # defaults to the first visible sheet, which is the summary
    assert runner().run_job(t, j) == "FAILED"
    job = jobs.get_job(t, j)
    assert job["error_code"] == "no_header" and "header row" in job["error_detail"] and sales_rows(t) == []  # type: ignore[index]


def test_xlsx_in_an_unfamiliar_format_goes_through_mapping_with_real_excel_dates_and_numbers(tmp_path: Path) -> None:
    from datetime import datetime as dt

    t = uuid.uuid4()
    rows = [[f"B-{i}", f"B-{i}-1", 2, 100.5 + i, dt(2026, 10, 1 + i % 28), "DELIVERED" if i % 4 else "RETURNED"] for i in range(40)]
    p = make_xlsx(tmp_path / "unk.xlsx", {"Sales": [UNKNOWN_COLUMNS, *rows]})
    j = upload(t, p)
    r = runner(proposer=lambda inp: mock_proposal(**{"4": {"transform": "DATE_ISO"}}))  # Excel dates reach the mapping as ISO text
    assert r.run_job(t, j) == "AWAITING_MAPPING_CONFIRMATION" and sales_rows(t) == []
    confirm_all(t, j, p)
    assert r.run_job(t, j) == "DONE"
    got = {x[0]: x for x in sales_rows(t)}
    assert len(got) == 40
    assert got["B-0"][3] == 10050 and got["B-3"][3] == 10350  # 100.5 and 103.5 rupees, exactly, as paise (no float artefacts)
    assert got["B-0"][4] == date(2026, 10, 1) and got["B-0"][2] == 2 and got["B-0"][5] == "PROVISIONAL"


# ============================================================================== report types that share headers (Amazon B2B / B2C MTR)
def amazon_csv(tmp: Path, name: str = "amz.csv") -> Path:
    from data_foundation.adapters.registry import ADAPTER_REGISTRY

    a = ADAPTER_REGISTRY["amazon.mtr_b2c.v1"]
    cols = [k[0] if isinstance(k, tuple) else k for k in a.column_map]
    p = tmp / name
    p.write_text(",".join(cols) + "\n" + "".join(",".join(f"{c.split()[0]}-{i}" for c in cols) + "\n" for i in range(30)), encoding="utf-8")
    return p


def test_a_file_that_fits_two_report_types_is_never_guessed_the_seller_chooses(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = amazon_csv(tmp_path)
    j = upload(t, p, marketplace="AMAZON")
    assert runner().run_job(t, j) == "FAILED"
    job = jobs.get_job(t, j)
    assert job["error_code"] == "AMBIGUOUS_ADAPTER" and "amazon.mtr_b2b.v1" in job["error_detail"] and "amazon.mtr_b2c.v1" in job["error_detail"]  # type: ignore[index]
    assert "will not guess" in job["error_detail"] and "Nothing was saved" in job["error_detail"] and sales_rows(t) == []  # type: ignore[index]
    chosen = upload(t, p, marketplace="AMAZON", adapter_id="amazon.mtr_b2c.v1")  # a second attempt with the choice stated
    assert runner().run_job(t, chosen) == "DONE"
    out = jobs.get_job(t, chosen)
    assert out["adapter_id"] == "amazon.mtr_b2c.v1" and out["outcome"]["persisted_row_count"] == 30  # type: ignore[index]


def test_a_chosen_report_type_must_fit_the_marketplace_and_the_file(tmp_path: Path) -> None:
    t = uuid.uuid4()
    wrong_marketplace = upload(t, amazon_csv(tmp_path), marketplace="AMAZON", adapter_id="flipkart.sales_report.v1")
    assert runner().run_job(t, wrong_marketplace) == "FAILED"
    assert jobs.get_job(t, wrong_marketplace)["error_code"] == "ADAPTER_NOT_APPLICABLE"  # type: ignore[index]
    not_this_file = upload(t, known_csv(tmp_path, 10, "m.csv"), marketplace="AMAZON", adapter_id="amazon.mtr_b2c.v1")  # a Meesho-shaped file
    assert runner().run_job(t, not_this_file) == "FAILED"
    job = jobs.get_job(t, not_this_file)
    assert job["error_code"] == "ADAPTER_MISMATCH" and "missing" in job["error_detail"] and sales_rows(t) == []  # type: ignore[index]



# ============================================================ legitimate events sharing an order / line, end to end through a mapped file
EVENT_COLUMNS = ["Order ID", "Line ID", "Doc Type", "Qty", "Selling Price", "Invoice Date"]


def event_csv(tmp: Path, rows: list[list[str]], name: str = "events.csv") -> Path:
    p = tmp / name
    p.write_text(",".join(EVENT_COLUMNS) + "\n" + "".join(",".join(r) + "\n" for r in rows), encoding="utf-8")
    return p


def event_proposal() -> dict[str, Any]:
    return {"fields": [
        {"source_column": "Order ID", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
        {"source_column": "Line ID", "index": 1, "canonical_field": "line_ref", "transform": "IDENTITY"},
        {"source_column": "Doc Type", "index": 2, "canonical_field": "document_type", "transform": "IDENTITY"},
        {"source_column": "Qty", "index": 3, "canonical_field": "quantity", "transform": "IDENTITY"},
        {"source_column": "Selling Price", "index": 4, "canonical_field": "gross_item_amount", "transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE", "sign_convention": "AS_IS"},
        {"source_column": "Invoice Date", "index": 5, "canonical_field": "invoice_date", "transform": "DATE_DMY"}], "unmapped_columns": []}


def confirm_event_mapping(t: uuid.UUID, j: uuid.UUID, p: Path) -> None:
    job = jobs.get_job(t, j)
    assert job is not None
    pinput = collect_profile_input(open_report(p, SLIM, sheet_name=None), profile_rows=2000, sample_rows=20, seed=1)
    service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(6)}, overrides={}, pinput=pinput,
                    limits=MLIM, as_of=AS_OF, now=NOW)
    assert jobs.transition(t, j, "QUEUED", mapping_id=job["mapping_id"], now=NOW)


def test_a_sale_and_its_credit_note_sharing_an_order_and_line_both_post(tmp_path: Path) -> None:
    t = uuid.uuid4()
    rows = [["O1", "L1", "INVOICE", "1", "100.00", "05/10/2026"], ["O1", "L1", "CREDIT_NOTE", "1", "-100.00", "07/10/2026"],
            ["O2", "L2", "INVOICE", "2", "250.00", "06/10/2026"], ["O2", "L2", "INVOICE", "2", "250.00", "06/10/2026"]]  # the last is an exact repeat of the row above
    p = event_csv(tmp_path, rows)
    j = upload(t, p)
    r = runner(proposer=lambda inp: event_proposal())
    assert r.run_job(t, j) == "AWAITING_MAPPING_CONFIRMATION"
    confirm_event_mapping(t, j, p)
    assert r.run_job(t, j) == "DONE"
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["persisted_row_count"] == 3 and out["duplicates_in_file"] == 1 and out["held_conflicts"] == 0 and out["held_ambiguous"] == 0
    with tenant_scope(t) as conn:
        got = [tuple(x) for x in conn.execute(text("SELECT order_ref, document_type, gross_item_amount FROM sales_line WHERE tenant_id = :t ORDER BY order_ref, document_type"), {"t": str(t)})]
    assert got == [("O1", "CREDIT_NOTE", -10000), ("O1", "INVOICE", 10000), ("O2", "INVOICE", 25000)]  # the credit note is its own event; the repeat was counted once


def test_without_an_event_type_the_same_line_with_different_content_is_held_not_merged_and_not_doubled(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = tmp_path / "noevent.csv"
    p.write_text("Order ID,Line ID,Qty,Selling Price,Invoice Date\nO1,L1,1,100.00,05/10/2026\nO1,L1,1,-100.00,07/10/2026\n", encoding="utf-8")

    def proposal(_inp: Any) -> dict[str, Any]:
        f = event_proposal()["fields"]
        keep = [x for x in f if x["canonical_field"] != "document_type"]
        for new_index, x in enumerate(keep):
            x["index"] = new_index
        return {"fields": keep, "unmapped_columns": []}

    j = upload(t, p)
    r = runner(proposer=proposal)
    assert r.run_job(t, j) == "AWAITING_MAPPING_CONFIRMATION"
    job = jobs.get_job(t, j)
    pinput = collect_profile_input(open_csv(p, SLIM), profile_rows=2000, sample_rows=20, seed=1)
    service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(5)}, overrides={}, pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)  # type: ignore[index]
    jobs.transition(t, j, "QUEUED", mapping_id=job["mapping_id"], now=NOW)  # type: ignore[index]
    assert r.run_job(t, j) == "DONE"
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["persisted_row_count"] == 1 and out["held_conflicts"] == 1  # nothing says the second row is a credit note, so it is held for the seller, not silently posted
    assert len(sales_rows(t)) == 1


# ============================================================ the unit of a rate is never guessed (decision R2), end to end
RATE_COLUMNS = ["Order ID", "Line ID", "Qty", "Selling Price", "Invoice Date", "GST Rate"]


def rate_file(tmp: Path, rates: list[str], name: str) -> Path:
    p = tmp / name
    p.write_text(",".join(RATE_COLUMNS) + "\n" + "".join(f"R-{i},R-{i}-1,1,{100 + i}.00,05/10/2026,{v}\n" for i, v in enumerate(rates)), encoding="utf-8")
    return p


def rate_proposal(transform: str) -> Any:
    def make(_inp: Any) -> dict[str, Any]:
        f = mock_proposal()["fields"][:5]
        f = [x for x in f if x["canonical_field"] != "return_status"]
        f.append({"source_column": "GST Rate", "index": 5, "canonical_field": "gst_rate", "transform": transform})
        return {"fields": f, "unmapped_columns": []}
    return make


def test_an_ambiguous_rate_column_is_refused_until_the_seller_chooses_the_unit(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = rate_file(tmp_path, ["0.18", "0.05", "0.12", "0.28"] * 10, "ambig.csv")
    j = upload(t, p)
    r = runner(proposer=rate_proposal("PERCENT"))
    assert r.run_job(t, j) == "AWAITING_MAPPING_CONFIRMATION"
    job = jobs.get_job(t, j)
    pinput = collect_profile_input(open_csv(p, SLIM), profile_rows=2000, sample_rows=20, seed=1)
    m = cm.get_mapping(t, job["mapping_id"])  # type: ignore[index]
    gst = next(f for f in m["fields"] if f["source_column"] == "GST Rate")  # type: ignore[index]
    assert gst["decision"] == "PENDING" and any("will not guess" in x for x in gst["evidence"]["confirm_reasons"])  # the question is on the mapping the seller sees
    others = {i: "SELLER_CONFIRMED" for i in range(5)}
    with pytest.raises(service.MappingRefused) as e:  # every other field decided, the rate unit left unanswered
        service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions=others, overrides={}, pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)  # type: ignore[index]
    assert any("GST Rate" in x and "needs your confirmation" in x for x in e.value.reasons)
    assert cm.get_mapping(t, job["mapping_id"])["status"] == "PROPOSED" and sales_rows(t) == []  # type: ignore[index]
    # the seller states the unit explicitly: fractions of 1
    service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={**others, 5: "SELLER_CONFIRMED"}, overrides={5: service.FieldOverride(transform="FRACTION_TO_PERCENT")},  # type: ignore[index]
                    pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    jobs.transition(t, j, "QUEUED", mapping_id=job["mapping_id"], now=NOW)  # type: ignore[index]
    assert r.run_job(t, j) == "DONE" and len(sales_rows(t)) == 40


def test_choosing_the_fraction_unit_for_percentage_points_is_refused(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = rate_file(tmp_path, ["18", "5", "12", "28"] * 10, "points.csv")
    j = upload(t, p)
    r = runner(proposer=rate_proposal("PERCENT"))
    assert r.run_job(t, j) == "AWAITING_MAPPING_CONFIRMATION"
    job = jobs.get_job(t, j)
    pinput = collect_profile_input(open_csv(p, SLIM), profile_rows=2000, sample_rows=20, seed=1)
    with pytest.raises(service.MappingRefused) as e:
        service.confirm(t, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(6)},  # type: ignore[index]
                        overrides={5: service.FieldOverride(transform="FRACTION_TO_PERCENT")}, pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    assert any("M-PCT" in x for x in e.value.reasons)  # values above 1 can only be percentage points
