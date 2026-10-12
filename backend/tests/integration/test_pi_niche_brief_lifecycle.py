"""Issues 3 and 12 (Metrion_24_Fixes): "Mark READY" on a DRAFT niche brief.

The route is correct; what a seller meets is the §6.1 rule-2 precondition (category, budget and at least one marketplace). These tests pin, against the real routes and
the scratch Postgres: a complete DRAFT becomes READY and the status is persisted; an incomplete DRAFT is refused with a 400 that names what is missing and stays DRAFT;
the same brief can then be completed through the existing PUT and becomes READY; another tenant can neither read nor transition it."""

from __future__ import annotations

import uuid

import pytest

from tests.integration.test_pi_discover_api import (  # noqa: F401  (fixtures and helpers)
    _clean_pi_tables,
    _register_owner,
    app_client,
    fake_clerk,
    tenant,
)

BASE = "/api/v1/pi/niche-briefs"


def _create(client, headers, **fields) -> str:
    resp = client.post(BASE, json=fields, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["nicheBriefId"]


def _status(client, headers, brief_id: str) -> str:
    return client.get(f"{BASE}/{brief_id}", headers=headers).json()["status"]


def test_a_complete_draft_becomes_ready_and_the_status_is_persisted(app_client, fake_clerk, tenant):
    headers = _register_owner(fake_clerk, tenant)
    brief = _create(app_client, headers, category_text="kitchen storage jars", budget_paise=5_000_000, marketplaces=["AMAZON"])
    assert _status(app_client, headers, brief) == "DRAFT"
    resp = app_client.post(f"{BASE}/{brief}/mark-ready", headers=headers)
    assert (resp.status_code, resp.json()["status"]) == (200, "READY")
    assert _status(app_client, headers, brief) == "READY"  # a fresh read, not the response
    assert [b["id"] for b in app_client.get(BASE, params={"status": "READY"}, headers=headers).json()] == [brief]
    assert app_client.post(f"{BASE}/{brief}/mark-ready", headers=headers).status_code == 200  # READY -> READY is idempotent


@pytest.mark.parametrize(
    "fields, missing",
    [
        ({"category_text": "jars", "marketplaces": ["AMAZON"]}, ["budget_paise"]),
        ({"category_text": "jars", "budget_paise": 100}, ["marketplaces"]),
        ({"budget_paise": 100, "marketplaces": ["AMAZON"]}, ["category_text"]),
        ({}, ["category_text", "budget_paise", "marketplaces"]),
    ],
)
def test_an_incomplete_draft_is_refused_with_the_missing_fields_named_and_stays_draft(app_client, fake_clerk, tenant, fields, missing):
    headers = _register_owner(fake_clerk, tenant)
    brief = _create(app_client, headers, **fields)
    resp = app_client.post(f"{BASE}/{brief}/mark-ready", headers=headers)
    assert resp.status_code == 400
    assert all(m in resp.json()["detail"] for m in missing)
    assert _status(app_client, headers, brief) == "DRAFT"


def test_an_incomplete_draft_can_be_completed_through_the_existing_put_and_then_made_ready(app_client, fake_clerk, tenant):
    headers = _register_owner(fake_clerk, tenant)
    brief = _create(app_client, headers, category_text="jars")
    assert app_client.post(f"{BASE}/{brief}/mark-ready", headers=headers).status_code == 400
    assert app_client.put(f"{BASE}/{brief}", json={"budget_paise": 5_000_000, "marketplaces": ["FLIPKART"]}, headers=headers).status_code == 200
    got = app_client.get(f"{BASE}/{brief}", headers=headers).json()
    assert (got["category_text"], got["budget_paise"], got["marketplaces"]) == ("jars", 5_000_000, ["FLIPKART"])  # earlier fields are kept
    assert app_client.post(f"{BASE}/{brief}/mark-ready", headers=headers).status_code == 200
    assert _status(app_client, headers, brief) == "READY"


def test_a_missing_or_foreign_brief_is_refused_and_not_changed(app_client, fake_clerk, tenant, two_tenants):
    headers = _register_owner(fake_clerk, tenant)
    assert app_client.post(f"{BASE}/{uuid.uuid4()}/mark-ready", headers=headers).status_code == 400  # unknown id: refused, nothing created
    other = _register_owner(fake_clerk, two_tenants[1])
    brief = _create(app_client, headers, category_text="jars", budget_paise=100, marketplaces=["MEESHO"])
    assert app_client.get(f"{BASE}/{brief}", headers=other).status_code == 404
    assert app_client.post(f"{BASE}/{brief}/mark-ready", headers=other).status_code == 400
    assert _status(app_client, headers, brief) == "DRAFT"  # tenant B's attempt changed nothing


def test_ready_can_go_back_to_draft_and_archived_cannot_become_ready(app_client, fake_clerk, tenant):
    headers = _register_owner(fake_clerk, tenant)
    brief = _create(app_client, headers, category_text="jars", budget_paise=100, marketplaces=["AMAZON"])
    app_client.post(f"{BASE}/{brief}/mark-ready", headers=headers)
    assert app_client.post(f"{BASE}/{brief}/mark-draft", headers=headers).json()["status"] == "DRAFT"
    assert app_client.post(f"{BASE}/{brief}/archive", headers=headers).json()["status"] == "ARCHIVED"
    assert app_client.post(f"{BASE}/{brief}/mark-ready", headers=headers).status_code == 400
    assert _status(app_client, headers, brief) == "ARCHIVED"
