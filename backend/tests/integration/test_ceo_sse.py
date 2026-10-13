"""SSE with polling fallback (spec 6.26 L11, L8): progress events stream to the caller's own tenant only, carry labels (never figures), and the
synchronous POST plus findings polling remain the fallback transport."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from backend.auth.permissions import AGENT_CEO
from backend.ceo import event_bus
from backend.ceo.runtime import TurnEvent
from tests.integration.test_ceo_api import STATE, api, clerk, login, start  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


class Live:
    """A real uvicorn server in this process (TestClient buffers a streamed response, so it cannot observe SSE). It serves the same app, with the
    same dependency overrides and the same Clerk fake, over real HTTP."""

    def __init__(self, base: str) -> None:
        self.base = base

    def get(self, path, headers=None):
        return httpx.get(self.base + path, headers=headers, timeout=20)

    def post(self, path, json=None, headers=None):
        return httpx.post(self.base + path, json=json, headers=headers, timeout=60)


@pytest.fixture
def live(api):  # noqa: F811
    from backend.main import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    assert server.started
    try:
        yield Live(f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _read_stream(live, url, headers, out, ready):
    with httpx.stream("GET", live.base + url, headers=headers, timeout=30) as r:
        out.append(("status", r.status_code))
        ready.set()
        if r.status_code != 200:
            return
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                out.append((event, json.loads(line[6:])))
                if event == event_bus.DONE:
                    return


def _collect(live, inv, headers, post_json, *, post_headers=None):
    out: list = []
    ready = threading.Event()
    t = threading.Thread(target=_read_stream, args=(live, f"/api/v1/ceo/investigations/{inv}/events", headers, out, ready))
    t.start()
    assert ready.wait(10)
    r = live.post(f"/api/v1/ceo/investigations/{inv}/turns", json=post_json, headers=post_headers or headers)
    t.join(timeout=20)
    return r, out


def test_a_turn_streams_its_progress_in_order_and_then_ends(api, live):  # noqa: F811
    client, owner, _, a, _ = api
    inv = start(client, owner)
    # not "hello": a bare greeting is now answered directly from fixed text (conversational.py) without a classification step, so it has no CLASSIFIED event
    r, out = _collect(live, inv, owner, {"message": "how should I think about pricing my products"})
    assert r.status_code == 200 and out[0] == ("status", 200)
    kinds = [k for k, _ in out[1:]]
    assert kinds[0] == "TURN_RECEIVED" and kinds[-1] == event_bus.DONE and "CLASSIFIED" in kinds and "ANSWER_READY" in kinds
    assert kinds.index("TURN_ADMITTED") < kinds.index("CLASSIFIED") < kinds.index("ANSWER_READY") < kinds.index(event_bus.DONE)
    assert dict(out[1:])[event_bus.DONE]["data"]["status"] == r.json()["status"]


def test_the_stream_carries_labels_only_never_a_figure_or_the_answer(api, live):  # noqa: F811
    client, owner, _, a, _ = api
    inv = start(client, owner)
    r, out = _collect(live, inv, owner, {"message": "hello"})
    blob = json.dumps([p for _, p in out[1:]])
    assert "₹" not in blob and r.json()["answer"] not in blob
    for _, p in out[1:]:
        assert set(p) == {"kind", "atMs", "data"}
        assert set(p["data"]) <= {"route", "routeKey", "source", "action", "entry", "findingId", "status", "mode"}


def test_another_tenant_cannot_subscribe_to_my_investigation(api):  # noqa: F811
    client, owner_a, owner_b, a, b = api
    inv = start(client, owner_a)
    r = client.get(f"/api/v1/ceo/investigations/{inv}/events", headers=owner_b)
    assert r.status_code == 404
    assert event_bus.get_bus().subscriber_count(b, uuid.UUID(inv)) == 0 and event_bus.get_bus().subscriber_count(a, uuid.UUID(inv)) == 0


def test_my_turns_events_never_reach_another_tenants_subscriber(api):  # noqa: F811
    client, owner_a, owner_b, a, b = api
    inv_a, inv_b = start(client, owner_a), start(client, owner_b)
    q_b = event_bus.get_bus().subscribe(b, uuid.UUID(inv_b))
    try:
        # even a subscriber that somehow used A's investigation id under B's tenant key receives nothing from A's turn
        q_cross = event_bus.get_bus().subscribe(b, uuid.UUID(inv_a))
        client.post(f"/api/v1/ceo/investigations/{inv_a}/turns", json={"message": "hello"}, headers=owner_a)
        assert q_b.empty() and q_cross.empty()
    finally:
        event_bus.get_bus().unsubscribe(b, uuid.UUID(inv_b), q_b)
        event_bus.get_bus().unsubscribe(b, uuid.UUID(inv_a), q_cross)


def test_both_keys_are_required_to_subscribe(api, clerk, live):  # noqa: F811
    from backend.auth.permissions import INVESTIGATION_VIEW, PARTNER_ROLE

    client, owner, _, a, _ = api
    inv = start(client, owner)
    for grid in ({INVESTIGATION_VIEW: True}, {AGENT_CEO: True}, {}):
        h = login(clerk, a, role=PARTNER_ROLE, permissions=grid)
        assert live.get(f"/api/v1/ceo/investigations/{inv}/events", headers=h).status_code == 403, grid
    allowed = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_VIEW: True})
    r, out = _collect(live, inv, allowed, {"message": "hello"})
    assert out[0] == ("status", 200) and r.status_code == 200


def test_unauthenticated_is_401(api):  # noqa: F811
    client, *_ = api
    assert client.get(f"/api/v1/ceo/investigations/{uuid.uuid4()}/events").status_code == 401


def test_a_refused_overlapping_turn_does_not_end_the_running_turns_stream(api, live, monkeypatch):  # noqa: F811
    from backend.ceo import orchestrator

    monkeypatch.delenv("CEO_TURN_LOCK_WAIT_SECONDS", raising=False)
    real = orchestrator._run_turn_locked

    def slow(*args, **kwargs):
        time.sleep(1.5)
        return real(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "_run_turn_locked", slow)
    client, owner, _, a, _ = api
    inv = start(client, owner)
    out: list = []
    ready = threading.Event()
    t = threading.Thread(target=_read_stream, args=(live, f"/api/v1/ceo/investigations/{inv}/events", owner, out, ready))
    t.start()
    assert ready.wait(10)
    first = threading.Thread(target=lambda: live.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "hello"}, headers=owner))
    first.start()
    time.sleep(0.5)
    second = live.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "again"}, headers=owner)
    assert second.status_code == 409
    time.sleep(0.2)
    assert t.is_alive(), "a refused turn must not end the stream of the turn that is running"
    first.join()
    t.join(timeout=20)
    assert out[-1][0] == event_bus.DONE


def test_the_subscription_is_removed_when_the_stream_ends(api, live):  # noqa: F811
    client, owner, _, a, _ = api
    inv = start(client, owner)
    _collect(live, inv, owner, {"message": "hello"})
    time.sleep(0.3)
    assert event_bus.get_bus().subscriber_count(a, uuid.UUID(inv)) == 0


def test_polling_remains_a_complete_fallback_with_no_stream_open(api):  # noqa: F811
    client, owner, _, a, _ = api
    inv = start(client, owner)
    r = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "hello"}, headers=owner)
    assert r.status_code == 200
    assert client.get(f"/api/v1/ceo/investigations/{inv}/findings", headers=owner).status_code == 200  # the polling seam is unchanged


# ------------------------------------------------------------------------------------------ the bus itself
def test_a_slow_subscriber_loses_the_oldest_events_and_never_blocks_the_publisher():
    bus = event_bus.EventBus()
    t, i = uuid.uuid4(), uuid.uuid4()
    q = bus.subscribe(t, i)
    sink = bus.sink_for(t, i)
    started = time.monotonic()
    for n in range(event_bus._QUEUE_SIZE + 50):
        sink(TurnEvent("LEG_FINISHED", n, {"action": "cfo.financial_health", "status": "COMPLETE"}))
    assert time.monotonic() - started < 2 and q.qsize() == event_bus._QUEUE_SIZE
    assert q.get_nowait()["atMs"] == 50  # the oldest 50 were dropped


def test_unsafe_event_data_is_never_published():
    bus = event_bus.EventBus()
    t, i = uuid.uuid4(), uuid.uuid4()
    q = bus.subscribe(t, i)
    bus.sink_for(t, i)(TurnEvent("LEG_FINISHED", 1, {"status": "COMPLETE", "amount": "₹482,150.00", "nested": {"x": 1}, "findingId": "abc"}))
    assert q.get_nowait()["data"] == {"status": "COMPLETE", "findingId": "abc"}
