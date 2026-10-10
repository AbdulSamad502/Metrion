"""Spec agent-needs S6a read edge: GET /api/v1/ceo/investigations/{id}/needs (who asked whom for what and how it ended). Same harness as test_ceo_api.py."""

from __future__ import annotations

import os
import uuid

import pytest

from backend.repositories import ceo_need_repo
from tests.integration.test_ceo_api import api, clerk, login, start  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def record(tenant, inv, key, provider, status):
    assert ceo_need_repo.record(tenant, investigation_id=uuid.UUID(inv), turn_message_id=None, need_key="GST_RATE_FOR_PRODUCT", requester_agent="CMO", mode="PARALLEL",
                                provider_key=provider, idempotency_key=key, status=status)


def test_needs_read_returns_only_this_investigations_lookups_in_camel_case(api):
    client, ha, _, a, _ = api
    inv, other = start(client, ha), start(client, ha)
    assert client.get(f"/api/v1/ceo/investigations/{inv}/needs", headers=ha).json() == {"items": []}
    record(a, inv, "k1", "service.gst_lookup", "NOT_ENTITLED")
    record(a, other, "k2", "cfo.gst_lookup", "FULFILLED")
    r = client.get(f"/api/v1/ceo/investigations/{inv}/needs", headers=ha)
    assert r.status_code == 200
    [item] = r.json()["items"]
    assert set(item) == {"id", "needKey", "requesterAgent", "providerKey", "status", "createdAt", "turnMessageId"}
    assert (item["needKey"], item["requesterAgent"], item["providerKey"], item["status"], item["turnMessageId"]) == ("GST_RATE_FOR_PRODUCT", "CMO", "service.gst_lookup", "NOT_ENTITLED", None)


def test_another_tenant_gets_a_plain_404(api):
    client, ha, hb, a, _ = api
    inv = start(client, ha)
    record(a, inv, "k1", "service.gst_lookup", "FULFILLED")
    r = client.get(f"/api/v1/ceo/investigations/{inv}/needs", headers=hb)
    assert r.status_code == 404 and r.json()["detail"] == {"code": "NOT_FOUND"}
    assert client.get(f"/api/v1/ceo/investigations/{uuid.uuid4()}/needs", headers=ha).status_code == 404
