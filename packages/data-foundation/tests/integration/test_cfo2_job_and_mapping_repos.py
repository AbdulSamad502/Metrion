"""ingestion_job / column_mapping / data_quality_report — real Postgres (cfo-data-intelligence.md §5, AC-D3, AC-D9)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

from data_foundation.repositories import column_mapping_repo as cm  # noqa: E402
from data_foundation.repositories import data_quality_report_repo as dq  # noqa: E402
from data_foundation.repositories import ingestion_job_repo as jobs  # noqa: E402
from data_foundation.repositories.tenant_context import tenant_scope  # noqa: E402

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def report_file(t: uuid.UUID) -> uuid.UUID:
    fid = uuid.uuid4()
    with tenant_scope(t) as conn:
        conn.execute(text("""INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                              byte_size, storage_uri, uploaded_by, uploaded_at)
                             VALUES (:id, :t, 'MEESHO', 'ORDER_STATUS', :sha, 'o.csv', 1, 'file://x', :u, :at)"""),
                     {"id": str(fid), "t": str(t), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4()), "at": NOW})
    return fid


def new_job(t: uuid.UUID, f: uuid.UUID | None = None) -> uuid.UUID:
    return jobs.create_job(t, report_file_id=f or report_file(t), report_kind="SALES", created_by=uuid.uuid4())


# ----------------------------------------------------------------------------------------- jobs
def test_job_lifecycle_and_terminal_states_never_move() -> None:
    t = uuid.uuid4()
    j = new_job(t)
    assert jobs.get_job(t, j)["status"] == "QUEUED"  # type: ignore[index]
    assert jobs.transition(t, j, "PROFILING", now=NOW)
    assert jobs.transition(t, j, "PARSING", adapter_id="meesho.orders.v1", total_rows_estimate=2500, now=NOW)
    assert jobs.heartbeat(t, j, 1400, now=NOW + timedelta(seconds=5))
    assert jobs.transition(t, j, "DONE", outcome={"persisted": 2500}, now=NOW + timedelta(seconds=9))
    row = jobs.get_job(t, j)
    assert row["status"] == "DONE" and row["adapter_id"] == "meesho.orders.v1" and row["outcome"] == {"persisted": 2500}  # type: ignore[index]
    assert row["started_at"] is not None and row["finished_at"] is not None  # type: ignore[index]
    # a late worker cannot resurrect or alter a finished job
    assert not jobs.transition(t, j, "PARSING", now=NOW)
    assert not jobs.transition(t, j, "FAILED", error_code="X", now=NOW)
    assert not jobs.heartbeat(t, j, 5, now=NOW)
    assert jobs.get_job(t, j)["status"] == "DONE"  # type: ignore[index]


def test_only_one_active_job_per_file_but_a_retry_after_failure_is_allowed() -> None:
    t = uuid.uuid4()
    f = report_file(t)
    first = new_job(t, f)
    with pytest.raises(jobs.ActiveJobExists) as e:
        new_job(t, f)
    assert e.value.job_id == first
    jobs.transition(t, first, "FAILED", error_code="ADAPTER_MISMATCH", now=NOW)
    retry = jobs.create_job(t, report_file_id=f, report_kind="SALES", created_by=uuid.uuid4(), attempt=2)
    assert retry != first and jobs.get_job(t, retry)["attempt"] == 2  # type: ignore[index]


def test_cancel_a_running_job_and_the_worker_can_see_it() -> None:
    t = uuid.uuid4()
    j = new_job(t)
    jobs.transition(t, j, "PARSING", now=NOW)
    assert not jobs.is_cancelled(t, j)
    assert jobs.request_cancel(t, j, now=NOW)
    assert jobs.is_cancelled(t, j)
    assert not jobs.transition(t, j, "COMMITTING", now=NOW)  # the cancelled job stays cancelled


def test_stale_jobs_are_failed_as_interrupted_but_a_job_waiting_for_the_seller_is_not() -> None:
    t = uuid.uuid4()
    stale, fresh, waiting = new_job(t), new_job(t), new_job(t)
    jobs.transition(t, stale, "PARSING", now=NOW - timedelta(hours=2))
    jobs.transition(t, fresh, "PARSING", now=NOW - timedelta(seconds=10))
    jobs.transition(t, waiting, "AWAITING_MAPPING_CONFIRMATION", now=NOW - timedelta(days=3))
    assert jobs.recover_stale(t, stale_after_seconds=600, now=NOW) == 1
    s = jobs.get_job(t, stale)
    assert s["status"] == "FAILED" and s["error_code"] == "INTERRUPTED" and "Nothing from it was saved" in s["error_detail"]  # type: ignore[index]
    assert jobs.get_job(t, fresh)["status"] == "PARSING"  # type: ignore[index]
    assert jobs.get_job(t, waiting)["status"] == "AWAITING_MAPPING_CONFIRMATION"  # type: ignore[index]


def test_jobs_are_tenant_isolated_and_a_missing_tenant_fails_closed() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    j = new_job(a)
    assert jobs.get_job(b, j) is None and jobs.list_jobs(b) == []
    assert not jobs.transition(b, j, "CANCELLED", now=NOW)  # B cannot touch A's job
    assert jobs.get_job(a, j)["status"] == "QUEUED"  # type: ignore[index]
    with pytest.raises(ValueError):
        jobs.get_job(None, j)  # type: ignore[arg-type]


def test_rls_is_forced_on_every_new_table() -> None:
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity = true AND relname = ANY(:n)"),
                            {"n": ["ingestion_job", "column_mapping", "column_mapping_field", "data_quality_report", "ad_report_line"]}).all()
    engine.dispose()
    assert {r[0] for r in rows} == {"ingestion_job", "column_mapping", "column_mapping_field", "data_quality_report", "ad_report_line"}


def test_bad_status_is_rejected_by_the_database_itself() -> None:
    from sqlalchemy.exc import IntegrityError

    t = uuid.uuid4()
    j = new_job(t)
    with pytest.raises(IntegrityError):
        with tenant_scope(t) as conn:
            conn.execute(text("UPDATE ingestion_job SET status = 'WHATEVER' WHERE id = :i"), {"i": str(j)})


# -------------------------------------------------------------------------------------- mappings
def fields(*, pending_last: bool = True) -> list[cm.FieldRow]:
    return [
        cm.FieldRow("Order ID", 0, "order_ref", None, "IDENTITY", None, None, "PENDING", {"M-VOC": "ok"}),
        cm.FieldRow("Item Price", 2, "gross_item_amount", None, "RUPEES_TO_PAISE", "INCLUSIVE", "AS_IS", "PENDING", {"M-TAX": "measured inclusive"}),
    ]


def proposal(t: uuid.UUID, fp: str = "fp-1") -> uuid.UUID:
    return cm.create_proposal(t, fingerprint=fp, report_kind="SALES", marketplace="MEESHO", sheet_name=None, header_row=0,
                              proposed_by="MODEL:mock", fields=fields())


def test_a_mapping_cannot_be_confirmed_until_every_field_is_resolved() -> None:
    t = uuid.uuid4()
    m = proposal(t)
    with pytest.raises(cm.MappingNotResolved) as e:
        cm.confirm(t, m, confirmed_by=uuid.uuid4(), field_decisions={0: "SELLER_CONFIRMED"}, now=NOW)  # column 2 left PENDING
    assert e.value.unresolved == (2,)
    got = cm.get_mapping(t, m)
    assert got["status"] == "PROPOSED" and {f["decision"] for f in got["fields"]} == {"PENDING"}  # type: ignore[index]  # nothing changed
    cm.confirm(t, m, confirmed_by=uuid.uuid4(), field_decisions={0: "SELLER_CONFIRMED", 2: "SELLER_OVERRIDDEN"}, now=NOW)
    got = cm.get_mapping(t, m)
    assert got["status"] == "CONFIRMED" and got["confirmed_at"] == NOW and got["verified"] is False  # type: ignore[index]  # never auto-verified
    assert cm.find_confirmed(t, "fp-1")["id"] == m  # type: ignore[index]


def test_a_rejected_decision_blocks_confirmation() -> None:
    t = uuid.uuid4()
    m = proposal(t)
    with pytest.raises(cm.MappingNotResolved):
        cm.confirm(t, m, confirmed_by=uuid.uuid4(), field_decisions={0: "SELLER_CONFIRMED", 2: "REJECTED"}, now=NOW)


def test_confirming_a_newer_version_supersedes_the_old_one() -> None:
    t = uuid.uuid4()
    v1, v2 = proposal(t), proposal(t)
    d = {0: "SELLER_CONFIRMED", 2: "SELLER_CONFIRMED"}
    cm.confirm(t, v1, confirmed_by=uuid.uuid4(), field_decisions=d, now=NOW)
    cm.confirm(t, v2, confirmed_by=uuid.uuid4(), field_decisions=d, now=NOW)
    assert cm.get_mapping(t, v1)["status"] == "SUPERSEDED" and cm.get_mapping(t, v2)["status"] == "CONFIRMED"  # type: ignore[index]
    assert cm.get_mapping(t, v2)["version"] == 2 and cm.find_confirmed(t, "fp-1")["id"] == v2  # type: ignore[index]


def test_a_rejected_mapping_is_never_found_as_confirmed() -> None:
    t = uuid.uuid4()
    m = proposal(t, "fp-x")
    assert cm.reject(t, m) and not cm.reject(t, m)
    assert cm.find_confirmed(t, "fp-x") is None


def test_mappings_are_tenant_isolated() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    m = proposal(a)
    cm.confirm(a, m, confirmed_by=uuid.uuid4(), field_decisions={0: "SELLER_CONFIRMED", 2: "SELLER_CONFIRMED"}, now=NOW)
    assert cm.get_mapping(b, m) is None and cm.find_confirmed(b, "fp-1") is None  # same fingerprint, other tenant: nothing


def test_database_refuses_a_confirmed_mapping_without_a_confirmer() -> None:
    from sqlalchemy.exc import IntegrityError

    t = uuid.uuid4()
    m = proposal(t)
    with pytest.raises(IntegrityError):
        with tenant_scope(t) as conn:
            conn.execute(text("UPDATE column_mapping SET status = 'CONFIRMED' WHERE id = :i"), {"i": str(m)})


# ------------------------------------------------------------------------------ quality report
def test_data_quality_report_round_trip_one_per_job_and_isolated() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    j = new_job(a)
    dq.upsert(a, ingestion_job_id=j, summary={"read": 10, "held": 1})
    dq.upsert(a, ingestion_job_id=j, summary={"read": 10, "held": 2})  # replaces, never a second report
    assert dq.get_for_job(a, j) == {"read": 10, "held": 2}
    assert dq.get_for_job(b, j) is None
