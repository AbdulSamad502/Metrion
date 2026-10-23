"""The owner's own sample files through the real upload -> manual mapping -> confirm -> dashboard path (CP-E; skipped where the files are not on the machine).

* The three mock MTR reports (`Documents/Ecom_Analysis/Data/Raw`) are not a format any verified adapter knows, so they go through the seller's manual mapping and the
  explicit confirmation, exactly as a seller without a mapping model would.
* The real Meesho GST workbooks (`Downloads/gst_3609938_1_2026.zip`) are the formats the Meesho TCS adapters were written from; both must be recognised by themselves.
The figures the dashboard shows are checked against an independent sum of the same file's own column, computed here with Decimal."""

from __future__ import annotations

import csv
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from tests.integration.test_cfo_imports import _register_owner, app_client, fake_clerk  # noqa: F401
from tests.integration.test_cfo_uploads_jobs import wait_for, with_runner  # noqa: F401

RAW = Path(r"C:\Users\ABDUL SAMAD\Documents\Ecom_Analysis\Data\Raw")
ZIP = Path(r"C:\Users\ABDUL SAMAD\Downloads\gst_3609938_1_2026.zip")

pytestmark = pytest.mark.skipif(not RAW.exists(), reason="the owner's sample files are not on this machine")

# (column index, canonical field, extras)
AMAZON = [
    (5, "order_ref", {}), (9, "line_ref", {}), (13, "sku", {}), (10, "quantity", {}),
    (38, "gross_item_amount", {"transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE"}),
    (52, "taxable_amount", {"transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE"}),
    (2, "invoice_date", {"transform": "DATE_MDY"}), (8, "order_date", {"transform": "DATE_MDY"}), (78, "return_status", {}),
    (50, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "PLATFORM_FEE"}),
    (75, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "MARKETPLACE_FEE_GENERIC"}),
]
FLIPKART = [
    (5, "order_ref", {}), (9, "line_ref", {}), (13, "sku", {}), (10, "quantity", {}),
    (38, "gross_item_amount", {"transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE"}),
    (52, "taxable_amount", {"transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE"}),
    (2, "invoice_date", {"transform": "DATE_DMY"}), (8, "order_date", {"transform": "DATE_DMY"}), (77, "return_status", {}),
    (50, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "COMMISSION"}),
    (48, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "FIXED_FEE"}),
    (46, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "COLLECTION_FEE"}),
    (44, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "PACKAGING_FEE"}),
]
MEESHO = [
    (1, "order_ref", {}), (2, "line_ref", {}), (3, "sku", {}), (4, "quantity", {}),
    (6, "gross_item_amount", {"transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE"}),
    (14, "taxable_amount", {"transform": "RUPEES_TO_PAISE", "tax_inclusion": "EXCLUSIVE"}),
    (0, "invoice_date", {"transform": "DATE_DMY"}), (42, "return_status", {}),
    (12, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "COMMISSION"}),
    (11, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "FIXED_FEE"}),
    (10, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "COLLECTION_FEE"}),
    (13, "component_amount", {"transform": "RUPEES_TO_PAISE", "component_code": "LOGISTICS_FEE"}),
]
MOCKS = [("AMAZON", "amazon_mtr_sep_2025.csv", AMAZON, 38), ("FLIPKART", "flipkart_mtr_sep_2025.csv", FLIPKART, 38), ("MEESHO", "meesho_mtr_sep_2025.csv", MEESHO, 6)]


def upload(client, h, name, data, marketplace, kind="SALES"):
    r = client.post("/api/v1/cfo/uploads", params={"marketplace": marketplace, "report_kind": kind}, files={"file": (name, data, "application/octet-stream")}, headers=h)
    assert r.status_code == 202, r.text
    return r.json()["job"]["jobId"]


def ingest_by_hand(client, h, name, marketplace, spec):
    job = upload(client, h, name, (RAW / name).read_bytes(), marketplace)
    assert wait_for(client, h, job)["status"] == "FAILED"  # no verified adapter: the seller maps it
    m = client.post(f"/api/v1/cfo/jobs/{job}/mapping/manual", json={"fields": [{"index": i, "canonical_field": f, **x} for i, f, x in spec]}, headers=h)
    assert m.status_code == 202, m.text
    new = m.json()["jobId"]
    fields = client.get(f"/api/v1/cfo/jobs/{new}/mapping", headers=h).json()["fields"]
    assert not [f for f in fields if (f["evidence"] or {}).get("errors")], [f for f in fields if (f["evidence"] or {}).get("errors")]
    conf = client.post(f"/api/v1/cfo/jobs/{new}/mapping/confirm", json={"decisions": {str(f["index"]): "SELLER_CONFIRMED" for f in fields}}, headers=h)
    assert conf.status_code == 202, conf.text
    done = wait_for(client, h, new)
    assert done["status"] == "DONE", done
    return done


def column_sum(name, idx) -> Decimal:
    rows = list(csv.reader(open(RAW / name, encoding="utf-8")))[1:]
    return sum((Decimal(r[idx]) for r in rows), Decimal(0))


def rupees(d: Decimal) -> str:
    paise = int((d * 100).to_integral_value())
    r, p = divmod(paise, 100)
    return f"\u20b9{r:,}.{p:02d}"


def test_the_three_mock_mtr_reports_load_through_manual_mapping_and_the_dashboard_shows_the_same_gross_sales_as_the_files(app_client, fake_clerk, two_tenants, with_runner):  # noqa: F811
    a, _ = two_tenants
    with_runner(proposer=None)
    h = _register_owner(fake_clerk, a)
    for marketplace, name, spec, _ in MOCKS:
        done = ingest_by_hand(app_client, h, name, marketplace, spec)
        rows = done["qualityReport"]["rows"]
        assert rows["read"] == 40 and rows["posted"] == 40 and rows["held_total"] == 0 and rows["failed_validation"] == 0, (name, rows)
    q = {"period_start": "2025-08-01", "period_end": "2025-09-30", "as_of_date": "2025-10-01"}
    table = {r["key"]: r for r in app_client.get("/api/v1/cfo/profitability/marketplaces", params=q, headers=h).json()["items"]}
    for marketplace, name, _, price_idx in MOCKS:
        shown = table[marketplace]["grossSales"]
        assert shown["display"] == rupees(column_sum(name, price_idx)), (marketplace, shown, rupees(column_sum(name, price_idx)))
    ov = app_client.get("/api/v1/cfo/overview", params=q, headers=h).json()
    by = {k["label"]: k for k in ov["kpis"]}
    # no cost per unit was entered, so profit is unavailable with the reason - never zero
    assert by["Contribution Profit"]["valueDisplay"] is None and by["Contribution Profit"]["completeness"] == "UNAVAILABLE"
    assert by["Operating Profit"]["valueDisplay"] is None


@pytest.mark.skipif(not ZIP.exists(), reason="the real Meesho GST workbooks are not on this machine")
def test_the_real_meesho_gst_workbooks_are_recognised_by_themselves_and_load(app_client, fake_clerk, two_tenants, with_runner):  # noqa: F811
    a, _ = two_tenants
    with_runner(proposer=None)
    h = _register_owner(fake_clerk, a)
    z = zipfile.ZipFile(ZIP)
    expect = {"tcs_sales.xlsx": ("meesho.tcs_sales.v1", 9), "tcs_sales_return.xlsx": ("meesho.tcs_sales_return.v1", 6)}
    for info in z.infolist():
        done = wait_for(app_client, h, upload(app_client, h, info.filename, z.read(info), "MEESHO"))
        adapter, n = expect[info.filename]
        assert done["status"] == "DONE" and done["qualityReport"]["format"]["adapter_id"] == adapter, done
        assert done["qualityReport"]["rows"]["read"] == n and done["qualityReport"]["rows"]["posted"] == n and done["qualityReport"]["rows"]["failed_validation"] == 0
