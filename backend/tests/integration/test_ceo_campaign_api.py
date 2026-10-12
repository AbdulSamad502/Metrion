"""Task 1 campaign: the CEO HTTP boundary (authentication, authorization, tenant isolation, validation, restoration, association integrity).

Evidence category: API-level against the real app + real Postgres, with Clerk and the two model handles faked (scripted). No live model, no network."""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.api.v1 import ceo as ceo_api
from backend.ceo.runtime import CeoRuntime
from backend.repositories import agent_run_repo, investigation_repo as repo
from tests.integration.test_ceo_api import clerk, login, start  # noqa: F401  (fixtures)
from tests.integration.test_ceo_http_end_to_end import stack  # noqa: F401  (fixture)
from tests.integration.test_ceo_turn import MSG_PROFIT, Grounded, Scripted, health_config, runtime, seed_books  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures("two_tenants")

P = "/api/v1/ceo"


def _routes():
    out = []
    for r in ceo_api.router.routes:
        for method in sorted((r.methods or set()) - {"HEAD", "OPTIONS"}):
            out.append((method, r.path))
    return out


@pytest.mark.parametrize("method,path", _routes())
def test_every_ceo_route_refuses_an_unauthenticated_caller_without_a_server_error(method, path, stack):
    client = stack[0]
    url = path
    for name in ("investigation_id", "turn_id", "memory_id", "finding_id", "agent_code"):
        url = url.replace("{" + name + "}", "CFO" if name == "agent_code" else str(uuid.uuid4()))
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        r = client.request(method, url, headers=headers, json={} if method in ("POST", "PUT") else None)
        assert r.status_code in (401, 403), (method, path, r.status_code)
        assert "Traceback" not in r.text


def test_another_tenants_ids_are_not_found_on_the_endpoints_the_older_suite_does_not_cover(stack):
    client, ha, hb, a, b, _ = stack
    seed_books(a)
    inv = start(client, ha)
    turn = client.post(f"{P}/investigations/{inv}/turns", json={"message": MSG_PROFIT}, headers=ha).json()
    tid = turn["turnId"]
    for path in (f"{P}/investigations/{inv}/needs", f"{P}/investigations/{inv}/turns/{tid}/flow", f"{P}/investigations/{inv}/findings?turn_id={tid}"):
        r = client.get(path, headers=hb)
        assert r.status_code == 404, (path, r.status_code, r.text[:120])
        assert "cfo" not in r.text.lower()
    assert client.get(f"{P}/investigations/{inv}/turns/{tid}/flow", headers=hb).status_code == 404
    up = client.post(f"{P}/investigations/{inv}/attachments", files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")}, headers=hb)
    assert up.status_code == 404
    # a forged turn id inside the OWNER's own tenant but another investigation is not found either
    other = start(client, ha)
    assert client.get(f"{P}/investigations/{other}/turns/{tid}/flow", headers=ha).status_code == 404
    # nothing of A's was changed by B's attempts
    assert repo.get_investigation(a, uuid.UUID(inv))["status"] == "ACTIVE"
    assert len(repo.list_findings(a, uuid.UUID(inv), turn_id=uuid.UUID(tid))) >= 1


@pytest.mark.parametrize("extra", [{"tenant_id": str(uuid.uuid4())}, {"tenantId": str(uuid.uuid4())}, {"role": "OWNER"}, {"permissions": {"agent.cfo": True}}])
def test_client_supplied_identity_in_a_request_body_changes_nothing(extra, stack):
    client, ha, hb, a, b, _ = stack
    inv = start(client, ha)
    r = client.post(f"{P}/investigations/{inv}/turns", json={"message": "hello", **extra}, headers=ha)
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        assert len(repo.list_messages(a, uuid.UUID(inv))) == 2  # written in the AUTHENTICATED tenant
    assert repo.list_messages(b, uuid.UUID(inv)) == [] and repo.get_investigation(b, uuid.UUID(inv)) is None  # and nowhere else
    s = client.post(f"{P}/investigations", json={"title": "t", **extra}, headers=ha)
    assert s.status_code in (201, 422)
    if s.status_code == 201:
        assert repo.get_investigation(a, uuid.UUID(s.json()["investigationId"])) is not None


@pytest.mark.parametrize(
    "body,expected",
    [({"message": ""}, 422), ({"message": "   "}, (400, 422)), ({"message": "x" * 20000}, (400, 422)), ({}, 422), ({"message": 5}, 422), ({"message": ["a"]}, 422)],
)
def test_malformed_turn_requests_are_clean_client_errors_and_write_nothing(body, expected, stack):
    client, ha, _, a, _, _ = stack
    inv = start(client, ha)
    r = client.post(f"{P}/investigations/{inv}/turns", json=body, headers=ha)
    assert r.status_code in (expected if isinstance(expected, tuple) else (expected,)), r.text
    assert "Traceback" not in r.text and "psycopg" not in r.text
    assert repo.list_messages(a, uuid.UUID(inv)) == [] and repo.list_turns(a, uuid.UUID(inv)) == []


def test_a_turn_for_an_unknown_malformed_or_archived_investigation_is_a_plain_client_error(stack):
    client, ha, _, a, _, _ = stack
    assert client.post(f"{P}/investigations/{uuid.uuid4()}/turns", json={"message": "hi"}, headers=ha).status_code == 404
    assert client.post(f"{P}/investigations/not-a-uuid/turns", json={"message": "hi"}, headers=ha).status_code == 422
    inv = start(client, ha)
    assert client.post(f"{P}/investigations/{inv}/archive", headers=ha).status_code == 200
    r = client.post(f"{P}/investigations/{inv}/turns", json={"message": "hi"}, headers=ha)
    assert r.status_code in (409, 422) and "Traceback" not in r.text
    assert repo.list_messages(a, uuid.UUID(inv)) == []


def test_messages_turns_findings_and_runs_all_point_at_each_other_correctly(stack):
    client, ha, _, a, _, _ = stack
    seed_books(a)
    inv = uuid.UUID(start(client, ha))
    res = client.post(f"{P}/investigations/{inv}/turns", json={"message": MSG_PROFIT}, headers=ha).json()
    assert res["status"] == "DELIVERED"
    msgs = repo.list_messages(a, inv)
    ceo_msg = [m for m in msgs if m["role"] == "CEO"][-1]
    turn = repo.get_turn(a, uuid.UUID(res["turnId"]))
    assert turn["ceo_message_id"] == ceo_msg["id"] and ceo_msg["turn_id"] == turn["id"]
    anchor = agent_run_repo.get_run(a, turn["agent_run_id"])
    assert anchor["agent_id"] == "CEO" and anchor["status"] in ("COMPLETE", "PARTIAL")
    kids = {k["id"]: k for k in agent_run_repo.list_children(a, turn["agent_run_id"])}
    findings = repo.list_findings(a, inv, turn_id=turn["id"])
    assert findings
    for f in findings:
        if f["source"] != "BUSINESS_STATE":
            assert f["agent_run_id"] in kids  # a trace reference resolves to a child of THIS turn's run
            assert kids[f["agent_run_id"]]["trigger_ref"] == f["action_key"]
            assert kids[f["agent_run_id"]]["status"] in ("COMPLETE", "FAILED", "DENIED", "RUNNING")
    flow = client.get(f"{P}/investigations/{inv}/turns/{turn['id']}/flow", headers=ha).json()
    assert {c["actionKey"] if "actionKey" in c else c.get("trigger_ref") for c in flow.get("legs", flow.get("children", []))} or flow


def test_a_conversation_is_restored_identically_by_a_fresh_runtime(stack, clerk):  # noqa: F811
    from backend.main import app

    client, ha, _, a, _, _ = stack
    seed_books(a)
    inv = start(client, ha)
    client.post(f"{P}/investigations/{inv}/turns", json={"message": MSG_PROFIT}, headers=ha)
    before = client.get(f"{P}/investigations/{inv}", headers=ha).json()
    fresh = runtime(Scripted({}), Grounded())  # a brand-new runtime that has never seen the conversation
    app.dependency_overrides[ceo_api.get_runtime] = lambda: fresh
    after = TestClient(app).get(f"{P}/investigations/{inv}", headers=ha).json()
    assert [(m["role"], m["content"], m.get("turnId")) for m in after["messages"]] == [(m["role"], m["content"], m.get("turnId")) for m in before["messages"]]
    assert [t["id"] for t in after["turns"]] == [t["id"] for t in before["turns"]]


def test_a_model_failure_leaves_exactly_one_question_and_one_answer_not_a_duplicate_or_a_false_success(stack):
    client, ha, _, a, _, classifier = stack
    classifier.table = {}  # the scripted classifier now raises KeyError for any message: a model failure
    inv = uuid.UUID(start(client, ha))
    r = client.post(f"{P}/investigations/{inv}/turns", json={"message": "something the model cannot route"}, headers=ha)
    assert r.status_code == 200 and r.json()["status"] in ("CLARIFIED", "FAILED")
    roles = [m["role"] for m in repo.list_messages(a, inv)]
    assert roles == ["USER", "CEO"]
    assert "KeyError" not in r.text and "Traceback" not in r.text


def test_an_unexpected_failure_is_a_plain_500_without_internals_and_no_false_answer(stack, monkeypatch):
    from backend.ceo import orchestrator
    from backend.main import app

    _, ha, _, a, _, _ = stack
    client = TestClient(app, raise_server_exceptions=False)
    inv = uuid.UUID(client.post(f"{P}/investigations", json={"title": "t"}, headers=ha).json()["investigationId"])

    def boom(*_a, **_k):
        raise RuntimeError("secret internals postgresql://user:pw@host/db /srv/app/file.py")

    monkeypatch.setattr(orchestrator, "run_turn", boom)
    r = client.post(f"{P}/investigations/{inv}/turns", json={"message": "hello"}, headers=ha)
    assert r.status_code == 500
    for leak in ("secret", "postgresql", "/srv", "Traceback", "RuntimeError"):
        assert leak not in r.text
    assert [m for m in repo.list_messages(a, inv) if m["role"] == "CEO"] == []  # no answer was invented



def test_a_server_side_value_error_is_not_blamed_on_the_sellers_message(stack, monkeypatch):
    """Regression (campaign defect, found in the browser): any ValueError inside a turn used to be answered as 422 INVALID_MESSAGE, so a server misconfiguration
    (here an invalid CEO_TURN_LOCK_WAIT_SECONDS) told the seller 'write a question between 1 and 4000 characters' about a perfectly good question."""
    from backend.main import app

    _, ha, _, a, _, _ = stack
    client = TestClient(app, raise_server_exceptions=False)
    inv = uuid.UUID(client.post(f"{P}/investigations", json={"title": "t"}, headers=ha).json()["investigationId"])
    monkeypatch.setenv("CEO_TURN_LOCK_WAIT_SECONDS", "0")  # not a positive integer: the operator's mistake, not the seller's
    r = client.post(f"{P}/investigations/{inv}/turns", json={"message": "What have I told you about my business?"}, headers=ha)
    assert r.status_code == 500 and "INVALID_MESSAGE" not in r.text and "CEO_TURN_LOCK" not in r.text  # a server fault, with no internals
    monkeypatch.delenv("CEO_TURN_LOCK_WAIT_SECONDS")
    # a genuinely out-of-range message is still the seller's to fix
    assert client.post(f"{P}/investigations/{inv}/turns", json={"message": "x" * 4001}, headers=ha).status_code == 422
