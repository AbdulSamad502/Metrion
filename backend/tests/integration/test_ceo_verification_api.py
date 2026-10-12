"""Workstream A3 verification (API level). Superseded for `clientRequestId` by `test_ceo_client_request_id_api.py` (approved 2026-10-11 and implemented). What stays pinned here: the
internal spellings `requestKey` / `request_key` are NOT part of the public contract, so a client can never choose the internal key directly."""

from __future__ import annotations

import uuid

import pytest

from backend.repositories import investigation_repo as repo
from tests.integration.test_ceo_api import clerk, login, start  # noqa: F401
from tests.integration.test_ceo_http_end_to_end import stack  # noqa: F401
from tests.integration.test_ceo_turn import health_config  # noqa: F401

pytestmark = pytest.mark.usefixtures("two_tenants")

P = "/api/v1/ceo"


@pytest.mark.parametrize("field", ["requestKey", "request_key"])
def test_the_internal_submission_key_cannot_be_chosen_through_the_public_api(field, stack):
    client, ha, _, a, _, _ = stack
    inv = start(client, ha)
    key = str(uuid.uuid4())
    first = client.post(f"{P}/investigations/{inv}/turns", json={"message": "What GST rate applies to steel water bottles?", field: key}, headers=ha)
    second = client.post(f"{P}/investigations/{inv}/turns", json={"message": "What GST rate applies to steel water bottles?", field: key}, headers=ha)
    if first.status_code == 200 and second.status_code == 200:
        assert first.json()["turnId"] != second.json()["turnId"]  # two submissions: nothing was replayed
        assert len(repo.list_turns(a, uuid.UUID(inv))) == 2
    else:
        assert first.status_code == 422 and second.status_code == 422 and repo.list_turns(a, uuid.UUID(inv)) == []  # rejected outright, still nothing replayed
