"""E24 (spec 6.14): turns in ONE investigation are serialized; different investigations are independent; the lock never outlives a turn."""

from __future__ import annotations

import os
import threading
import time
import uuid

import pytest

from backend.ceo import orchestrator
from backend.ceo.turn_lock import TurnInProgress, investigation_turn_lock
from backend.repositories import investigation_repo as repo
from tests.integration.test_ceo_api import api, clerk, start  # noqa: F401  (fixtures + helper)

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def test_a_held_lock_refuses_a_second_taker_at_once_when_no_wait_is_configured():
    inv = uuid.uuid4()
    with investigation_turn_lock(inv, None):
        with pytest.raises(TurnInProgress):
            with investigation_turn_lock(inv, None):
                pytest.fail("a second turn must not run while the first holds the lock")


def test_a_waiting_taker_gets_the_lock_when_the_first_finishes():
    inv = uuid.uuid4()
    order: list[str] = []

    def second() -> None:
        with investigation_turn_lock(inv, 10):
            order.append("second")

    with investigation_turn_lock(inv, None):
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.6)
        order.append("first-done")
    t.join(timeout=15)
    assert order == ["first-done", "second"]


def test_a_wait_that_elapses_is_a_refusal_not_a_hang():
    inv = uuid.uuid4()
    with investigation_turn_lock(inv, None):
        started = time.monotonic()
        with pytest.raises(TurnInProgress):
            with investigation_turn_lock(inv, 1):
                pass
        assert 0.8 <= time.monotonic() - started < 5


def test_different_investigations_never_block_each_other():
    with investigation_turn_lock(uuid.uuid4(), None):
        with investigation_turn_lock(uuid.uuid4(), None):
            pass


def test_the_lock_is_released_when_the_turn_raises():
    inv = uuid.uuid4()
    with pytest.raises(RuntimeError):
        with investigation_turn_lock(inv, None):
            raise RuntimeError("boom")
    with investigation_turn_lock(inv, None):  # taken again at once
        pass


def _slow(monkeypatch, seconds: float) -> None:
    real = orchestrator._run_turn_locked

    def slow(*a, **k):
        time.sleep(seconds)
        return real(*a, **k)

    monkeypatch.setattr(orchestrator, "_run_turn_locked", slow)


def test_api_refuses_an_overlapping_turn_with_409_and_writes_nothing_for_it(api, monkeypatch):  # noqa: F811
    monkeypatch.delenv("CEO_TURN_LOCK_WAIT_SECONDS", raising=False)
    _slow(monkeypatch, 1.5)
    client, owner, _, a, _ = api
    inv = start(client, owner)
    out: list = []
    go = lambda m: out.append(client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": m}, headers=owner))  # noqa: E731
    t1 = threading.Thread(target=go, args=("first",))
    t1.start()
    time.sleep(0.5)  # the first turn now holds the lock
    go("second")
    t1.join()
    assert sorted(r.status_code for r in out) == [200, 409]
    refused = next(r for r in out if r.status_code == 409)
    assert refused.json()["detail"]["code"] == "TURN_IN_PROGRESS"
    assert len(repo.list_turns(a, inv)) == 1 and [m["content"] for m in repo.list_messages(a, inv) if m["role"] == "USER"] == ["first"]


def test_api_waits_for_the_running_turn_when_a_wait_is_configured(api, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CEO_TURN_LOCK_WAIT_SECONDS", "30")
    _slow(monkeypatch, 1.0)
    client, owner, _, a, _ = api
    inv = start(client, owner)
    out: list = []
    go = lambda m: out.append(client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": m}, headers=owner))  # noqa: E731
    t1 = threading.Thread(target=go, args=("first",))
    t1.start()
    time.sleep(0.4)
    go("second")
    t1.join()
    assert [r.status_code for r in out] == [200, 200]
    users = [m["content"] for m in sorted(repo.list_messages(a, inv), key=lambda m: m["created_at"]) if m["role"] == "USER"]
    assert users == ["first", "second"]  # strictly one after the other


def test_another_tenants_investigation_id_takes_no_lock_and_is_a_plain_404(api):  # noqa: F811
    client, owner, other, _, _ = api
    inv = start(client, owner)
    r = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "x"}, headers=other)
    assert r.status_code == 404
