"""CMO 3.0 B8 (migration 20261031_0009; acceptance M7-50, M7-51, M7-52): performance OBSERVED alongside a saved listing version, from the seller's own statements (their SKU in the sales report; the date a
version went live) and their own uploaded sales rows. Everything unsupported stays NOT_ASSESSED and is named; nothing is attributed. The sales rows below are synthetic test rows in a scratch database."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from backend.services import cmo_performance
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import AMAZON, SKU, ListingProvider, body, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

REPORT_SKU = "AQ-BOTTLE-1L"
T0 = date(2026, 9, 1)


def seed_sales(env, rows, tenant=None, marketplace="AMAZON"):
    """rows: (order_ref or None, report sku, order date)."""
    t = tenant or env.tenant
    run, file_ = uuid.uuid4(), uuid.uuid4()
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(t)})
        conn.execute(text("INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                          "VALUES (:id, :t, :mp, 'SETTLEMENT', :sha, 'a.csv', 1, 's3://x', :u, now())"), {"id": str(file_), "t": str(t), "mp": marketplace, "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4())})
        conn.execute(text("INSERT INTO ingestion_run (id, tenant_id, report_file_id, adapter_id, adapter_version, status) VALUES (:id, :t, :f, 'x.v1', 'v1', 'PENDING')"), {"id": str(run), "t": str(t), "f": str(file_)})
        for i, (ref, sku, d) in enumerate(rows, start=1):
            conn.execute(text("INSERT INTO sales_line (tenant_id, ingestion_run_id, marketplace, order_ref, sku, item_title, order_date, source_row_number, source_row_json, confidence) "
                              "VALUES (:t, :r, :mp, :ref, :sku, 'AquaNest bottle', :d, :n, '{}'::jsonb, 'PROVISIONAL')"), {"t": str(t), "r": str(run), "mp": marketplace, "ref": ref, "sku": sku, "d": d, "n": i})


def set_window(env, days=7):
    with env.engine.begin() as conn:
        conn.execute(text("DELETE FROM cmo_platform_config WHERE tenant_id = :t AND key = 'performance_window_days'"), {"t": str(env.tenant)})
        conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, 'performance_window_days', CAST(:v AS jsonb), '2026-01-01')"), {"t": str(env.tenant), "v": json.dumps(days)})


def two_versions(env):
    ru_env(env, ListingProvider())
    first = env.post("full-listing", body("b8")).json()["card"]["generationId"]
    r = env.client().post(f"/api/v1/cmo/listing/{first}/edit", json={"message": "Change bullet 2 to: Holds 1 litre of water"}, headers=env.headers)
    assert r.status_code == 200, r.text
    return first, r.json()["generationId"]


def golive(env, gid, d, status=200):
    r = env.post("performance/golive", {"generation_id": gid, "went_live_on": d.isoformat()})
    assert r.status_code == status, r.text
    return r


def link(env, report_sku=REPORT_SKU, status=200, seed=True):
    if seed:  # the SKU must really be in the seller's own uploaded rows; one old row (outside every window used below) stands for the report
        seed_sales(env, [("link-seed", report_sku, date.today() - timedelta(days=60))])
    r = env.post("performance/sku-link", {"sku": SKU, "marketplace": AMAZON, "report_sku": report_sku})
    assert r.status_code == status, r.text
    return r


def test_with_nothing_confirmed_the_answer_is_not_assessed_and_names_every_missing_item(env):
    two_versions(env)
    p = cmo_performance.assess_for(env.tenant, SKU, "AMAZON")
    assert p["state"] == "NOT_ASSESSED" and p["attribution"] == "NOT_ATTRIBUTED"
    joined = " ".join(p["needs"])
    assert "comparison period length" in joined and "which SKU" in joined and "at least two saved versions" in joined


def test_the_seller_chooses_only_from_skus_that_really_are_in_their_own_reports(env):
    two_versions(env)
    seed_sales(env, [("o1", REPORT_SKU, T0), ("o2", REPORT_SKU, T0), ("o3", "OTHER-SKU", T0)])
    c = env.client().get("/api/v1/cmo/performance/sku-candidates", params={"marketplace": "AMAZON"}, headers=env.headers).json()
    assert {x["reportSku"] for x in c["candidates"]} == {REPORT_SKU, "OTHER-SKU"} and "does not guess" in c["note"]
    assert link(env, "NOT-IN-MY-REPORTS", status=422, seed=False).json()["detail"]["code"] == "SKU_NOT_IN_REPORTS"
    assert env.n("cmo_listing_sku_link") == 0
    link(env)
    assert env.n("cmo_listing_sku_link") == 1
    other_tenant, headers = env.other_tenant()
    seed_sales(env, [("x", "THEIR-SKU", T0)], tenant=other_tenant)
    mine = env.client().get("/api/v1/cmo/performance/sku-candidates", params={"marketplace": "AMAZON"}, headers=env.headers).json()
    assert "THEIR-SKU" not in {x["reportSku"] for x in mine["candidates"]}  # another tenant's rows are invisible


def test_a_link_needs_a_saved_listing_and_a_golive_date_is_checked(env):
    first, second = two_versions(env)
    assert env.post("performance/sku-link", {"sku": "no-such-product", "marketplace": AMAZON, "report_sku": "x"}).status_code == 404
    created = env.q("SELECT created_at::date FROM cmo_generation WHERE id = :g", g=first)[0][0]
    assert golive(env, first, date.today() + timedelta(days=3), status=422).json()["detail"]["code"] == "DATE_IN_FUTURE"
    assert golive(env, first, created - timedelta(days=1), status=422).json()["detail"]["code"] == "BEFORE_CREATED"
    assert env.post("performance/golive", {"generation_id": str(uuid.uuid4()), "went_live_on": created.isoformat()}).status_code == 404
    assert env.n("cmo_listing_golive") == 0
    golive(env, first, created)
    golive(env, first, created)  # a correction / repeat is a new, append-only row
    assert env.n("cmo_listing_golive") == 2


def test_a_foreign_tenants_version_cannot_be_given_a_golive_date(env):
    first, _ = two_versions(env)
    other_tenant, headers = env.other_tenant()
    r = env.post("performance/golive", {"generation_id": first, "went_live_on": date.today().isoformat()}, headers=headers)
    assert r.status_code == 404 and env.n("cmo_listing_golive", tenant=other_tenant) == 0


def put_golive(env, gid, d):
    """Drive the READ side with a statement dated in the past. The service refuses a date before the version was created (tested above), and every test version is created today, so these rows are
    inserted directly: they stand for statements a seller made about versions that existed then."""
    with env.cengine.begin() as conn:  # the context engine (its connections are never shared with the owner-role cleanup, which a leaked empty tenant setting would break)
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
        conn.execute(text("INSERT INTO cmo_listing_golive (tenant_id, generation_id, marketplace, went_live_on, confirmed_by) VALUES (:t, :g, 'AMAZON', :d, :u)"),
                     {"t": str(env.tenant), "g": gid, "d": d, "u": str(env.user_id)})


def days_ago(n):
    return date.today() - timedelta(days=n)


def test_comparable_windows_come_from_real_rows_and_name_the_version(env):
    first, second = two_versions(env)
    set_window(env, 7)
    link(env)
    put_golive(env, second, days_ago(30))  # window: 30..24 days ago
    put_golive(env, first, days_ago(12))   # window: 12..6 days ago
    seed_sales(env, [(f"o{i}", REPORT_SKU, days_ago(30 - i)) for i in range(0, 5)] + [(f"p{i}", REPORT_SKU, days_ago(12 - i)) for i in range(0, 3)]
               + [("same-order", REPORT_SKU, days_ago(12)), ("z", "ANOTHER", days_ago(11)), ("edge", REPORT_SKU, days_ago(5))])
    p = cmo_performance.assess_for(env.tenant, SKU, "AMAZON")
    assert p["state"] == "OBSERVED_COMPARABLE", p
    per = p["periods"]
    assert [x["days"] for x in per] == [7, 7] and [x["versionId"] for x in per] == [second, first] and p["attribution"] == "NOT_ATTRIBUTED"
    assert [x["value"] for x in per] == [5, 4] and p["needs"] == [] and "does not show that the listing change caused it" in p["note"]  # 3 + the same-day order = 4; another SKU is not counted
    blob = json.dumps(p).casefold()
    for banned in ("improved", "uplift", "boost", "because of", "grew", "fell"):
        assert banned not in blob, banned


def test_overlapping_windows_are_incomparable_and_the_reason_is_named(env):
    first, second = two_versions(env)
    set_window(env, 7)
    link(env)
    put_golive(env, second, days_ago(15))
    put_golive(env, first, days_ago(12))  # starts inside the other window
    seed_sales(env, [(f"o{i}", REPORT_SKU, days_ago(15 - i)) for i in range(0, 10)])
    p = cmo_performance.assess_for(env.tenant, SKU, "AMAZON")
    assert p["state"] == "INCOMPARABLE" and "OVERLAPPING_PERIODS" in p["reasons"] and p["attribution"] == "NOT_ATTRIBUTED"


def test_uncovered_data_or_unreferenced_rows_or_no_window_keep_it_not_assessed(env):
    first, second = two_versions(env)
    link(env)
    put_golive(env, second, days_ago(30))
    put_golive(env, first, days_ago(12))
    seed_sales(env, [("o1", REPORT_SKU, days_ago(30))])
    assert "period length" in " ".join(cmo_performance.assess_for(env.tenant, SKU, "AMAZON")["needs"])  # no operator window: NOT_ASSESSED
    set_window(env, 7)
    p = cmo_performance.assess_for(env.tenant, SKU, "AMAZON")
    assert p["state"] == "NOT_ASSESSED" and any("uploaded sales data covering" in n for n in p["needs"])  # the uploaded data ends before the windows do
    seed_sales(env, [(None, REPORT_SKU, days_ago(29)), ("o9", REPORT_SKU, days_ago(12)), ("o10", REPORT_SKU, days_ago(5))])
    p = cmo_performance.assess_for(env.tenant, SKU, "AMAZON")
    assert p["state"] == "NOT_ASSESSED" and any("order reference on every sales row" in n for n in p["needs"])  # a row without an order reference makes that window's count unreliable


def test_the_compare_answer_carries_the_performance_block_and_nothing_else_changed(env):
    first, second = two_versions(env)
    r = env.client().get("/api/v1/cmo/listing-history/compare", params={"older": first, "newer": second}, headers=env.headers)
    assert r.status_code == 200
    perf = r.json()["performance"]
    assert perf["state"] == "NOT_ASSESSED" and perf["needs"] and perf["attribution"] == "NOT_ATTRIBUTED"
    assert env.n("cmo_generation", "output_type = 'LISTING_COPY'") == 2  # reading it created no version, and the answer was free


def test_m7_51_the_compare_answer_shows_comparable_observations_when_everything_is_confirmed(env):
    first, second = two_versions(env)
    set_window(env, 7)
    link(env)
    put_golive(env, second, days_ago(30))
    put_golive(env, first, days_ago(12))
    seed_sales(env, [(f"o{i}", REPORT_SKU, days_ago(30 - i)) for i in range(0, 5)] + [(f"p{i}", REPORT_SKU, days_ago(12 - i)) for i in range(0, 3)] + [("edge", REPORT_SKU, days_ago(5))])
    perf = env.client().get("/api/v1/cmo/listing-history/compare", params={"older": first, "newer": second}, headers=env.headers).json()["performance"]
    assert perf["state"] == "OBSERVED_COMPARABLE" and perf["attribution"] == "NOT_ATTRIBUTED" and [x["value"] for x in perf["periods"]] == [5, 3] and perf["needs"] == []


def test_m7_52_the_compare_answer_refuses_incomparable_periods(env):
    first, second = two_versions(env)
    set_window(env, 7)
    link(env)
    put_golive(env, second, days_ago(15))
    put_golive(env, first, days_ago(12))
    seed_sales(env, [(f"o{i}", REPORT_SKU, days_ago(15 - i)) for i in range(0, 10)])
    perf = env.client().get("/api/v1/cmo/listing-history/compare", params={"older": first, "newer": second}, headers=env.headers).json()["performance"]
    assert perf["state"] == "INCOMPARABLE" and "overlapping periods" in perf["missing"]
