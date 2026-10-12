"""The requests the Profit & Finance forms really send, replayed against the real routes.

`frontend/test-support/fixtures/requestSamples.json` is written by `frontend/components/cfo/requestSamples.test.tsx`, which fills each form the way a seller would,
submits it, and records the body the component built (that test also validates it against the backend's schema, values included). Here each recorded body is posted,
unchanged, to the real route on the scratch Postgres with a real owner membership (only Clerk is faked):

- the request is accepted by validation (never 422) and nothing fails with a server error;
- when the route answers 200, the response has every field the frontend reads for it (`responseContracts.json`);
- as a control, the same body with one required field removed IS refused with 422, so a passing replay means something.

The tenant has no stored books, so the answers are the honest empty ones (unavailable figures, data requests, domain refusals). One route is also replayed with real
stored results so a populated 200 is checked."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from tests.integration.ceo_support import save_metric
from tests.integration.test_cfo_cash_reconciliation import _clean_tables, _register_owner, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)
from tests.integration.test_frontend_response_contracts import CONTRACTS, conforms

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "test-support"
SAMPLES: dict[str, dict] = json.loads((FRONTEND / "fixtures" / "requestSamples.json").read_text(encoding="utf-8"))
REQUEST_CONTRACT = json.loads((FRONTEND / "requestContract.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.usefixtures("two_tenants")


class _FakeProvider:
    """Stands in for the local-Ollama narration provider. A replayed request may reach a narration step (period comparison does by default); no test here may call a
    real model, so every call lands here, is recorded, and returns a plain sentence."""

    calls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def complete(self, *, model: str, prompt: str) -> str:
        _FakeProvider.calls.append(prompt)
        return "The two periods are compared in the figures below."


@pytest.fixture(autouse=True)
def _no_real_model(monkeypatch):
    from backend.api.v1 import cfo as cfo_api

    _FakeProvider.calls = []
    monkeypatch.setattr(cfo_api, "OllamaLlmProvider", _FakeProvider)
    yield


def _send(client, headers, key: str, body: dict):
    method, path = key.split(" ", 1)
    if "__query" in body:  # a GET the form builds with a query string and no body
        return client.request(method, path, params=body["__query"], headers=headers)
    return client.request(method, path, json=body, headers=headers)


def _required(key: str) -> list[str]:
    schema = REQUEST_CONTRACT["routes"][key]["body"]
    while "$ref" in schema:
        schema = REQUEST_CONTRACT["schemas"][schema["$ref"].split("/")[-1]]
    return list(schema.get("required", []))


def test_the_samples_cover_the_forms_that_were_upgraded_from_static_checks() -> None:
    assert len(SAMPLES) == 16
    assert all(k in REQUEST_CONTRACT["routes"] for k in SAMPLES)


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_the_body_the_form_builds_is_accepted_and_the_answer_has_what_the_screen_reads(app_client, fake_clerk, two_tenants, key):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    resp = _send(app_client, headers, key, copy.deepcopy(SAMPLES[key]))
    assert resp.status_code != 422, f"{key} refused what the form sends: {resp.text[:300]}"
    assert resp.status_code < 500, f"{key} failed on what the form sends: {resp.status_code} {resp.text[:300]}"
    if resp.status_code == 200 and key in CONTRACTS:
        problems = conforms(resp.json(), CONTRACTS[key], key, set())
        assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_control_the_same_body_missing_a_required_field_is_refused(app_client, fake_clerk, two_tenants, key):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    if "__query" in SAMPLES[key]:
        _, path = key.split(" ", 1)
        required_query = REQUEST_CONTRACT["routes"][key]["requiredQuery"]
        assert required_query, "a form that builds a query for a route with no required parameter"
        params = {k: v for k, v in SAMPLES[key]["__query"].items() if k != required_query[0]}
        assert app_client.get(path, params=params, headers=headers).status_code == 422
        return
    required = _required(key)
    if not required:
        pytest.skip("every field of this request is optional")
    body = copy.deepcopy(SAMPLES[key])
    body.pop(required[0])
    assert _send(app_client, headers, key, body).status_code == 422


def test_period_comparison_with_real_stored_results_answers_200_in_the_shape_the_screen_reads(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    first = save_metric(a, "CONTRIBUTION_PROFIT", period="2026-08-01/2026-08-31", value_paise=5_000_000)
    second = save_metric(a, "CONTRIBUTION_PROFIT", period="2026-09-01/2026-09-30", value_paise=6_132_000)
    key = "POST /api/v1/cfo/period-comparison"
    body = {**SAMPLES[key], "result_a_id": str(first), "result_b_id": str(second)}
    resp = _send(app_client, headers, key, body)
    assert resp.status_code == 200, resp.text
    assert conforms(resp.json(), CONTRACTS[key], key, set()) == []


def test_period_comparison_refuses_results_that_belong_to_another_tenant(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    headers = _register_owner(fake_clerk, a)
    mine = save_metric(a, "CONTRIBUTION_PROFIT", period="2026-08-01/2026-08-31", value_paise=1)
    theirs = save_metric(b, "CONTRIBUTION_PROFIT", period="2026-09-01/2026-09-30", value_paise=999)
    key = "POST /api/v1/cfo/period-comparison"
    resp = _send(app_client, headers, key, {**SAMPLES[key], "result_a_id": str(mine), "result_b_id": str(theirs)})
    assert "999" not in resp.text  # tenant B's figure is never reflected back to tenant A
    random_ids = _send(app_client, headers, key, {**SAMPLES[key], "result_a_id": str(uuid.uuid4()), "result_b_id": str(uuid.uuid4())})
    assert random_ids.status_code < 500


def test_the_writes_the_forms_send_are_stored_and_read_back_for_this_tenant_only(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    ha, hb = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    for key in ("PUT /api/v1/cfo/expenses", "PUT /api/v1/cfo/expenses/budget", "PUT /api/v1/cfo/seller-goal"):
        resp = _send(app_client, ha, key, copy.deepcopy(SAMPLES[key]))
        assert resp.status_code == 200, f"{key}: {resp.status_code} {resp.text[:200]}"
        assert resp.json()["manualAdjustmentId"]
    listed = app_client.get("/api/v1/cfo/expenses", headers=ha).json()
    assert "50000" in json.dumps(listed)  # the expense the form sent is listed back, in paise, as sent
    assert "50000" not in json.dumps(app_client.get("/api/v1/cfo/expenses", headers=hb).json())  # and tenant B does not see it
    status = app_client.get("/api/v1/cfo/expenses/budget-status", params=SAMPLES["GET /api/v1/cfo/expenses/budget-status"]["__query"], headers=ha)
    assert status.status_code == 200, status.text[:200]
    again = _send(app_client, ha, "PUT /api/v1/cfo/expenses", copy.deepcopy(SAMPLES["PUT /api/v1/cfo/expenses"]))
    assert again.status_code == 200  # saving the same entry again is accepted (a new superseding row), not an error
