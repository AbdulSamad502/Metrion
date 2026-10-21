"""`POST /cfo/uploads` and the `/cfo/jobs/*` routes through the real HTTP stack and real Postgres (scratch database); only Clerk is faked and the mapping
"model" is a fixed function — no LLM is called. Covers cfo-data-intelligence.md §6.1–§6.5: streaming upload, background job, polling, duplicate uploads,
seller-confirmed mapping with its permission, cancel, failure messages and tenant isolation."""

from __future__ import annotations

import time
import uuid
from datetime import date
from fractions import Fraction

import pytest
from sqlalchemy import text

from backend.repositories import app_user_repo, membership_repo
from backend.auth.permissions import AGENT_CFO
from backend.tenant_context import tenant_scope
from tests.integration.test_cfo_imports import _csv, _register_owner, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)

KNOWN_HEADER = "Meesho Order Number,Sub Order No,Reason for Credit Entry,Return Status\n"
UNKNOWN_HEADER = "Order ID,Line ID,Qty,Selling Price,Invoice Date,Status\n"


def known(n: int) -> bytes:
    return (KNOWN_HEADER + "".join(f"ORD-{i},ORD-{i}_1,DELIVERED,Delivered\n" for i in range(n))).encode()


def unknown(n: int = 40) -> bytes:
    rows = "".join(f"B-{i},B-{i}-1,2,{100 + i}.50,{1 + i % 28:02d}/10/2026,{'DELIVERED' if i % 4 else 'RETURNED'}\n" for i in range(n))
    return (UNKNOWN_HEADER + rows).encode()


def fake_mapping(inp):  # the "model": fixed JSON, never a real call
    return {"fields": [
        {"source_column": "Order ID", "index": 0, "canonical_field": "order_ref", "transform": "IDENTITY"},
        {"source_column": "Line ID", "index": 1, "canonical_field": "line_ref", "transform": "IDENTITY"},
        {"source_column": "Qty", "index": 2, "canonical_field": "quantity", "transform": "IDENTITY"},
        {"source_column": "Selling Price", "index": 3, "canonical_field": "gross_item_amount", "transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE", "sign_convention": "AS_IS"},
        {"source_column": "Invoice Date", "index": 4, "canonical_field": "invoice_date", "transform": "DATE_DMY"},
        {"source_column": "Status", "index": 5, "canonical_field": "return_status", "transform": "IDENTITY"},
    ], "unmapped_columns": []}


@pytest.fixture
def with_runner(monkeypatch):
    from data_foundation.ingestion.job_runner import JobRunner, RunnerConfig
    from data_foundation.ingestion.streaming import StreamLimits
    from data_foundation.mapping.validator import MappingLimits

    from backend.services import cfo_ingestion

    def install(proposer=None):
        runner = JobRunner(
            config=RunnerConfig(max_workers=2, stale_after_seconds=600, profile_rows=2000, sample_rows=20),
            stream_limits=StreamLimits(chunk_rows=500, max_rows=100_000, header_scan_rows=30, min_header_fill=Fraction(6, 10),
                                       max_uncompressed_bytes=50 * 1024 * 1024, max_zip_ratio=200, max_zip_members=200, max_sheets=20),
            mapping_limits=MappingLimits(min_parse_rate=Fraction(98, 100), tax_consistency_rate=Fraction(98, 100), tax_tolerance_paise=1,
                                         key_unique_rate=Fraction(98, 100), mixed_sign_low=Fraction(2, 100), max_date_span_years=5,
                                         unit_fraction_share=Fraction(2, 100)),
            as_of=lambda: date(2026, 10, 21), proposer=proposer, proposed_by="MODEL:mock",
        )
        cfo_ingestion.set_runner_for_tests(runner)
        monkeypatch.setattr(cfo_ingestion, "stream_limits", lambda: runner._limits)
        monkeypatch.setattr(cfo_ingestion, "mapping_limits", lambda: runner._mapping_limits)
        return runner

    yield install
    cfo_ingestion.set_runner_for_tests(None)


def post_upload(client, headers, content: bytes, *, name="report.csv", marketplace="MEESHO", kind="SALES", **extra):
    return client.post("/api/v1/cfo/uploads", params={"marketplace": marketplace, "report_kind": kind, **extra},
                       files={"file": (name, content, "text/csv")}, headers=headers)


def wait_for(client, headers, job_id, until=("DONE", "FAILED", "CANCELLED", "AWAITING_MAPPING_CONFIRMATION"), timeout=60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/cfo/jobs/{job_id}", headers=headers).json()
        if body["status"] in until:
            return body
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} did not reach {until}: {body}")


def partner_with(fake_clerk, tenant, *keys) -> dict[str, str]:
    user = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(clerk_user_id=user, email=f"{user}@example.com", email_verified=True, auth_provider="GOOGLE", display_name="Partner")
    row = app_user_repo.get_by_clerk_user_id(user)
    membership_repo.upsert_partner(tenant, row["id"], role="PARTNER", status="ACTIVE")
    membership_repo.set_permissions(tenant, row["id"], {k: True for k in keys})
    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (user, f"org_{tenant}")
    return {"Authorization": f"Bearer {token}"}


def sales_count(tenant) -> int:
    with tenant_scope(tenant) as conn:
        return conn.execute(text("SELECT count(*) FROM sales_line WHERE tenant_id = :t"), {"t": str(tenant)}).scalar_one()


# ============================================================================================ access
def test_uploads_and_jobs_need_a_signed_in_member_with_the_cfo_key(app_client, fake_clerk, two_tenants, with_runner):
    a, _ = two_tenants
    with_runner()
    files = {"file": ("r.csv", known(5), "text/csv")}
    assert app_client.post("/api/v1/cfo/uploads", params={"marketplace": "MEESHO", "report_kind": "SALES"}, files=files).status_code == 401
    nokey = partner_with(fake_clerk, a)  # no grants
    assert post_upload(app_client, nokey, known(5)).status_code == 403
    assert app_client.get("/api/v1/cfo/jobs", headers=nokey).status_code == 403


# ===================================================================================== known formats
def test_upload_returns_202_then_the_job_runs_to_done_with_a_quality_report(app_client, fake_clerk, two_tenants, with_runner):
    a, _ = two_tenants
    with_runner()
    headers = _register_owner(fake_clerk, a)
    resp = post_upload(app_client, headers, known(1300))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["duplicate"] is False and body["job"]["status"] in ("QUEUED", "PROFILING", "PARSING", "DONE")
    assert "file://" not in resp.text and "storage" not in resp.text.lower()  # a storage location is never sent to a client
    done = wait_for(app_client, headers, body["job"]["jobId"])
    assert done["status"] == "DONE" and done["outcome"]["persisted_row_count"] == 1300 and done["errorCode"] is None
    assert done["qualityReport"]["rows"]["posted"] == 1300 and done["qualityReport"]["confidence"] == "PROVISIONAL"
    assert sales_count(a) == 1300
    assert [j["jobId"] for j in app_client.get("/api/v1/cfo/jobs", headers=headers).json()] == [body["job"]["jobId"]]


def test_the_same_bytes_uploaded_twice_reuse_the_file_and_the_job(app_client, fake_clerk, two_tenants, with_runner):
    a, _ = two_tenants
    with_runner()
    headers = _register_owner(fake_clerk, a)
    first = post_upload(app_client, headers, known(200)).json()
    wait_for(app_client, headers, first["job"]["jobId"])
    again = post_upload(app_client, headers, known(200)).json()
    assert again["duplicate"] is True and again["reportFileId"] == first["reportFileId"] and again["job"]["jobId"] == first["job"]["jobId"]
    assert sales_count(a) == 200
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM report_file WHERE tenant_id = :t"), {"t": str(a)}).scalar_one() == 1


@pytest.mark.parametrize("params,name,content,status", [
    ({"marketplace": "SNAPDEAL", "report_kind": "SALES"}, "r.csv", b"a,b\n1,2\n", 400),
    ({"marketplace": "MEESHO", "report_kind": "EXPENSE"}, "r.csv", b"a,b\n1,2\n", 400),
    ({"marketplace": "MEESHO", "report_kind": "SALES"}, "r.pdf", b"%PDF", 400),
    ({"marketplace": "MEESHO", "report_kind": "SALES"}, "r.xlsm", b"x", 400),
    ({"marketplace": "MEESHO", "report_kind": "SALES"}, "r.csv", b"", 400),
])
def test_bad_upload_requests_are_refused_before_anything_is_stored(app_client, fake_clerk, two_tenants, with_runner, params, name, content, status):
    a, _ = two_tenants
    with_runner()
    headers = _register_owner(fake_clerk, a)
    resp = app_client.post("/api/v1/cfo/uploads", params=params, files={"file": (name, content, "text/csv")}, headers=headers)
    assert resp.status_code == status, resp.text
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM report_file")).scalar_one() == 0


def test_an_oversized_upload_is_refused_with_413_and_leaves_no_partial_file(app_client, fake_clerk, two_tenants, with_runner, monkeypatch, tmp_path):
    from backend.api.v1 import cfo as cfo_routes

    a, _ = two_tenants
    with_runner()
    headers = _register_owner(fake_clerk, a)
    monkeypatch.setattr(cfo_routes, "cfo_stream_max_upload_bytes", lambda: 200)
    resp = post_upload(app_client, headers, known(500))
    assert resp.status_code == 413 and "upload limit" in resp.json()["detail"]
    assert list(tmp_path.iterdir()) == []  # the partially written temp file was removed


def test_an_unrecognised_format_without_a_mapping_model_fails_plainly_and_a_reupload_is_a_new_attempt(app_client, fake_clerk, two_tenants, with_runner):
    a, _ = two_tenants
    with_runner(proposer=None)
    headers = _register_owner(fake_clerk, a)
    first = post_upload(app_client, headers, unknown()).json()
    failed = wait_for(app_client, headers, first["job"]["jobId"])
    assert failed["status"] == "FAILED" and failed["errorCode"] == "NO_MATCHING_FORMAT" and "Nothing was saved" in failed["errorDetail"]
    again = post_upload(app_client, headers, unknown()).json()
    assert again["duplicate"] is True and again["job"]["jobId"] != first["job"]["jobId"] and again["job"]["attempt"] == 2
    assert sales_count(a) == 0


# ============================================================================================ mapping
def test_unfamiliar_format_waits_for_the_seller_and_confirming_needs_financials_adjust(app_client, fake_clerk, two_tenants, with_runner):
    a, _ = two_tenants
    with_runner(proposer=fake_mapping)
    owner = _register_owner(fake_clerk, a)
    job = post_upload(app_client, owner, unknown(40)).json()["job"]["jobId"]
    waiting = wait_for(app_client, owner, job)
    assert waiting["status"] == "AWAITING_MAPPING_CONFIRMATION" and sales_count(a) == 0  # nothing is posted before the seller confirms

    m = app_client.get(f"/api/v1/cfo/jobs/{job}/mapping", headers=owner).json()
    assert m["status"] == "PROPOSED" and m["proposedBy"] == "MODEL:mock" and len(m["fields"]) == 6 and m["verified"] is False
    price = next(f for f in m["fields"] if f["sourceColumn"] == "Selling Price")
    assert price["decision"] == "PENDING" and any("GST" in r or "tax" in r for r in price["evidence"]["confirm_reasons"])

    cfo_only = partner_with(fake_clerk, a, AGENT_CFO)  # can see the mapping, cannot decide what the columns mean
    assert app_client.get(f"/api/v1/cfo/jobs/{job}/mapping", headers=cfo_only).status_code == 200
    body = {"decisions": {str(i): "SELLER_CONFIRMED" for i in range(6)}}
    assert app_client.post(f"/api/v1/cfo/jobs/{job}/mapping/confirm", json=body, headers=cfo_only).status_code == 403

    silent = app_client.post(f"/api/v1/cfo/jobs/{job}/mapping/confirm", json={"decisions": {}}, headers=owner)
    assert silent.status_code == 422 and any("needs your confirmation" in r for r in silent.json()["detail"]["reasons"])

    bad = app_client.post(f"/api/v1/cfo/jobs/{job}/mapping/confirm", json={**body, "overrides": {"3": {"transform": "PAISE_IDENTITY"}}}, headers=owner)
    assert bad.status_code == 422 and any("M-UNT" in r for r in bad.json()["detail"]["reasons"])
    assert wait_for(app_client, owner, job)["status"] == "AWAITING_MAPPING_CONFIRMATION"  # refusals changed nothing

    ok = app_client.post(f"/api/v1/cfo/jobs/{job}/mapping/confirm", json=body, headers=owner)
    assert ok.status_code == 202, ok.text
    done = wait_for(app_client, owner, job)
    assert done["status"] == "DONE" and done["qualityReport"]["format"]["mapped"] is True and sales_count(a) == 40
    with tenant_scope(a) as conn:
        conf = conn.execute(text("SELECT DISTINCT confidence FROM sales_line WHERE tenant_id = :t"), {"t": str(a)}).scalars().all()
    assert conf == ["PROVISIONAL"]  # mapped data is never VERIFIED
    assert app_client.post(f"/api/v1/cfo/jobs/{job}/mapping/confirm", json=body, headers=owner).status_code == 409  # not waiting any more


# ================================================================================ cancel + isolation
def test_cancel_a_waiting_job_then_cancelling_again_or_a_foreign_job(app_client, fake_clerk, two_tenants, with_runner):
    a, b = two_tenants
    with_runner(proposer=fake_mapping)
    owner_a, owner_b = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    job = post_upload(app_client, owner_a, unknown()).json()["job"]["jobId"]
    wait_for(app_client, owner_a, job)
    assert app_client.post(f"/api/v1/cfo/jobs/{job}/cancel", headers=owner_b).status_code == 404  # B cannot cancel A's job
    ok = app_client.post(f"/api/v1/cfo/jobs/{job}/cancel", headers=owner_a)
    assert ok.status_code == 200 and ok.json()["status"] == "CANCELLED"
    assert app_client.post(f"/api/v1/cfo/jobs/{job}/cancel", headers=owner_a).status_code == 409
    assert sales_count(a) == 0


def test_another_tenants_job_and_mapping_are_a_plain_404(app_client, fake_clerk, two_tenants, with_runner):
    a, b = two_tenants
    with_runner(proposer=fake_mapping)
    owner_a, owner_b = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    job = post_upload(app_client, owner_a, unknown()).json()["job"]["jobId"]
    wait_for(app_client, owner_a, job)
    assert app_client.get(f"/api/v1/cfo/jobs/{job}", headers=owner_b).status_code == 404
    assert app_client.get(f"/api/v1/cfo/jobs/{job}/mapping", headers=owner_b).status_code == 404
    assert app_client.post(f"/api/v1/cfo/jobs/{job}/mapping/confirm", json={"decisions": {}}, headers=owner_b).status_code == 404
    assert app_client.get("/api/v1/cfo/jobs", headers=owner_b).json() == []


def test_the_legacy_ingest_route_still_works_unchanged(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    resp = app_client.post("/api/v1/cfo/ingest", params={"marketplace": "MEESHO", "adapter_id": "meesho.orders.v1"},
                           files={"file": ("o.csv", _csv(20), "text/csv")}, headers=headers)
    assert resp.status_code == 200 and resp.json()["rowCountAccepted"] == 20


# ============================================================================ choosing the report type (adapter_id)
def _amazon_bytes(n: int = 20) -> bytes:
    from data_foundation.adapters.registry import ADAPTER_REGISTRY

    cols = [k[0] if isinstance(k, tuple) else k for k in ADAPTER_REGISTRY["amazon.mtr_b2c.v1"].column_map]
    return (",".join(cols) + "\n" + "".join(",".join(f"{c.split()[0]}-{i}" for c in cols) + "\n" for i in range(n))).encode()


def test_amazon_mtr_needs_the_report_type_chosen_and_the_choice_is_validated_up_front(app_client, fake_clerk, two_tenants, with_runner):
    a, _ = two_tenants
    with_runner()
    headers = _register_owner(fake_clerk, a)
    first = post_upload(app_client, headers, _amazon_bytes(), marketplace="AMAZON").json()  # B2B and B2C share headers: no guess
    failed = wait_for(app_client, headers, first["job"]["jobId"])
    assert failed["status"] == "FAILED" and failed["errorCode"] == "AMBIGUOUS_ADAPTER" and "adapter_id" in failed["errorDetail"]

    for bad, why in (("amazon.nope.v9", "unknown"), ("flipkart.sales_report.v1", "wrong marketplace"), ("amazon.settlement.v2", "wrong kind")):
        r = post_upload(app_client, headers, _amazon_bytes(), marketplace="AMAZON", adapter_id=bad)
        assert r.status_code == 400, (why, r.text)

    again = post_upload(app_client, headers, _amazon_bytes(), marketplace="AMAZON", adapter_id="amazon.mtr_b2c.v1").json()
    assert again["duplicate"] is True and again["job"]["attempt"] == 2  # same bytes: a new attempt, now with the choice
    done = wait_for(app_client, headers, again["job"]["jobId"])
    assert done["status"] == "DONE" and done["adapterId"] == "amazon.mtr_b2c.v1" and sales_count(a) == 20
