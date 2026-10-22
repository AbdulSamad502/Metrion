"""Expense files into the expense ledger through the background job path — real Postgres, mocked mapping proposals, no LLM
(cfo-expense-ledger.md AC-L10, cfo-data-intelligence.md AC-D11)."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from calc_engine.repositories import expense_ledger_repo as ledger  # noqa: E402
from calc_engine.repositories import read_model_version_repo as rmv  # noqa: E402

from data_foundation.ingestion.profiling import collect_profile_input  # noqa: E402
from data_foundation.ingestion.streaming import open_report  # noqa: E402
from data_foundation.mapping import service  # noqa: E402
from data_foundation.repositories import data_quality_report_repo as dq  # noqa: E402
from data_foundation.repositories import ingestion_job_repo as jobs  # noqa: E402
from data_foundation.repositories.tenant_context import tenant_scope  # noqa: E402

from .test_job_runner import AS_OF, MLIM, NOW, SLIM, runner  # noqa: E402

COLUMNS = ["Date", "Category", "Amount", "Vendor", "Note", "Paid On", "GST"]
START, END = date(2026, 9, 1), date(2026, 9, 30)


def proposal(**override: Any) -> dict[str, Any]:
    f = [
        {"source_column": "Date", "index": 0, "canonical_field": "expense_date", "transform": "DATE_DMY"},
        {"source_column": "Category", "index": 1, "canonical_field": "expense_category", "transform": "IDENTITY"},
        {"source_column": "Amount", "index": 2, "canonical_field": "expense_amount", "transform": "RUPEES_TO_PAISE", "tax_inclusion": "UNKNOWN", "sign_convention": "AS_IS"},
        {"source_column": "Vendor", "index": 3, "canonical_field": "expense_vendor", "transform": "IDENTITY"},
        {"source_column": "Note", "index": 4, "canonical_field": "expense_description", "transform": "IDENTITY"},
        {"source_column": "Paid On", "index": 5, "canonical_field": "expense_paid_date", "transform": "DATE_DMY"},
        {"source_column": "GST", "index": 6, "canonical_field": "expense_gst_amount", "transform": "RUPEES_TO_PAISE", "sign_convention": "AS_IS"},
    ]
    for i, patch in override.items():
        f[int(i)].update(patch)
    return {"fields": f, "unmapped_columns": []}


def expense_csv(tmp: Path, rows: list[list[str]], name: str = "expenses.csv") -> Path:
    p = tmp / name
    p.write_text(",".join(COLUMNS) + "\n" + "".join(",".join(r) + "\n" for r in rows), encoding="utf-8")
    return p


def upload_expense(tenant: uuid.UUID, path: Path) -> uuid.UUID:
    fid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text("""INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at)
                             VALUES (:id, :t, 'ALL', 'EXPENSE', :sha, :n, 10, :uri, :u, :at)"""),
                     {"id": str(fid), "t": str(tenant), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "n": path.name, "uri": f"file://{path}", "u": str(uuid.uuid4()), "at": NOW})
    return jobs.create_job(tenant, report_file_id=fid, report_kind="EXPENSE", created_by=uuid.uuid4(), sheet_name=None, adapter_id=None)


def confirm(tenant: uuid.UUID, job_id: uuid.UUID, path: Path) -> None:
    job = jobs.get_job(tenant, job_id)
    assert job is not None and job["mapping_id"] is not None
    pinput = collect_profile_input(open_report(path, SLIM, sheet_name=None), profile_rows=2000, sample_rows=20, seed=1)
    service.confirm(tenant, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(len(COLUMNS))}, overrides={},
                    pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    assert jobs.transition(tenant, job_id, "QUEUED", mapping_id=job["mapping_id"], now=NOW)


def run_file(tenant: uuid.UUID, path: Path, hook: Any = None) -> uuid.UUID:
    j = upload_expense(tenant, path)
    r = runner(proposer=lambda inp: proposal())
    if hook is not None:
        r._after_expense_commit = hook  # type: ignore[attr-defined]
    first = r.run_job(tenant, j)
    if first == "AWAITING_MAPPING_CONFIRMATION":
        confirm(tenant, j, path)
        first = r.run_job(tenant, j)
    assert first == "DONE", jobs.get_job(tenant, j)
    return j


ROWS = [
    ["05/09/2026", "Rent", "12000.00", "Landlord", "Sept rent", "06/09/2026", "0.00"],
    ["07/09/2026", "Software", "999.00", "SaaS Co", "tool", "08/09/2026", "179.82"],
    ["07/09/2026", "Rent", "-500.00", "Landlord", "refund", "09/09/2026", "0.00"],
    ["10/09/2026", "Marketplace commission", "250.00", "Meesho", "fee", "10/09/2026", "0.00"],
    ["12/09/2026", "Stock purchase", "50000.00", "Supplier", "bulk", "13/09/2026", "0.00"],
]


def many(n: int, **bad: Any) -> list[list[str]]:
    return [[f"{1 + i % 28:02d}/09/2026", f"Cat{i}", f"{100 + i}.00", "V", f"n{i}", f"{1 + i % 28:02d}/09/2026", "0.00"] for i in range(n)]


def test_a_confirmed_mapping_posts_every_row_to_the_ledger_with_exact_paise_and_a_quality_report(tmp_path: Path) -> None:
    t = uuid.uuid4()
    p = expense_csv(tmp_path, ROWS)
    j = run_file(t, p)
    lines = {ln.category + ("#" + str(ln.amount_paise)): ln for ln in ledger.lines_for_period(t, START, END)}
    assert set(lines) == {"Rent#1200000", "Software#99900", "Rent#-50000", "Marketplace commission#25000", "Stock purchase#5000000"}
    held = {k for k, ln in lines.items() if ln.hold.value != "NONE"}
    assert held == {"Marketplace commission#25000"}  # deduction-like: waits for the seller
    job = jobs.get_job(t, j)
    assert job["outcome"]["posted"] == 5 and job["outcome"]["persisted_row_count"] == 5  # type: ignore[index]
    rep = dq.get_for_job(t, j)
    assert rep["kind"] == "EXPENSE" and rep["rows"]["read"] == 5 and rep["rows"]["posted"] == 5 and rep["rows"]["held_overlap"] == 1  # type: ignore[index]
    assert any("GST" in n for n in rep["needs_seller"]) and any("no accounting class" in n for n in rep["needs_seller"])  # type: ignore[index]
    assert rmv.get(t) >= 1
    with tenant_scope(t) as conn:  # provenance: the entry names the run and the row it came from
        r = conn.execute(text("SELECT source, source_row_number, ingestion_run_id, gst_amount_paise, gst_treatment FROM expense_entry WHERE category = 'Software'")).one()
    assert r[0] == "FILE" and r[1] == 2 and str(r[2]) == str(job["outcome"]["ingestion_run_id"]) and r[3] == 17982 and r[4] is None  # type: ignore[index]  # GST stored beside the amount, treatment unconfirmed


def test_uploading_the_same_expenses_again_adds_nothing_and_does_not_invalidate_caches(tmp_path: Path) -> None:
    t = uuid.uuid4()
    run_file(t, expense_csv(tmp_path, ROWS, "a.csv"))
    v = rmv.get(t)
    j2 = run_file(t, expense_csv(tmp_path, ROWS, "b.csv"))
    out = jobs.get_job(t, j2)["outcome"]  # type: ignore[index]
    assert out["posted"] == 0 and out["skipped_exact_duplicates"] == 5
    assert rmv.get(t) == v and len(ledger.lines_for_period(t, START, END)) == 5


def test_repeats_inside_one_file_collapse_and_a_same_day_lookalike_is_held(tmp_path: Path) -> None:
    t = uuid.uuid4()
    rows = [ROWS[0], ROWS[0], ["05/09/2026", "Rent", "12000.00", "Landlord", "Rent payment", "06/09/2026", "0.00"], ROWS[1]]
    j = run_file(t, expense_csv(tmp_path, rows))
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert (out["posted"], out["skipped_exact_duplicates"], out["held_possible_duplicates"]) == (3, 1, 1)


def test_unreadable_rows_beyond_the_profiled_sample_are_rejected_with_reasons_and_too_many_roll_the_whole_file_back(tmp_path: Path) -> None:
    # The mapping is validated on a profiled sample (2,000 rows here); a value that cannot be read LATER in the file is rejected row by row at ingest.
    t = uuid.uuid4()
    rows = many(2000) + [["xx", "Late", "1.00", "V", "bad date", "01/09/2026", "0.00"] for _ in range(5)]
    j = run_file(t, expense_csv(tmp_path, rows))
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["posted"] == 2000 and out["rejected"] == 5 and out["rejection_examples"][0][0] == 2001  # type: ignore[index]
    rep = dq.get_for_job(t, j)
    assert "cannot be read" in rep["rejection_examples"][0]["reason"] and "Date" in rep["rejection_examples"][0]["reason"]  # type: ignore[index]
    assert any("5 row(s) could not be read" in n for n in rep["needs_seller"])  # type: ignore[index]

    t2 = uuid.uuid4()
    bad = many(2000) + [["xx", "Late", "1.00", "V", f"bad{i}", "01/09/2026", "0.00"] for i in range(700)]  # 700 of 2700 unreadable: over the 20% limit
    jid = upload_expense(t2, expense_csv(tmp_path, bad, "bad.csv"))
    r = runner(proposer=lambda inp: proposal())
    assert r.run_job(t2, jid) == "AWAITING_MAPPING_CONFIRMATION"
    confirm(t2, jid, tmp_path / "bad.csv")
    assert r.run_job(t2, jid) == "FAILED"
    job = jobs.get_job(t2, jid)
    assert job["error_code"] == "QUARANTINE_EXCEEDED" and "Nothing from it was saved" in job["error_detail"]  # type: ignore[index]
    assert ledger.lines_for_period(t2, START, END) == [] and rmv.get(t2) == 0  # all-or-nothing, and no cache invalidation for data that never landed


def test_rows_missing_a_required_value_are_rejected_not_defaulted(tmp_path: Path) -> None:
    t = uuid.uuid4()
    rows = many(40)
    rows[3][1] = ""            # no category
    rows[4][2] = "0.00"        # a zero expense
    rows[5][5] = "01/01/2020"  # paid before incurred
    j = run_file(t, expense_csv(tmp_path, rows))
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["posted"] == 37 and out["rejected"] == 3
    reasons = " | ".join(why for _, why in out["rejection_examples"])  # type: ignore[index]
    assert "category" in reasons and "zero" in reasons and "paid before" in reasons


def test_the_after_commit_hook_receives_the_new_categories_and_a_failure_does_not_undo_the_file(tmp_path: Path) -> None:
    t = uuid.uuid4()
    seen: list[tuple[uuid.UUID, tuple[str, ...]]] = []

    def hook(tenant: uuid.UUID, cats: tuple[str, ...]) -> None:
        seen.append((tenant, cats))
        raise RuntimeError("suggester down")

    run_file(t, expense_csv(tmp_path, ROWS), hook=hook)
    assert seen == [(t, ("Marketplace commission", "Rent", "Software", "Stock purchase"))]  # distinct categories only
    assert len(ledger.lines_for_period(t, START, END)) == 5  # the posted file stands


def test_expense_ingestion_is_tenant_isolated(tmp_path: Path) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    run_file(a, expense_csv(tmp_path, ROWS))
    assert ledger.lines_for_period(b, START, END) == []
    run_file(b, expense_csv(tmp_path, ROWS, "b.csv"))  # the same rows are not "duplicates" of another tenant's
    assert len(ledger.lines_for_period(b, START, END)) == 5 and len(ledger.lines_for_period(a, START, END)) == 5
