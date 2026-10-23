"""`/api/v1/cfo/expense-ledger/import` — kickoff S5a against a real Postgres (only Clerk is faked).

The preview writes nothing; a commit writes `pending_review` IMPORT records (not counted until confirmed); partially invalid files, duplicates and probable matches are reported
row by row and never silently dropped; re-uploading a file is safe; confirmation needs `financials.adjust`; no raw CSV is stored; tenants are isolated.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.services import expense_import as imp
from tests.integration.test_cfo_pnl import (  # noqa: F401  (fixtures and helpers)
    _clean_metric_result_table,
    _register_owner,
    _register_partner_with_permissions,
    _seed_zero_cap,
    app_client,
    fake_clerk,
)

BASE = "/api/v1/cfo/expense-ledger"
IMP = f"{BASE}/import"
H = ",".join(imp.TEMPLATE_COLUMNS)
ROW1 = "2026-09-10,Acme Realty,September rent,operating_overhead,1200.50,INV-1,"
ROW2 = "2026-09-11,Acme Cloud,hosting,software,300,INV-2,amazon"


def csv_bytes(*lines: str) -> bytes:
    return ("\r\n".join([H, *lines]) + "\r\n").encode()


def up(client, path, headers, data: bytes, **params):
    return client.post(f"{IMP}/{path}", files={"file": ("expenses.csv", data, "text/csv")}, params=params, headers=headers)


def ledger_rows(client, headers):
    return sorted(client.get(f"{BASE}?limit=200&include_voided=true", headers=headers).json()["records"], key=lambda r: (r["effectiveDate"], r["amountPaise"]))


def runs(tenant):
    from backend.tenant_context import tenant_scope

    with tenant_scope(tenant) as conn:
        return conn.execute(text("SELECT count(*) FROM agent_run WHERE trigger_ref = 'cfo.expense_ledger'")).scalar_one()


@pytest.fixture
def owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[0])


@pytest.fixture
def other_owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[1])


def test_the_template_is_the_fixed_header(app_client, owner):
    r = app_client.get(f"{IMP}/template", headers=owner)
    assert r.status_code == 200 and r.text.strip() == H and "attachment" in r.headers["content-disposition"]


def test_preview_writes_nothing_and_reports_every_row(app_client, owner, two_tenants):
    r = up(app_client, "preview", owner, csv_bytes(ROW1, ROW2, "bad-date,Acme,,software,1,,"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"] == {"OK": 2, "ERROR": 1, "DUPLICATE": 0, "PROBABLE_MATCH": 0} and [x["status"] for x in body["rows"]] == ["OK", "OK", "ERROR"]
    assert body["rows"][0]["amountPaise"] == 120_050 and "Date" in body["rows"][2]["errors"][0]
    assert ledger_rows(app_client, owner) == [] and runs(two_tenants[0]) == 0  # nothing written, no run row


def test_preview_flags_probable_matches_and_duplicates_against_the_ledger(app_client, owner):
    app_client.post(BASE, json={"effective_date": "2026-09-10", "category": "operating_overhead", "amount_paise": 120_050, "vendor": "ACME realty", "description": "september  rent"},
                    headers=owner)
    got = up(app_client, "preview", owner, csv_bytes(ROW1)).json()
    assert got["rows"][0]["status"] == "PROBABLE_MATCH" and len(got["rows"][0]["matchedExpenseIds"]) == 1
    assert up(app_client, "commit", owner, csv_bytes(ROW1)).status_code == 200
    again = up(app_client, "preview", owner, csv_bytes(ROW1.replace("September rent", "different words"))).json()
    assert again["rows"][0]["status"] == "DUPLICATE"  # the same source id is already in the ledger


def test_commit_writes_pending_review_import_records_that_are_not_counted(app_client, owner, two_tenants):
    r = up(app_client, "commit", owner, csv_bytes(ROW1, ROW2))
    assert r.status_code == 200, r.text
    assert len(r.json()["created"]) == 2 and r.json()["alreadyImported"] == 0 and r.json()["state"] == "pending_review"
    got = ledger_rows(app_client, owner)
    assert {x["reviewState"] for x in got} == {"pending_review"} and {x["origin"] for x in got} == {"IMPORT"}
    assert got[0]["sourceReference"] == "import:INV-1" and got[0]["costClass"] == "OVERHEAD" and got[1]["channelScope"] == "AMAZON"
    assert runs(two_tenants[0]) == 1
    s = app_client.post(f"{BASE}/summary", json={"period_start": "2026-09-01", "period_end": "2026-09-30"}, headers=owner).json()
    assert s["expenseTotal"]["paise"] == 0 and s["reviewQueue"]["amountPaise"] == 150_050  # not counted until the seller confirms


def test_reuploading_the_same_file_creates_nothing_and_writes_no_second_run(app_client, owner, two_tenants):
    data = csv_bytes(ROW1, ROW2)
    first = up(app_client, "commit", owner, data).json()
    second = up(app_client, "commit", owner, data).json()
    assert len(first["created"]) == 2 and second["created"] == [] and second["alreadyImported"] + sum(1 for x in second["rows"] if x["status"] == "DUPLICATE") == 2
    assert len(ledger_rows(app_client, owner)) == 2 and runs(two_tenants[0]) == 1


def test_an_edited_file_adds_only_the_new_rows(app_client, owner):
    up(app_client, "commit", owner, csv_bytes(ROW1))
    r = up(app_client, "commit", owner, csv_bytes(ROW1, ROW2)).json()
    assert len(r["created"]) == 1 and [x["status"] for x in r["rows"]] == ["DUPLICATE", "OK"]
    assert len(ledger_rows(app_client, owner)) == 2


def test_a_partially_invalid_file_is_refused_whole_by_default_and_lists_the_bad_rows(app_client, owner):
    r = up(app_client, "commit", owner, csv_bytes(ROW1, "2026-09-10,Acme,,nope,1,,", "2026-13-01,Acme,,software,1,,"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ROWS_INVALID" and [x["row"] for x in r.json()["detail"]["rows"]] == [2, 3]
    assert ledger_rows(app_client, owner) == []


def test_skip_invalid_imports_the_good_rows_and_still_reports_the_bad_ones(app_client, owner):
    r = up(app_client, "commit", owner, csv_bytes(ROW1, "2026-09-10,Acme,,nope,1,,"), skip_invalid="true")
    assert r.status_code == 200 and len(r.json()["created"]) == 1 and r.json()["counts"]["ERROR"] == 1 and len(ledger_rows(app_client, owner)) == 1


def test_a_probable_match_is_imported_for_review_and_flagged_not_dropped(app_client, owner):
    app_client.post(BASE, json={"effective_date": "2026-09-10", "category": "software", "amount_paise": 30_000, "vendor": "Acme Cloud", "description": "hosting"}, headers=owner)
    r = up(app_client, "commit", owner, csv_bytes("2026-09-10,Acme Cloud,hosting,software,300,,")).json()
    assert r["rows"][0]["status"] == "PROBABLE_MATCH" and len(r["created"]) == 1
    flagged = [x for x in ledger_rows(app_client, owner) if x["origin"] == "IMPORT"]
    assert ":probable:" in flagged[0]["sourceReference"] and flagged[0]["reviewState"] == "pending_review"


@pytest.mark.parametrize(
    "data",
    [pytest.param(b"", id="empty"), pytest.param(b"date,vendor\r\n1,2\r\n", id="bad-header"), pytest.param(b"\xff\xfe\x00junk", id="not-utf8"),
     pytest.param(b"a" * (imp.MAX_BYTES + 5), id="too-big")],
)
def test_a_malformed_file_is_refused_with_reasons_and_writes_nothing(app_client, owner, data):
    assert up(app_client, "commit", owner, data).status_code == 422
    assert up(app_client, "preview", owner, data).json()["fileErrors"]
    assert ledger_rows(app_client, owner) == []


def test_no_raw_csv_is_stored_only_parsed_fields(app_client, owner, two_tenants, migrate_engine):
    marker = "ZZ-RAW-MARKER"
    up(app_client, "commit", owner, csv_bytes(f"2026-09-10,Acme,{marker},software,5,,"))
    from backend.tenant_context import tenant_scope

    with tenant_scope(two_tenants[0]) as conn:
        row = conn.execute(text("SELECT description, source_reference FROM expense_event")).first()
    assert row.description == marker and "," not in row.source_reference and len(row.source_reference) < 40  # the field, never the file or its rows


def test_a_partner_without_financials_adjust_cannot_commit_but_can_preview(app_client, fake_clerk, two_tenants, owner):
    partner = _register_partner_with_permissions(fake_clerk, two_tenants[0], permissions={"agent.cfo": True})
    assert up(app_client, "preview", partner, csv_bytes(ROW1)).status_code == 200
    assert up(app_client, "commit", partner, csv_bytes(ROW1)).status_code == 403
    assert ledger_rows(app_client, owner) == []


def test_confirming_an_imported_row_needs_financials_adjust(app_client, fake_clerk, two_tenants, owner):
    up(app_client, "commit", owner, csv_bytes(ROW1))
    eid = ledger_rows(app_client, owner)[0]["id"]
    partner = _register_partner_with_permissions(fake_clerk, two_tenants[0], permissions={"agent.cfo": True})
    assert app_client.post(f"{BASE}/{eid}/review", json={"state": "confirmed"}, headers=partner).status_code == 403
    assert app_client.post(f"{BASE}/{eid}/review", json={"state": "confirmed"}, headers=owner).status_code == 200


def test_tenants_are_isolated_and_a_duplicate_in_another_tenant_is_not_a_match(app_client, owner, other_owner):
    up(app_client, "commit", owner, csv_bytes(ROW1))
    r = up(app_client, "preview", other_owner, csv_bytes(ROW1)).json()
    assert r["rows"][0]["status"] == "OK" and ledger_rows(app_client, other_owner) == []


def test_the_entitlement_gate_applies_to_the_commit(app_client, owner, migrate_engine):
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.expense_ledger.write")
    assert up(app_client, "commit", owner, csv_bytes(ROW1)).status_code == 402
