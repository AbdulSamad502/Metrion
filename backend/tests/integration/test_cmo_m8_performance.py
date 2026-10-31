"""CMO 3.0 M8 (migration 20261031_0010): importing a seller's performance report, the dashboard, the seller-set comparison window, the replace-guard on earlier statements, and the before/after view of a
saved listing version. Everything runs on synthetic rows in a scratch database; nothing here calls a model or spends a credit."""

from __future__ import annotations

import io
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_b8_performance import AMAZON, REPORT_SKU, SKU, days_ago, golive, link, put_golive, two_versions
from tests.integration.test_cmo_m6_integration import ListingProvider, ru_env  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

HEAD = "Date,SKU,Impressions,Clicks,Orders,Units Sold,Sales\n"


def report(days, sku=REPORT_SKU, imp=100, clk=10, orders=2, units=2, sales="500.00"):
    """days: iterable of dates -> CSV bytes with one row each."""
    return (HEAD + "".join(f"{d.isoformat()},{sku},{imp},{clk},{orders},{units},{sales}\n" for d in days)).encode()


def span(a, b):
    return [days_ago(n) for n in range(a, b - 1, -1)]  # a days ago ... b days ago, oldest first


def up(env, path, data, name="report.csv", marketplace="AMAZON", extra=None, headers=None):
    return env.client().post(f"/api/v1/cmo/performance/{path}", files={"file": (name, io.BytesIO(data), "text/csv")}, data={"marketplace": marketplace, **(extra or {})},
                             headers=env.headers if headers is None else headers)


def importing(env, data, name="report.csv", marketplace="AMAZON", status=200):
    p = up(env, "import/preview", data, name, marketplace)
    assert p.status_code == 200, p.text
    r = up(env, "import", data, name, marketplace, extra={"expected_sha256": p.json()["sha256"]})
    assert r.status_code == status, r.text
    return r


def get(env, path, headers=None, **params):
    return env.client().get(f"/api/v1/cmo/performance/{path}", params=params, headers=env.headers if headers is None else headers)


# ------------------------------------------------------------------------------------------------ the import
def test_preview_saves_nothing_then_import_saves_the_rows_with_source_period_and_user(env):
    data = report(span(6, 0))
    p = up(env, "import/preview", data).json()
    assert p["ok"] and p["canImport"] and p["rowCount"] == 7 and p["newRows"] == 7 and p["aiCredits"] == 0 and p["period"]["days"] == 7
    assert p["metrics"] == ["impressions", "clicks", "orders", "units", "sales"] and env.n("cmo_perf_import") == 0 and env.n("cmo_perf_line") == 0
    r = importing(env, data).json()
    assert r["rowsSaved"] == 7 and r["aiCredits"] == 0 and "Nothing was published" in r["message"]
    row = env.q("SELECT marketplace, source_name, period_start, period_end, rows_saved, imported_by FROM cmo_perf_import")[0]
    assert (row[0], row[1], row[2], row[3], row[4]) == ("AMAZON", "report.csv", days_ago(6), days_ago(0), 7) and str(row[5]) == str(env.user_id)
    assert env.q("SELECT sales_paise FROM cmo_perf_line LIMIT 1")[0][0] == 50000


def test_a_blank_metric_is_stored_as_missing_never_as_zero(env):
    data = (HEAD + f"{days_ago(1).isoformat()},{REPORT_SKU},100,,2,-,\n").encode()
    importing(env, data)
    assert env.q("SELECT impressions, clicks, orders, units, sales_paise FROM cmo_perf_line")[0] == (100, None, 2, None, None)


def test_the_same_file_cannot_be_imported_twice_and_existing_records_are_never_overwritten(env):
    data = report(span(3, 0))
    importing(env, data)
    again = up(env, "import", data, extra={"expected_sha256": up(env, "import/preview", data).json()["sha256"]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "ALREADY_IMPORTED" and env.n("cmo_perf_line") == 4 and env.n("cmo_perf_import") == 1
    same_rows_other_file = report(span(3, 0)) + b"\n\n"  # different bytes, identical records
    p = up(env, "import/preview", same_rows_other_file).json()
    assert p["duplicateRows"] == 4 and p["newRows"] == 0 and not p["canImport"]
    assert up(env, "import", same_rows_other_file, extra={"expected_sha256": p["sha256"]}).json()["detail"]["code"] == "NOTHING_NEW"
    conflicting = report(span(3, 0), imp=999)
    c = up(env, "import/preview", conflicting).json()
    assert c["conflictCount"] == 4 and not c["canImport"] and "never overwritten" in c["conflicts"][0]["message"]
    assert up(env, "import", conflicting, extra={"expected_sha256": c["sha256"]}).json()["detail"]["code"] == "CONFLICTING_RECORDS"
    assert env.q("SELECT DISTINCT impressions FROM cmo_perf_line") == [(100,)] and env.n("cmo_perf_import") == 1


def test_a_partly_new_file_adds_only_the_new_rows(env):
    importing(env, report(span(3, 2)))
    r = importing(env, report(span(3, 0))).json()
    assert r["rowsSaved"] == 2 and r["rowsSkipped"] == 2 and env.n("cmo_perf_line") == 4


def test_invalid_files_are_refused_with_plain_reasons_and_save_nothing(env):
    bad = (HEAD + f"{days_ago(1).isoformat()},{REPORT_SKU},5,50,1,1,1\n" + f"not-a-date,{REPORT_SKU},1,1,1,1,1\n").encode()
    p = up(env, "import/preview", bad).json()
    assert not p["ok"] and p["errorCount"] == 2 and not p["canImport"] and any("more than impressions" in e["message"] for e in p["errors"])
    r = up(env, "import", bad, extra={"expected_sha256": p["sha256"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_FILE" and env.n("cmo_perf_line") == 0 and env.n("cmo_perf_import") == 0
    assert up(env, "import/preview", b"", "x.csv").json()["detail"]["code"] == "EMPTY_FILE"
    assert up(env, "import/preview", b"%PDF-1.4", "x.pdf").json()["detail"]["code"] == "BAD_FILE"
    assert up(env, "import/preview", b"PK\x03\x04junk", "x.xlsx").json()["detail"]["code"] == "BAD_FILE"
    assert up(env, "import/preview", report(span(1, 0)), marketplace="EBAY").status_code == 422


def test_the_import_must_be_the_file_that_was_previewed(env):
    p = up(env, "import/preview", report(span(2, 0))).json()
    r = up(env, "import", report(span(2, 0), imp=7), extra={"expected_sha256": p["sha256"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "FILE_CHANGED" and env.n("cmo_perf_line") == 0


def test_an_xlsx_workbook_is_read(env):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "SKU", "Impressions", "Clicks"])
    ws.append([days_ago(2), REPORT_SKU, 300, 30])
    buf = io.BytesIO()
    wb.save(buf)
    p = up(env, "import/preview", buf.getvalue(), "report.xlsx").json()
    assert p["ok"] and p["metrics"] == ["impressions", "clicks"] and p["newRows"] == 1, p


def test_imports_are_invisible_to_another_tenant_and_the_same_file_imports_there_independently(env):
    data = report(span(2, 0))
    importing(env, data)
    other, headers = env.other_tenant()
    assert get(env, "imports", headers).json()["imports"] == [] and get(env, "dashboard", headers).json()["current"]["metrics"]["orders"]["state"] == "UNAVAILABLE"
    p = up(env, "import/preview", data, headers=headers).json()
    assert p["alreadyImported"] is None and p["canImport"]
    assert up(env, "import", data, extra={"expected_sha256": p["sha256"]}, headers=headers).status_code == 200
    assert env.n("cmo_perf_line", tenant=other) == 3 and env.n("cmo_perf_line") == 3


# ------------------------------------------------------------------------------------------------ the dashboard
def test_with_no_imports_every_metric_is_unavailable_not_zero(env):
    d = get(env, "dashboard").json()
    assert d["aiCredits"] == 0 and all(m["state"] == "UNAVAILABLE" and m["value"] is None for m in d["current"]["metrics"].values()) and d["dataSpan"]["lastImportAt"] is None
    assert d["insights"][0]["kind"] == "INSUFFICIENT_DATA"


def test_totals_rates_and_previous_period_come_from_the_imported_rows(env):
    env.post("performance/window", {"days": 7})
    importing(env, report(span(13, 7), imp=100, clk=10, orders=2))  # previous 7 days
    importing(env, report(span(6, 0), imp=200, clk=10, orders=2))          # latest 7 days
    d = get(env, "dashboard").json()
    cur, prev = d["current"]["metrics"], d["previous"]["metrics"]
    assert d["current"]["complete"] and (cur["impressions"]["value"], cur["clicks"]["value"], cur["orders"]["value"], cur["units"]["value"], cur["sales"]["value"]) == (1400, 70, 14, 14, 350000)
    assert (cur["ctr"]["value"], cur["cvr"]["value"], prev["ctr"]["value"]) == (500, 2000, 1000)
    assert d["comparison"]["impressions"]["difference"] == 700 and d["comparison"]["ctr"]["direction"] == "DOWN"
    assert d["dataSpan"]["last"] == days_ago(0).isoformat() and d["dataSpan"]["lastImportAt"] and d["source"] == "your imported performance reports"
    assert [t["date"] for t in d["trend"]] == [x.isoformat() for x in span(6, 0)] and d["insights"][0]["kind"] == "IMPRESSIONS_UP_CTR_DOWN"
    assert d["insights"][0]["nextStep"] and d["insights"][0]["limits"] and d["imports"][0]["sourceName"] == "report.csv"


def test_an_incomplete_period_never_shows_a_misleading_total(env):
    importing(env, report(span(6, 0)))
    importing(env, report(span(40, 38)), name="old.csv")
    d = get(env, "dashboard", start=days_ago(40).isoformat(), end=days_ago(0).isoformat()).json()
    o = d["current"]["metrics"]["orders"]
    assert o["state"] == "NOT_ASSESSED" and o["value"] is None and "uncovered" in o["reason"] and not d["current"]["complete"]
    assert d["comparison"]["orders"]["state"] == "NOT_ASSESSED" and any("cover" in x for x in d["limits"])
    ok = get(env, "dashboard", start=days_ago(6).isoformat(), end=days_ago(0).isoformat()).json()
    assert ok["current"]["complete"] and ok["current"]["metrics"]["orders"]["value"] == 14


def test_filtering_by_product_needs_the_sellers_confirmed_link(env):
    two_versions(env)
    importing(env, report(span(6, 0)))
    importing(env, report(span(6, 0), sku="OTHER-1", orders=50), name="other.csv")
    env.post("performance/window", {"days": 7})
    anywhere = get(env, "dashboard").json()["current"]["metrics"]["orders"]["value"]
    assert anywhere == 7 * 2 + 7 * 50
    d = get(env, "dashboard", sku=SKU).json()
    assert d["needs"] and "which SKU" in d["needs"][0] and d["current"]["metrics"]["orders"]["state"] == "UNAVAILABLE"
    link(env, seed=False)
    d = get(env, "dashboard", sku=SKU, marketplace="AMAZON").json()
    assert d["needs"] == [] and d["current"]["metrics"]["orders"]["value"] == 14 and d["filters"]["sku"] == SKU
    assert get(env, "dashboard", sku="nope").status_code == 404 and get(env, "dashboard", marketplace="EBAY").status_code == 422
    assert get(env, "dashboard", start="2026-01-01").status_code == 422 and get(env, "dashboard", start="2026-01-05", end="2026-01-01").status_code == 422


# ------------------------------------------------------------------------------------------------ the seller's window and statements
def test_the_comparison_window_is_validated_and_the_sellers_setting_is_used(env):
    for bad in (0, 6, 91, -3, "7", 7.5, None):
        r = env.post("performance/window", {"days": bad})
        assert r.status_code == 422, (bad, r.text)
    assert env.n("cmo_perf_setting") == 0 and get(env, "mappings").json()["windowDays"] is None and "comparison period length" in get(env, "mappings").json()["missing"][0]
    assert env.post("performance/window", {"days": 14}).status_code == 200 and env.post("performance/window", {"days": 21}).status_code == 200
    m = get(env, "mappings").json()
    assert m["windowDays"] == 21 and m["windowSetBy"] == "YOU" and env.n("cmo_perf_setting") == 2  # a change is a new row; the earlier one stays


def test_an_earlier_link_or_go_live_date_is_never_silently_replaced(env):
    first, second = two_versions(env)
    importing(env, report(span(3, 0)))
    importing(env, report(span(3, 0), sku="ALT-1"), name="alt.csv")
    link(env, seed=False)
    again = env.post("performance/sku-link", {"sku": SKU, "marketplace": AMAZON, "report_sku": "ALT-1"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "LINK_EXISTS" and env.n("cmo_listing_sku_link") == 1
    ok = env.post("performance/sku-link", {"sku": SKU, "marketplace": AMAZON, "report_sku": "ALT-1", "replace": True}).json()
    assert ok["previous"] == REPORT_SKU and env.n("cmo_listing_sku_link") == 2
    created = env.q("SELECT created_at::date FROM cmo_generation WHERE id = :g", g=first)[0][0]
    golive(env, first, created)
    later = created + timedelta(days=0)
    assert env.post("performance/golive", {"generation_id": first, "went_live_on": later.isoformat()}).status_code == 200  # the same date again is just a repeat
    item = get(env, "mappings").json()["items"][0]
    assert item["reportSku"] == "ALT-1" and [h["reportSku"] for h in item["history"]["links"]] == ["ALT-1", REPORT_SKU]
    assert item["status"] == "NEEDS_CONFIRMATION" and any("go-live date for version" in x for x in item["missing"]) and item["versions"][0]["wentLiveOn"] == created.isoformat()


def test_a_golive_date_is_not_assumed_from_creation_or_approval(env):
    two_versions(env)
    m = get(env, "mappings").json()["items"][0]
    assert all(v["wentLiveOn"] is None for v in m["versions"]) and m["reportSku"] is None and len(m["missing"]) == 3  # a link and one date per version


# ------------------------------------------------------------------------------------------------ a saved version, before and after
def test_each_version_is_observed_before_and_after_its_confirmed_golive_date(env):
    first, second = two_versions(env)
    env.post("performance/window", {"days": 7})
    days_before = span(37, 31)
    days_after = span(30, 24)
    rest = [d for d in span(45, 5) if d not in days_before + days_after]
    importing(env, report(rest + days_before) + b"", name="a.csv")
    importing(env, report(days_after, imp=300, clk=15, orders=3), name="b.csv")
    link(env, seed=False)
    put_golive(env, first, days_ago(30))
    put_golive(env, second, days_ago(14))
    v = get(env, "versions", sku=SKU, marketplace="AMAZON").json()
    assert v["aiCredits"] == 0 and v["windowDays"] == 7 and v["windowSetBy"] == "YOU" and v["linked"] == REPORT_SKU and v["needs"] == []
    one = next(x for x in v["versions"] if x["versionId"] == first)
    assert one["state"] == "OBSERVED_COMPARABLE" and one["attribution"] == "NOT_ATTRIBUTED" and one["wentLiveOn"] == days_ago(30).isoformat()
    assert one["previous"]["days"] == one["following"]["days"] == 7 and one["comparison"]["impressions"]["difference"] == 7 * 200
    assert one["comparison"]["ctr"]["previous"] == 1000 and one["comparison"]["ctr"]["current"] == 500
    assert any("Impressions was higher" in s and "after version" in s for s in one["observations"])
    blob = " ".join(one["observations"]).casefold()
    assert "caused" not in blob and "because" not in blob and "improved" not in blob
    assert next(x for x in v["versions"] if x["versionId"] == second)["state"] == "OBSERVED_COMPARABLE"


def test_missing_coverage_or_confirmations_leave_a_version_not_assessed_and_say_what_is_needed(env):
    first, second = two_versions(env)
    v = get(env, "versions", sku=SKU, marketplace="AMAZON").json()
    assert {n for n in v["needs"]} == {"the comparison period length in days (set it on the performance page or tell me in chat)", "your confirmation of which SKU in your reports is this product"}
    assert all(x["state"] == "NOT_ASSESSED" and x["needs"] and x["wentLiveOn"] is None for x in v["versions"])
    env.post("performance/window", {"days": 7})
    importing(env, report(span(20, 14)), name="x.csv")
    link(env, seed=False)
    put_golive(env, first, days_ago(30))
    v = get(env, "versions", sku=SKU, marketplace="AMAZON").json()
    one = next(x for x in v["versions"] if x["versionId"] == first)
    assert one["state"] == "NOT_ASSESSED" and "imported reports covering" in one["needs"][0] and "0 of 7 days before" in one["needs"][0]
    assert one["previous"]["metrics"]["orders"]["state"] in ("UNAVAILABLE", "NOT_ASSESSED")


def test_versions_that_went_live_inside_each_others_periods_are_rejected_as_overlapping(env):
    first, second = two_versions(env)
    env.post("performance/window", {"days": 7})
    importing(env, report(span(45, 5)), name="all.csv")
    link(env, seed=False)
    put_golive(env, first, days_ago(30))
    put_golive(env, second, days_ago(26))
    v = get(env, "versions", sku=SKU, marketplace="AMAZON").json()
    assert all(x["state"] == "INCOMPARABLE" and x["reasons"] == ["OVERLAPPING_PERIODS"] and "comparison" not in x for x in v["versions"])


def test_the_compare_answer_carries_the_new_version_analysis_and_creates_nothing(env):
    first, second = two_versions(env)
    env.post("performance/window", {"days": 7})
    importing(env, report(span(45, 5)), name="all.csv")
    link(env, seed=False)
    put_golive(env, first, days_ago(30))
    before = env.n("cmo_generation")
    r = env.client().get("/api/v1/cmo/listing-history/compare", params={"older": first, "newer": second}, headers=env.headers)
    assert r.status_code == 200, r.text
    perf = r.json()["performance"]
    assert perf["attribution"] == "NOT_ATTRIBUTED" and perf["versionAnalysis"]["sku"] == SKU and env.n("cmo_generation") == before


def test_a_foreign_tenants_product_has_no_version_analysis(env):
    two_versions(env)
    other, headers = env.other_tenant()
    assert get(env, "versions", headers, sku=SKU, marketplace="AMAZON").status_code == 404
    assert get(env, "mappings", headers).json()["items"] == []
