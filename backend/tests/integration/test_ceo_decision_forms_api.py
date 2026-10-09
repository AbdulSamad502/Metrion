"""Spec §6.33 at the HTTP edge: the form-support reads (stored inputs shown to the seller before a run) and the shape of a run request.

Tenant comes only from the authenticated context; the stored cost is CFO data (CEO + investigation + CFO keys); a malformed form is a 422 with plain problems and nothing is stored."""

from __future__ import annotations

import os
import uuid

import pytest

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, INVESTIGATION_VIEW, PARTNER_ROLE
from backend.services import cfo_actions
from tests.integration.test_ceo_api import api, clerk, login, start  # noqa: F401
from tests.integration.test_ceo_state_specialists import seed  # noqa: F401
from tests.integration.test_ceo_turn import health_config  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

FORMS = ("/api/v1/ceo/forms/price-impact", "/api/v1/ceo/forms/new-product")


def test_the_form_reads_require_authentication(api):
    client, *_ = api
    for path in FORMS:
        assert client.get(path).status_code == 401


def test_the_form_reads_need_the_cfo_key_as_well_as_the_ceo_keys(api, clerk):
    client, ha, hb, a, _ = api
    for grid, expected in (
        ({AGENT_CEO: True, INVESTIGATION_VIEW: True}, 403),  # no CFO key: the stored cost is CFO data
        ({AGENT_CEO: True, INVESTIGATION_VIEW: True, AGENT_CFO: True}, 200),
        ({AGENT_CFO: True, INVESTIGATION_VIEW: True}, 403),  # no CEO key
    ):
        h = login(clerk, a, role=PARTNER_ROLE, permissions=grid)
        for path in FORMS:
            assert client.get(path, headers=h).status_code == expected, (grid, path)


def test_price_impact_form_support_shows_the_stored_cost_and_never_another_tenants(api, two_tenants):
    client, ha, hb, a, b = api
    user = uuid.uuid4()
    r0 = client.get("/api/v1/ceo/forms/price-impact", params={"sku": "SKU-1"}, headers=ha).json()
    assert r0["storedCost"]["amountPaise"] is None and "no cogs_per_unit" in r0["storedCost"]["reason"]  # nothing stored: unavailable, never zero
    assert r0["competitors"] == [] and r0["maxCandidatePrices"] is None  # the bound has no default
    cfo_actions.enter_expense(b, target_type="SKU", target_ref="SKU-1", field="cogs_per_unit", value={"amount_paise": 99999, "effective_from": "2026-01-01"}, created_by=user)
    assert client.get("/api/v1/ceo/forms/price-impact", params={"sku": "SKU-1"}, headers=ha).json()["storedCost"]["amountPaise"] is None  # B's cost is invisible to A
    mine = client.get("/api/v1/ceo/forms/price-impact", params={"sku": "SKU-1"}, headers=hb).json()["storedCost"]
    assert mine["amountPaise"] == 99999 and mine["effectiveFrom"] == "2026-01-01"
    assert "storedCost" in client.get("/api/v1/ceo/forms/price-impact", headers=ha).json() and client.get("/api/v1/ceo/forms/price-impact", headers=ha).json()["storedCost"] is None


def test_new_product_form_support_lists_active_quotes_and_the_budget_per_tenant(api, two_tenants):
    client, ha, hb, a, b = api
    user = uuid.uuid4()
    cfo_actions.enter_expense(a, target_type="SKU", target_ref="SKU-1", field="supplier.quote", value={"supplier_name": "Acme", "unit_cost_paise": 10000}, created_by=user)
    cfo_actions.enter_expense(a, target_type="ACCOUNT", target_ref=str(a), field="batch.budget", value={"amount_paise": 500000}, created_by=user)
    cfo_actions.enter_expense(b, target_type="SKU", target_ref="SKU-1", field="supplier.quote", value={"supplier_name": "Rival", "unit_cost_paise": 1}, created_by=user)
    mine = client.get("/api/v1/ceo/forms/new-product", params={"sku": "SKU-1"}, headers=ha).json()
    assert [q["value"]["supplier_name"] for q in mine["quotes"]] == ["Acme"] and mine["budget"][0]["value"]["amount_paise"] == 500000
    assert [q["value"]["supplier_name"] for q in client.get("/api/v1/ceo/forms/new-product", params={"sku": "SKU-1"}, headers=hb).json()["quotes"]] == ["Rival"]
    assert client.get("/api/v1/ceo/forms/new-product", headers=ha).json()["quotes"] == []  # no SKU named: no quotes listed


def test_a_malformed_run_request_is_a_422_and_stores_nothing(api):
    client, ha, *_ = api
    inv = start(client, ha)
    bad = {"message": "Should I stock this?", "action": {"kind": "PLAYBOOK", "key": "NEW_PRODUCT_DECISION", "inputs": {"sku": "S"}}}
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json=bad, headers=ha).status_code == 422
    wrong = {"message": "x", "action": {"kind": "ACTION", "key": "cfo.financial_health", "inputs": {"sku": "S"}}}
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json=wrong, headers=ha).status_code == 422
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["messages"] == []  # the refused request wrote no message
