"""The CEO lifecycle over HTTP, with a real specialist: request → auth → validation → turn → classification → plan → the real registry and the real CFO handlers →
findings with provenance → composition → persistence → read-back (restoration) → the audit flow.

Deterministic integration test, not a live-model one: only Clerk and the two model handles (classifier, composer) are scripted, exactly as in `test_ceo_api.py`
and `test_ceo_turn.py`. Everything between (the HTTP edge, the membership grid, tenant context, RLS, the orchestrator, the registry/choke point, the CFO
`financial_health` / `anomaly_check` / `strategic_briefing` handlers, the repositories) is real, on a real Postgres. A live local-model run is a separate thing
this file does not claim.

The real turn and detail payloads are what the frontend renders. With `CAPTURE_CEO_FIXTURE=1` this test writes them to
`frontend/test-support/fixtures/ceoRealTurn.json`; without it, it fails when the committed fixture's STRUCTURE differs from the real response (so the frontend's
rendering test never runs against a fiction)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.v1 import ceo as ceo_api
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_CREATE, INVESTIGATION_VIEW, PARTNER_ROLE
from tests.integration.test_ceo_api import clerk, login, start  # noqa: F401  (fixtures)
from tests.integration.test_ceo_turn import MSG_PROFIT, PROFIT, Grounded, Scripted, health_config, runtime, seed_books  # noqa: F401  (fixtures)

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

FIXTURE = Path(__file__).resolve().parents[3] / "frontend" / "test-support" / "fixtures" / "ceoRealTurn.json"


@pytest.fixture
def stack(clerk, two_tenants, health_config):
    from backend.main import app

    a, b = two_tenants
    classifier = Scripted({MSG_PROFIT: PROFIT})
    rt = runtime(classifier, Grounded())
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    try:
        from backend.auth.permissions import OWNER_ROLE

        yield TestClient(app), login(clerk, a, role=OWNER_ROLE), login(clerk, b, role=OWNER_ROLE), a, b, classifier
    finally:
        app.dependency_overrides.pop(ceo_api.get_runtime, None)


def shape(value: Any) -> Any:
    """The structure of a JSON value with the data removed: object keys (sorted) and the shape of list items, so two responses can be compared for contract."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return type(value).__name__ if value is not None else "null"


def test_a_profit_question_runs_the_real_cfo_legs_and_is_restorable_over_http(stack):
    client, ha, hb, a, b, classifier = stack
    ids = seed_books(a)

    # authentication and validation come first
    assert client.post("/api/v1/ceo/investigations", json={}).status_code == 401
    inv = start(client, ha)
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": ""}, headers=ha).status_code == 422
    assert classifier.calls == 0  # an invalid request never reached the model

    resp = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": MSG_PROFIT}, headers=ha)
    assert resp.status_code == 200, resp.text
    turn = resp.json()

    # orchestration: classified as the profit-diagnosis playbook, composed from stored values, every marker rendered by code
    assert (turn["status"], turn["route"], turn["routeKey"]) == ("DELIVERED", "PLAYBOOK", "PROFIT_DIAGNOSIS")
    assert "{{" not in turn["answer"] and "12.5%" in turn["answer"]
    assert classifier.calls == 1

    # specialist selection through the real registry: the three CFO actions the playbook plans, each a finding that cites THIS tenant's engine results
    by_action = {f["action_key"]: f for f in turn["findings"]}
    assert {"cfo.financial_health", "cfo.anomaly_check", "cfo.strategic_briefing"} <= set(by_action)
    health = by_action["cfo.financial_health"]
    assert (health["source"], health["status"]) == ("CFO", "COMPLETE")
    assert {r["id"] for r in health["figure_refs"]} == {str(ids["margin"]), str(ids["fees"]), str(ids["returns"])}

    # evidence and provenance reach the response: figures carry a register and the engine result they came from
    figures = [fig for f in turn["findings"] if f.get("presentation") for fig in f["presentation"]["figures"]]
    assert figures, "the presentation snapshot (what the Hub renders) carries the figures"
    assert all(fig["register"] in {"VERIFIED", "DERIVED", "ESTIMATE", "UNAVAILABLE", "SELLER_STATED", "MANUAL"} for fig in figures)
    assert all(fig["ref"]["id"] for fig in figures if fig["register"] != "UNAVAILABLE")

    # progress: the persisted event trail runs from receipt to the answer, in order, and names the legs it ran (no timers, no invented stages)
    kinds = [e["kind"] for e in turn["events"]]
    assert kinds[:2] == ["TURN_RECEIVED", "TURN_ADMITTED"] and kinds[-1] == "ANSWER_READY"
    assert sum(1 for k in kinds if k.startswith("LEG_")) >= 3

    # restoration: a fresh read returns the same conversation, turn and findings
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    assert [m["role"] for m in detail["messages"]] == ["USER", "CEO"] and detail["messages"][1]["content"] == turn["answer"]
    assert detail["turns"][0]["status"] == "DELIVERED" and detail["turns"][0]["route_key"] == "PROFIT_DIAGNOSIS"
    assert {f["id"] for f in detail["findings"]} == {f["id"] for f in turn["findings"]}
    polled = client.get(f"/api/v1/ceo/investigations/{inv}/findings", params={"turn_id": turn["turnId"]}, headers=ha).json()
    assert {f["id"] for f in polled} == {f["id"] for f in turn["findings"]}
    listed = client.get("/api/v1/ceo/investigations", headers=ha).json()
    assert [i["id"] for i in listed] == [inv]

    # the audit flow for the turn: who asked whom for what
    flow = client.get(f"/api/v1/ceo/investigations/{inv}/turns/{turn['turnId']}/flow", headers=ha)
    assert flow.status_code == 200 and flow.json()

    # workspace isolation: tenant B sees none of it
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=hb).status_code == 404
    assert client.get("/api/v1/ceo/investigations", headers=hb).json() == []
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": MSG_PROFIT}, headers=hb).status_code == 404

    # the real payloads are what the frontend renders: capture them, or fail when the committed copy no longer has the real structure
    real = {"turn": turn, "detail": detail}
    if os.environ.get("CAPTURE_CEO_FIXTURE"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(real, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert shape(committed) == shape(real), "frontend/test-support/fixtures/ceoRealTurn.json is stale: rerun with CAPTURE_CEO_FIXTURE=1"


def test_a_member_without_the_cfo_key_gets_no_cfo_figures_and_nothing_made_up(stack, clerk):
    client, ha, _, a, _, classifier = stack
    seed_books(a)
    ceo_only = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_CREATE: True, INVESTIGATION_VIEW: True})
    inv = start(client, ceo_only)
    resp = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": MSG_PROFIT}, headers=ceo_only)
    assert resp.status_code == 200, resp.text
    turn = resp.json()
    cfo = [f for f in turn["findings"] if f["source"] == "CFO"]
    assert all(f["status"] != "COMPLETE" for f in cfo), "no CFO result may be presented as complete to a member who cannot use the CFO"
    assert all(not f["figure_refs"] for f in cfo)
    assert "12.5%" not in turn["answer"] and "{{" not in turn["answer"]


def test_a_classifier_that_fails_degrades_to_a_question_not_an_answer(stack):
    client, ha, _, a, _, classifier = stack
    inv = start(client, ha)
    # the scripted classifier has no entry for this message, which raises inside the model handle: the failure path, over HTTP
    resp = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "an unscripted message"}, headers=ha)
    assert resp.status_code == 200, resp.text
    turn = resp.json()
    assert turn["status"] != "DELIVERED" or turn["route"] == "CLARIFY"
    assert turn["findings"] == [] and "₹" not in turn["answer"]
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    assert [m["role"] for m in detail["messages"]] == ["USER", "CEO"]  # the exchange is persisted and restorable even though nothing was computed
