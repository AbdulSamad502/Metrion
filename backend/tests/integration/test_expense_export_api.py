"""`GET /api/v1/cfo/expense-ledger/export` — kickoff S5b, tests EX1–EX7 of engine §5.18.4 against a real Postgres (only Clerk is faked)."""

from __future__ import annotations

import csv
import io

import pytest
from sqlalchemy import text

from backend.api.v1 import expense_export as ex
from tests.integration.test_cfo_pnl import (  # noqa: F401  (fixtures and helpers)
    _clean_metric_result_table,
    _register_owner,
    _register_partner_with_permissions,
    _seed_zero_cap,
    app_client,
    fake_clerk,
)

BASE = "/api/v1/cfo/expense-ledger"
X = f"{BASE}/export"
BODY = {"effective_date": "2026-09-10", "category": "operating_overhead", "amount_paise": 125_000, "vendor": "Acme Realty", "description": "September rent"}


@pytest.fixture
def owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[0])


@pytest.fixture
def other_owner(fake_clerk, two_tenants):
    return _register_owner(fake_clerk, two_tenants[1])


def rows_of(response):
    assert response.status_code == 200, response.text
    return list(csv.reader(io.StringIO(response.text, newline="")))


def dicts(response):
    table = rows_of(response)
    return [dict(zip(table[0], r)) for r in table[1:]]


def add(client, headers, **kw):
    r = client.post(BASE, json={**BODY, **kw}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["expenseId"]


def test_ex1_every_field_is_present_and_the_header_order_is_stable(app_client, owner):
    add(app_client, owner)
    table = rows_of(app_client.get(X, headers=owner))
    assert tuple(table[0]) == ex.STATE_COLUMNS
    for needed in ("treatment", "review_status", "void_status", "source_reference", "payment_status", "amount_paise", "actor", "recorded_at"):
        assert needed in table[0]
    assert len(table) == 2 and len(table[1]) == len(table[0])


def test_ex2_every_review_state_is_present_including_voided_with_its_status(app_client, owner):
    confirmed = add(app_client, owner)
    pending = add(app_client, owner, amount_paise=2_000)
    app_client.post(f"{BASE}/{pending}/review", json={"state": "pending_review"}, headers=owner)
    draft = app_client.post(BASE, json={**BODY, "amount_paise": 3_000, "state": "draft"}, headers=owner).json()["expenseId"]
    voided = add(app_client, owner, amount_paise=4_000)
    assert app_client.post(f"{BASE}/{voided}/void", json={"reason": "entered twice"}, headers=owner).status_code == 200
    got = {r["expense_id"]: r for r in dicts(app_client.get(X, headers=owner))}
    assert {got[confirmed]["review_status"], got[pending]["review_status"], got[draft]["review_status"], got[voided]["review_status"]} == {"confirmed", "pending_review", "draft", "voided"}
    assert got[voided]["void_status"] == "VOIDED" and got[voided]["void_reason"].startswith("entered twice") and got[confirmed]["void_status"] == ""


def test_ex3_amounts_equal_the_ledger_paise_exactly_including_refunds_and_large_values(app_client, owner):
    big = add(app_client, owner, amount_paise=9_999_999_999_999)
    cost = add(app_client, owner, amount_paise=1)
    refund = app_client.post(f"{BASE}/{cost}/refund", json={"effective_date": "2026-09-12", "amount_paise": -1}, headers=owner).json()["expenseId"]
    got = {r["expense_id"]: r for r in dicts(app_client.get(X, headers=owner))}
    assert got[big]["amount_paise"] == "9999999999999" and got[cost]["amount_paise"] == "1" and got[refund]["amount_paise"] == "-1"  # a negative paise amount is not text-escaped
    assert got[refund]["refund_of_expense_id"] == cost
    api = {r["id"]: r["amountPaise"] for r in app_client.get(f"{BASE}?limit=200", headers=owner).json()["records"]}
    assert all(int(got[i]["amount_paise"]) == api[i] for i in got)


def test_ex4_unknown_values_are_blank_not_zero(app_client, owner):
    add(app_client, owner)
    r = dicts(app_client.get(X, headers=owner))[0]
    assert r["paid_amount_paise"] == "" and r["sku"] == "" and r["channel_scope"] == "" and r["corrects_expense_id"] == "" and r["refund_of_expense_id"] == ""
    assert r["payment_status"] == "unknown" and r["source_reference"] == "manual"  # a real status value is exported as itself


def test_ex5_formula_injection_cells_are_escaped(app_client, owner):
    add(app_client, owner, description="=HYPERLINK(\"http://x\")")
    add(app_client, owner, description="+1+1", amount_paise=7)
    add(app_client, owner, description="-2", amount_paise=8)
    add(app_client, owner, description="@SUM(A1)", amount_paise=9)
    got = {r["amount_paise"]: r["description"] for r in dicts(app_client.get(X, headers=owner))}
    assert got["125000"].startswith("'=") and got["7"] == "'+1+1" and got["8"] == "'-2" and got["9"] == "'@SUM(A1)"


@pytest.mark.parametrize("value,expected", [("=1", "'=1"), ("+1", "'+1"), ("-1", "'-1"), ("@x", "'@x"), ("\tx", "'\tx"), ("plain", "plain"), (None, ""), ("a=b", "a=b")])
def test_ex5_the_cell_escape_rule(value, expected):
    assert ex.text_cell(value) == expected


def test_ex6_a_cross_tenant_export_is_impossible(app_client, owner, other_owner):
    add(app_client, owner, description="tenant A only")
    assert dicts(app_client.get(X, headers=other_owner)) == []
    assert "tenant A only" not in app_client.get(X, headers=other_owner).text
    assert app_client.get(X, params={"tenant_id": "x"}, headers=other_owner).text.count("\n") == 1  # the parameter is ignored: scope comes from the session


def test_ex7_an_empty_ledger_returns_the_header_only(app_client, owner):
    r = app_client.get(X, headers=owner)
    assert r.status_code == 200 and r.text == ",".join(ex.STATE_COLUMNS) + "\r\n"
    assert app_client.get(X, params={"history": "true"}, headers=owner).text == ",".join(ex.HISTORY_COLUMNS) + "\r\n"


def test_the_history_option_exports_every_status_event_in_order(app_client, owner):
    eid = add(app_client, owner)
    app_client.post(f"{BASE}/{eid}/payment", json={"status": "paid", "paid_amount_paise": 125_000}, headers=owner)
    app_client.post(f"{BASE}/{eid}/void", json={"reason": "mistake"}, headers=owner)
    got = dicts(app_client.get(X, params={"history": "true"}, headers=owner))
    assert [(r["kind"], r["review_status"] or r["payment_status"]) for r in got] == [("REVIEW", "confirmed"), ("PAYMENT", "unknown"), ("PAYMENT", "paid"), ("REVIEW", "voided")]
    seqs = [int(r["event_seq"]) for r in got]
    assert seqs == sorted(seqs) and got[2]["paid_amount_paise"] == "125000" and got[3]["reason"] == "mistake"


def test_the_export_is_not_stored_or_cached_and_is_a_download(app_client, owner):
    add(app_client, owner)
    r = app_client.get(X, headers=owner)
    assert r.headers["cache-control"] == "no-store" and "attachment" in r.headers["content-disposition"] and r.headers["content-type"].startswith("text/csv")


def test_there_is_no_totals_row_and_no_gst_column(app_client, owner):
    add(app_client, owner)
    add(app_client, owner, amount_paise=5)
    table = rows_of(app_client.get(X, headers=owner))
    assert len(table) == 3 and not [c for c in table[0] if "gst" in c or "itc" in c or "total" in c]


def test_the_permission_follows_the_financial_read_gate(app_client, fake_clerk, two_tenants, owner, migrate_engine):
    add(app_client, owner)
    reader = _register_partner_with_permissions(fake_clerk, two_tenants[0], permissions={"agent.cfo": True})
    assert app_client.get(X, headers=reader).status_code == 200  # reading needs agent.cfo, not financials.adjust
    nobody = _register_partner_with_permissions(fake_clerk, two_tenants[0], permissions={})
    assert app_client.get(X, headers=nobody).status_code == 403
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.expense_ledger.read")
    assert app_client.get(X, headers=owner).status_code == 402


def test_the_export_writes_no_run_row_and_no_ledger_row(app_client, owner, two_tenants):
    from backend.tenant_context import tenant_scope

    add(app_client, owner)
    with tenant_scope(two_tenants[0]) as conn:
        before = conn.execute(text("SELECT (SELECT count(*) FROM agent_run), (SELECT count(*) FROM expense_event), (SELECT count(*) FROM expense_status_event)")).first()
    app_client.get(X, headers=owner)
    app_client.get(X, params={"history": "true"}, headers=owner)
    with tenant_scope(two_tenants[0]) as conn:
        after = conn.execute(text("SELECT (SELECT count(*) FROM agent_run), (SELECT count(*) FROM expense_event), (SELECT count(*) FROM expense_status_event)")).first()
    assert tuple(before) == tuple(after)
