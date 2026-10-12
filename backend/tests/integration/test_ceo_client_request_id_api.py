"""Public submission idempotency over HTTP: the optional `clientRequestId` on `POST /investigations/{id}/turns`.

One logical submission = one UUID. A retry of it (same id, same text) gets the STORED outcome (`replayed: true`) and writes nothing and runs nothing; a new submission (new id, even with
identical text) is a new turn; the same id with different text is refused (409 CLIENT_REQUEST_ID_REUSED); a request that omits the id behaves exactly as before. The id is scoped to the
investigation inside the tenant, so it can never read or collide with another tenant's turn. The check-then-act runs under the per-investigation Postgres advisory lock, so simultaneous
copies cannot both run.

These tests go through the real HTTP edge (auth, validation, tenant context, RLS) with a spied registry: no model is called and no external service is reached. Evidence labels:
tests marked SIMULATED fake a slow or failing handler in-process; the PROCESS DEATH test kills a real child process mid-leg.

NOT claimed: exactly-once execution of external side effects. A leg that completed and was recorded is never run again for the same id. A leg interrupted by a dead process MAY have taken
effect; a retry with the same id returns the recorded "did not finish" outcome and does not run it again; to try again the seller sends a new submission (a new id)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.api.v1 import ceo as ceo_api
from backend.auth.permissions import OWNER_ROLE
from backend.ceo import orchestrator, recovery
from backend.ceo.registry import ActionRegistry
from backend.repositories import investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_api import clerk, login, start  # noqa: F401
from tests.integration.test_ceo_campaign_routing_e2e import build
from tests.integration.test_ceo_turn import MSG_PROFIT, health_config, runtime, Scripted  # noqa: F401

pytestmark = pytest.mark.usefixtures("two_tenants")

P = "/api/v1/ceo"
MSG = "What GST rate applies to steel water bottles?"
OTHER = "What GST rate applies to steel lunch boxes?"


@pytest.fixture
def api(clerk, two_tenants, health_config):
    from backend.main import app

    a, b = two_tenants
    holder: dict = {}
    app.dependency_overrides[ceo_api.get_runtime] = lambda: holder["rt"]

    def use(handler=None):
        rt, called, _ = build(None)
        if handler is not None:
            rt = replace(rt, registry=ActionRegistry([replace(s, invoke=handler) if s.key == "cfo.gst_lookup" else s for s in rt.registry.specs()]))
        holder["rt"] = rt
        return called

    try:
        yield TestClient(app), login(clerk, a, role=OWNER_ROLE), login(clerk, b, role=OWNER_ROLE), a, b, use
    finally:
        app.dependency_overrides.pop(ceo_api.get_runtime, None)


def post(client, headers, inv, message=MSG, **extra):
    return client.post(f"{P}/investigations/{inv}/turns", json={"message": message, **extra}, headers=headers)


def counts(tenant, inv):
    with tenant_scope(tenant) as conn:
        one = lambda sql: conn.execute(text(sql), {"i": str(inv)}).scalar_one()  # noqa: E731
        return {
            "user_messages": one("SELECT count(*) FROM investigation_message WHERE investigation_id = :i AND role = 'USER'"),
            "ceo_messages": one("SELECT count(*) FROM investigation_message WHERE investigation_id = :i AND role = 'CEO'"),
            "turns": one("SELECT count(*) FROM investigation_turn WHERE investigation_id = :i"),
            "legs": one("SELECT count(*) FROM agent_run WHERE investigation_id = :i AND trigger_ref = 'cfo.gst_lookup'"),
        }


ONCE = {"user_messages": 1, "ceo_messages": 1, "turns": 1, "legs": 1}


# ------------------------------------------------------------------------------------------------ sequential
def test_a_retry_with_the_same_id_returns_the_stored_outcome_and_runs_nothing(api):
    client, ha, _, a, _, use = api
    called = use()
    inv = start(client, ha)
    key = str(uuid.uuid4())
    first, second = post(client, ha, inv, clientRequestId=key), post(client, ha, inv, clientRequestId=key)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    f, s = first.json(), second.json()
    assert f["replayed"] is False and s["replayed"] is True
    assert (s["turnId"], s["answer"], s["status"], s["route"], s["routeKey"], s["messageId"]) == (f["turnId"], f["answer"], f["status"], f["route"], f["routeKey"], f["messageId"])
    assert called == ["cfo.gst_lookup"] and counts(a, inv) == ONCE  # one leg, one question, one answer, one turn


def test_a_new_id_with_identical_text_is_a_new_submission(api):
    client, ha, _, a, _, use = api
    called = use()
    inv = start(client, ha)
    one, two = post(client, ha, inv, clientRequestId=str(uuid.uuid4())), post(client, ha, inv, clientRequestId=str(uuid.uuid4()))
    assert one.json()["replayed"] is False and two.json()["replayed"] is False and one.json()["turnId"] != two.json()["turnId"]
    assert called == ["cfo.gst_lookup"] * 2 and counts(a, inv) == {"user_messages": 2, "ceo_messages": 2, "turns": 2, "legs": 2}


def test_the_same_id_with_different_text_is_refused_and_writes_nothing(api):
    client, ha, _, a, _, use = api
    called = use()
    inv = start(client, ha)
    key = str(uuid.uuid4())
    assert post(client, ha, inv, clientRequestId=key).status_code == 200
    clash = post(client, ha, inv, OTHER, clientRequestId=key)
    assert clash.status_code == 409 and clash.json()["detail"] == {"code": "CLIENT_REQUEST_ID_REUSED"}
    assert called == ["cfo.gst_lookup"] and counts(a, inv) == ONCE
    assert post(client, ha, inv, clientRequestId=key).json()["replayed"] is True  # the original submission is still replayable afterwards


def test_a_request_without_an_id_behaves_exactly_as_before(api):
    client, ha, _, a, _, use = api
    called = use()
    inv = start(client, ha)
    one, two = post(client, ha, inv), post(client, ha, inv)
    assert one.status_code == two.status_code == 200
    assert one.json()["replayed"] is False and two.json()["replayed"] is False and one.json()["turnId"] != two.json()["turnId"]
    assert called == ["cfo.gst_lookup"] * 2 and counts(a, inv)["turns"] == 2


@pytest.mark.parametrize("bad", ["not-a-uuid", "", 12345, ["x"], {"a": 1}, "1" * 300, "5d1b0b52-6f0c-4f0e-9d0a-0a7a2f1d9c1"])
def test_a_malformed_id_is_a_422_and_nothing_is_written_or_run(api, bad):
    client, ha, _, a, _, use = api
    called = use()
    inv = start(client, ha)
    resp = post(client, ha, inv, clientRequestId=bad)
    assert resp.status_code == 422 and called == []
    assert counts(a, inv) == {"user_messages": 0, "ceo_messages": 0, "turns": 0, "legs": 0}


def test_an_explicit_null_id_means_no_id(api):
    client, ha, _, a, _, use = api
    use()
    inv = start(client, ha)
    assert post(client, ha, inv, clientRequestId=None).json()["replayed"] is False


@pytest.mark.parametrize("field", ["client_request_id", "requestKey", "request_key"])
def test_other_spellings_are_not_part_of_the_public_contract(api, field):
    client, ha, _, a, _, use = api
    called = use()
    inv = start(client, ha)
    key = str(uuid.uuid4())
    one, two = post(client, ha, inv, **{field: key}), post(client, ha, inv, **{field: key})
    assert one.json()["turnId"] != two.json()["turnId"] and called == ["cfo.gst_lookup"] * 2  # an unknown field is ignored, never honoured


# ------------------------------------------------------------------------------------------------ scope
def test_an_id_is_scoped_to_its_investigation_and_its_tenant(api):
    client, ha, hb, a, b, use = api
    called = use()
    inv_a, inv_a2, inv_b = start(client, ha), start(client, ha), start(client, hb)
    key = str(uuid.uuid4())
    assert post(client, ha, inv_a, clientRequestId=key).json()["replayed"] is False
    assert post(client, ha, inv_a2, clientRequestId=key).json()["replayed"] is False  # same tenant, another investigation: independent
    assert post(client, hb, inv_b, clientRequestId=key).json()["replayed"] is False  # another tenant: independent
    assert called == ["cfo.gst_lookup"] * 3
    foreign = post(client, hb, inv_a, clientRequestId=key)  # another tenant's investigation is a plain 404 and its turn is never revealed
    assert foreign.status_code == 404 and "turnId" not in foreign.text
    assert counts(a, inv_a) == ONCE


# ------------------------------------------------------------------------------------------------ concurrency, running, failure
def test_simultaneous_duplicates_run_the_action_once(api, monkeypatch):
    client, ha, _, a, _, use = api
    monkeypatch.setenv("CEO_TURN_LOCK_WAIT_SECONDS", "30")  # the second copy waits for the first, then replays
    entered, release = threading.Event(), threading.Event()
    runs: list[int] = []

    def slow(slots, c, leg):
        runs.append(1)
        entered.set()
        release.wait(timeout=20)
        return {"result": None, "noMatch": None}

    use(slow)
    inv = start(client, ha)
    key, out = str(uuid.uuid4()), []
    threads = [threading.Thread(target=lambda: out.append(post(client, ha, inv, clientRequestId=key))) for _ in range(2)]
    threads[0].start()
    assert entered.wait(timeout=20)
    threads[1].start()  # arrives while the first is mid-leg
    release.set()
    [t.join(timeout=60) for t in threads]
    assert sorted(r.status_code for r in out) == [200, 200]
    assert sorted(r.json()["replayed"] for r in out) == [False, True] and len({r.json()["turnId"] for r in out}) == 1
    assert len(runs) == 1 and counts(a, inv) == ONCE


def test_simulated_a_retry_while_the_original_is_still_running_is_refused_without_writing_and_then_replays(api, monkeypatch):
    client, ha, _, a, _, use = api
    monkeypatch.delenv("CEO_TURN_LOCK_WAIT_SECONDS", raising=False)  # no waiting configured: a busy investigation refuses at once
    entered, release = threading.Event(), threading.Event()

    def slow(slots, c, leg):
        entered.set()
        release.wait(timeout=20)
        return {"result": None, "noMatch": None}

    use(slow)
    inv = start(client, ha)
    key, first = str(uuid.uuid4()), []
    t = threading.Thread(target=lambda: first.append(post(client, ha, inv, clientRequestId=key)))
    t.start()
    assert entered.wait(timeout=20)
    busy = post(client, ha, inv, clientRequestId=key)
    assert busy.status_code == 409 and busy.json()["detail"] == {"code": "TURN_IN_PROGRESS"}  # told so: retry later with the SAME id
    release.set()
    t.join(timeout=30)
    assert first[0].status_code == 200 and counts(a, inv) == ONCE
    again = post(client, ha, inv, clientRequestId=key)
    assert again.json()["replayed"] is True and again.json()["turnId"] == first[0].json()["turnId"] and counts(a, inv) == ONCE


def test_simulated_a_failed_original_is_replayed_as_failed_not_run_again(api):
    client, ha, _, a, _, use = api
    attempts: list[int] = []

    def flaky(slots, c, leg):
        attempts.append(1)
        raise RuntimeError("the lookup failed")

    use(flaky)
    inv = start(client, ha)
    key = str(uuid.uuid4())
    first, retry = post(client, ha, inv, clientRequestId=key), post(client, ha, inv, clientRequestId=key)
    assert retry.json()["replayed"] is True and retry.json()["turnId"] == first.json()["turnId"] and retry.json()["status"] == first.json()["status"] and len(attempts) == 1
    fresh = post(client, ha, inv, clientRequestId=str(uuid.uuid4()))  # the seller deliberately tries again
    assert fresh.json()["replayed"] is False and len(attempts) == 2


def test_simulated_failure_before_anything_was_recorded_lets_the_retry_run(api, monkeypatch):
    client, ha, _, a, _, use = api
    called = use()
    inv = start(client, ha)
    key = str(uuid.uuid4())
    real = repo.create_turn
    monkeypatch.setattr(repo, "create_turn", lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("could not record the turn")))
    original = post(client, ha, inv, clientRequestId=key)
    assert original.status_code in (200, 500) and called == []  # nothing ran, no turn row exists
    assert counts(a, inv)["turns"] == 0
    monkeypatch.setattr(repo, "create_turn", real)
    retry = post(client, ha, inv, clientRequestId=key)
    assert retry.status_code == 200 and retry.json()["replayed"] is False and called == ["cfo.gst_lookup"] and counts(a, inv)["turns"] == 1


def test_process_death_a_retry_after_a_real_crash_returns_the_recorded_interruption_and_does_not_run_the_leg_again(api, app_user):
    """PROCESS DEATH: a child process takes a real turn with this id and `os._exit`s inside a leg (its Postgres session, and with it the turn lock, dies with it). The retry through HTTP
    first settles the abandoned turn, then finds the stored (interrupted) outcome for the id: it is NOT run again, because the leg may already have had its effect."""
    client, ha, _, a, _, use = api
    called = use()
    inv = orchestrator.start_investigation(ctx_for(a, user_id=app_user), runtime(Scripted({}), registry=build(None)[0].registry))
    key = str(uuid.uuid4())
    child = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "ceo_recovery_child.py"), str(a), str(app_user), str(inv), key],
                           capture_output=True, text=True, timeout=120, env={**os.environ})
    assert child.returncode == 137, (child.returncode, child.stdout[-300:], child.stderr[-600:])
    retry = post(client, ha, inv, MSG_PROFIT, clientRequestId=key)
    assert retry.status_code == 200, retry.text
    body = retry.json()
    assert body["replayed"] is True and body["status"] == "FAILED" and called == []  # recorded as not finished; nothing was re-run
    assert body["answer"].startswith(recovery.INTERRUPTED_ANSWER)
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM agent_run WHERE investigation_id = :i AND status = 'RUNNING'"), {"i": str(inv)}).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM investigation_turn WHERE investigation_id = :i"), {"i": str(inv)}).scalar_one() == 1
