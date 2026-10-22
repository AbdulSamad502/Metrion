"""Advertising reports into `ad_report_line` through the job path — real Postgres, mocked mapping proposals (docs/specs/cfo-phase3-scope.md AC-B1, AC-B6, AC-B7)."""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from calc_engine.repositories import ad_report_repo as ads  # noqa: E402
from calc_engine.repositories import read_model_version_repo as rmv  # noqa: E402

from data_foundation.ingestion.profiling import collect_profile_input  # noqa: E402
from data_foundation.ingestion.streaming import open_report  # noqa: E402
from data_foundation.mapping import service  # noqa: E402
from data_foundation.repositories import data_quality_report_repo as dq  # noqa: E402
from data_foundation.repositories import ingestion_job_repo as jobs  # noqa: E402
from data_foundation.repositories.tenant_context import tenant_scope  # noqa: E402

from .test_job_runner import AS_OF, MLIM, NOW, SLIM, runner  # noqa: E402

COLUMNS = ["Date", "Campaign", "SKU", "Spend", "Sales", "Impressions", "Clicks"]
START, END = date(2026, 9, 1), date(2026, 9, 30)


def proposal() -> dict[str, Any]:
    return {"fields": [
        {"source_column": "Date", "index": 0, "canonical_field": "report_date", "transform": "DATE_DMY"},
        {"source_column": "Campaign", "index": 1, "canonical_field": "campaign_ref", "transform": "IDENTITY"},
        {"source_column": "SKU", "index": 2, "canonical_field": "sku", "transform": "IDENTITY"},
        {"source_column": "Spend", "index": 3, "canonical_field": "spend", "transform": "RUPEES_TO_PAISE", "sign_convention": "AS_IS"},
        {"source_column": "Sales", "index": 4, "canonical_field": "attributed_sales", "transform": "RUPEES_TO_PAISE", "sign_convention": "AS_IS"},
        {"source_column": "Impressions", "index": 5, "canonical_field": "impressions", "transform": "IDENTITY"},
        {"source_column": "Clicks", "index": 6, "canonical_field": "clicks", "transform": "IDENTITY"},
    ], "unmapped_columns": []}


def ad_csv(tmp: Path, rows: list[list[str]], name: str = "ads.csv") -> Path:
    p = tmp / name
    p.write_text(",".join(COLUMNS) + "\n" + "".join(",".join(r) + "\n" for r in rows), encoding="utf-8")
    return p


def many(n: int, campaign: str = "C1") -> list[list[str]]:
    return [[f"{1 + i % 28:02d}/09/2026", f"{campaign}-{i // 28}", f"SKU{i % 5}", f"{100 + i}.00", f"{500 + i}.00", f"{1000 + i}", f"{10 + i % 7}"] for i in range(n)]


def upload_ad(tenant: uuid.UUID, path: Path, marketplace: str = "MEESHO") -> uuid.UUID:
    fid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text("""INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at)
                             VALUES (:id, :t, :m, 'ADVERTISING', :sha, :n, 10, :uri, :u, :at)"""),
                     {"id": str(fid), "t": str(tenant), "m": marketplace, "sha": uuid.uuid4().hex + uuid.uuid4().hex, "n": path.name, "uri": f"file://{path}", "u": str(uuid.uuid4()), "at": NOW})
    return jobs.create_job(tenant, report_file_id=fid, report_kind="ADVERTISING", created_by=uuid.uuid4(), sheet_name=None, adapter_id=None)


def run_file(tenant: uuid.UUID, path: Path, marketplace: str = "MEESHO") -> uuid.UUID:
    j = upload_ad(tenant, path, marketplace)
    r = runner(proposer=lambda inp: proposal())
    st = r.run_job(tenant, j)
    if st == "AWAITING_MAPPING_CONFIRMATION":
        job = jobs.get_job(tenant, j)
        pinput = collect_profile_input(open_report(path, SLIM, sheet_name=None), profile_rows=2000, sample_rows=20, seed=1)
        service.confirm(tenant, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(len(COLUMNS))}, overrides={},
                        pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
        assert jobs.transition(tenant, j, "QUEUED", mapping_id=job["mapping_id"], now=NOW)
        st = r.run_job(tenant, j)
    assert st == "DONE", jobs.get_job(tenant, j)
    return j


def test_a_confirmed_mapping_posts_ad_lines_with_exact_paise_coverage_and_a_report(tmp_path: Path) -> None:
    t = uuid.uuid4()
    j = run_file(t, ad_csv(tmp_path, many(40)))
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["posted"] == 40 and out["rejected"] == 0 and out["period_start"] == "2026-09-01" and out["period_end"] == "2026-09-28"  # type: ignore[index]
    spend = ads.spend_in_period(t, "MEESHO", START, END)
    assert spend is not None and spend.line_count == 40 and spend.spend_paise == sum((100 + i) * 100 for i in range(40)) and spend.attributed_sales_paise == sum((500 + i) * 100 for i in range(40))
    cov = ads.report_coverage(t, "MEESHO")
    assert len(cov) == 1 and cov[0].start == date(2026, 9, 1) and cov[0].end == date(2026, 9, 28)
    rep = dq.get_for_job(t, j)
    assert rep["kind"] == "ADVERTISING" and rep["rows"]["posted"] == 40 and rep["period"]["start"] == "2026-09-01"  # type: ignore[index]
    assert rmv.get(t) >= 1


def test_an_identical_repeat_is_skipped_and_a_conflicting_repeat_is_rejected_with_the_earlier_figure_standing(tmp_path: Path) -> None:
    t = uuid.uuid4()
    run_file(t, ad_csv(tmp_path, many(40), "a.csv"))
    before = ads.spend_in_period(t, "MEESHO", START, END)
    v = rmv.get(t)
    j2 = run_file(t, ad_csv(tmp_path, many(40), "b.csv"))
    out = jobs.get_job(t, j2)["outcome"]  # type: ignore[index]
    assert out["posted"] == 0 and out["skipped_exact_duplicates"] == 40 and rmv.get(t) == v
    changed = many(40)
    changed[3][3] = "9999.00"  # same campaign/sku/day, different spend
    j3 = run_file(t, ad_csv(tmp_path, changed, "c.csv"))
    out3 = jobs.get_job(t, j3)["outcome"]  # type: ignore[index]
    assert out3["posted"] == 0 and out3["rejected"] == 1 and "different figures" in out3["rejection_examples"][0][1] and out3["skipped_exact_duplicates"] == 39  # type: ignore[index]
    assert ads.spend_in_period(t, "MEESHO", START, END) == before  # nothing overwritten, nothing doubled


def test_repeats_inside_one_file_collapse(tmp_path: Path) -> None:
    t = uuid.uuid4()
    rows = many(30) + [many(30)[0]]
    j = run_file(t, ad_csv(tmp_path, rows))
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["posted"] == 30 and out["skipped_exact_duplicates"] == 1


def test_rows_without_attributed_sales_keep_it_unknown_not_zero(tmp_path: Path) -> None:
    t = uuid.uuid4()
    rows = many(40)
    for r in rows[:20]:
        r[4] = ""
    j = run_file(t, ad_csv(tmp_path, rows))
    assert jobs.get_job(t, j)["outcome"]["no_attributed_sales"] == 20  # type: ignore[index]
    s = ads.spend_in_period(t, "MEESHO", START, END)
    assert s is not None and s.lines_with_sales == 20
    with tenant_scope(t) as conn:
        assert conn.execute(text("SELECT count(*) FROM ad_report_line WHERE tenant_id = :t AND attributed_sales IS NULL"), {"t": str(t)}).scalar_one() == 20


def test_unreadable_negative_and_missing_values_are_rejected_with_reasons_and_too_many_roll_back(tmp_path: Path) -> None:
    t = uuid.uuid4()
    rows = many(2000) + [["xx", "L", "S", "1.00", "", "", ""]] + [["05/09/2026", "N", "S", "-5.00", "", "", ""]]
    j = run_file(t, ad_csv(tmp_path, rows))
    out = jobs.get_job(t, j)["outcome"]  # type: ignore[index]
    assert out["posted"] == 2000 and out["rejected"] == 2
    reasons = " | ".join(why for _, why in out["rejection_examples"])  # type: ignore[index]
    assert "cannot be read" in reasons and "negative" in reasons
    t2 = uuid.uuid4()
    bad = many(2000) + [["xx", f"L{i}", "S", "1.00", "", "", ""] for i in range(700)]
    jid = upload_ad(t2, ad_csv(tmp_path, bad, "bad.csv"))
    r = runner(proposer=lambda inp: proposal())
    assert r.run_job(t2, jid) == "AWAITING_MAPPING_CONFIRMATION"
    job = jobs.get_job(t2, jid)
    pinput = collect_profile_input(open_report(tmp_path / "bad.csv", SLIM, sheet_name=None), profile_rows=2000, sample_rows=20, seed=1)
    service.confirm(t2, job["mapping_id"], confirmed_by=uuid.uuid4(), decisions={i: "SELLER_CONFIRMED" for i in range(len(COLUMNS))}, overrides={}, pinput=pinput, limits=MLIM, as_of=AS_OF, now=NOW)
    jobs.transition(t2, jid, "QUEUED", mapping_id=job["mapping_id"], now=NOW)
    assert r.run_job(t2, jid) == "FAILED"
    assert jobs.get_job(t2, jid)["error_code"] == "QUARANTINE_EXCEEDED" and ads.spend_in_period(t2, "MEESHO", START, END) is None and rmv.get(t2) == 0  # type: ignore[index]


def test_ad_lines_are_tenant_isolated_and_append_only(tmp_path: Path) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    run_file(a, ad_csv(tmp_path, many(40)))
    assert ads.spend_in_period(b, "MEESHO", START, END) is None and ads.report_coverage(b) == []
    for sql in ("UPDATE ad_report_line SET spend = 0", "DELETE FROM ad_report_line"):
        with pytest.raises(Exception, match="permission denied"):
            with tenant_scope(a) as conn:
                conn.execute(text(sql))
