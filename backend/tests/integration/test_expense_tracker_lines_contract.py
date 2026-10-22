"""`GET /api/v1/cfo/expense-ledger/lines` — the read contract CFO consumes (docs/specs/expense-tracker-cfo-integration.md).

Native vocabulary, integer paise, current states and SKU assignment, tenant-scoped, read-only, nothing summed.
"""

from __future__ import annotations

from tests.integration.test_expense_assignment_api import (  # noqa: F401  (fixtures and helpers)
    BASE, _clean_sales, app_client, assign, fake_clerk, new, other_owner, owner, seed_catalog,
)

WINDOW = {"period_start": "2026-09-01", "period_end": "2026-09-30"}


def lines(client, headers, **params):
    return client.get(f"{BASE}/lines", params={**WINDOW, **params}, headers=headers)


def test_lines_carry_the_version_native_fields_and_integer_paise(app_client, owner):
    eid = new(app_client, owner)
    r = lines(app_client, owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contractVersion"] == "EXPENSE_TRACKER_LINES.v1" and body["periodStart"] == "2026-09-01" and body["periodEnd"] == "2026-09-30"
    (line,) = body["lines"]
    assert line["id"] == eid and line["amountPaise"] == 10_001 and isinstance(line["amountPaise"], int)
    assert line["costClass"] == "ADVERTISING" and line["treatment"] and line["reviewState"] and line["assignment"] is None
    assert line["paidAmountPaise"] is None or isinstance(line["paidAmountPaise"], int)  # unknown stays null, never zero


def test_lines_include_the_current_sku_assignment(app_client, owner, two_tenants):
    seed_catalog(two_tenants[0], "A", "B")
    eid = new(app_client, owner)
    assert assign(app_client, owner, eid, "EQUAL", [{"sku": "A"}, {"sku": "B"}]).status_code == 201
    (line,) = lines(app_client, owner).json()["lines"]
    assert line["assignment"] == {"basis": "EQUAL", "shares": [{"sku": "A", "bp": None}, {"sku": "B", "bp": None}]}


def test_the_window_and_voided_records_are_respected(app_client, owner):
    new(app_client, owner)
    new(app_client, owner, effective_date="2026-08-10")
    gone = new(app_client, owner)
    assert app_client.post(f"{BASE}/{gone}/void", json={"reason": "duplicate entry"}, headers=owner).status_code == 200
    assert len(lines(app_client, owner).json()["lines"]) == 1
    assert len(lines(app_client, owner, include_voided="true").json()["lines"]) == 2


def test_a_backwards_window_is_422(app_client, owner):
    assert lines(app_client, owner, period_start="2026-09-30", period_end="2026-09-01").status_code == 422


def test_lines_are_tenant_scoped_and_need_authentication(app_client, owner, other_owner):
    new(app_client, owner)
    assert lines(app_client, other_owner).json()["lines"] == []
    assert app_client.get(f"{BASE}/lines", params=WINDOW).status_code == 401
