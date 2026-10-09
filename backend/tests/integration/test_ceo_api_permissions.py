"""Independent verification of the CEO HTTP surface's authorization (spec D8, §8 rules 2 and 5, R10, T12).

Written as a reviewer's check on the B3/B4 API, not by its author: the matrix below is the SPEC's rule, asserted exactly.
Seeing or continuing an investigation needs `agent.ceo` AND `investigation.view`; starting one needs `agent.ceo` AND `investigation.create`.
Neither key alone is enough. (Before this suite, `investigation.view` alone could read, resolve and archive CEO conversations, and
`agent.ceo` alone could attach/detach agents.)
"""

from __future__ import annotations

import os
import threading

import pytest

from backend.auth.permissions import AGENT_CEO, INVESTIGATION_CREATE, INVESTIGATION_VIEW, PARTNER_ROLE
from backend.repositories import investigation_repo as repo
from tests.integration.test_ceo_api import api, clerk, login, start  # noqa: F401  (fixtures + helpers)

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

ENDPOINTS = ("start", "list", "one", "findings", "turn", "attach", "resolve", "archive", "availability")
GRIDS: dict[str, dict[str, object]] = {
    "view-only": {INVESTIGATION_VIEW: True},
    "ceo-only": {AGENT_CEO: True},
    "ceo+view": {AGENT_CEO: True, INVESTIGATION_VIEW: True},
    "ceo+create": {AGENT_CEO: True, INVESTIGATION_CREATE: True},
    "nothing": {},
}
# The spec's rule: exactly these (grid, endpoint) pairs succeed.
ALLOWED = {
    ("ceo+view", "list"), ("ceo+view", "one"), ("ceo+view", "findings"), ("ceo+view", "turn"), ("ceo+view", "attach"),
    ("ceo+view", "resolve"), ("ceo+view", "archive"), ("ceo+view", "availability"), ("ceo+create", "start"),
}


def _request(client, endpoint: str, inv: str, headers):
    p = "/api/v1/ceo"
    return {
        "start": lambda: client.post(f"{p}/investigations", json={"title": "x"}, headers=headers),
        "list": lambda: client.get(f"{p}/investigations", headers=headers),
        "one": lambda: client.get(f"{p}/investigations/{inv}", headers=headers),
        "findings": lambda: client.get(f"{p}/investigations/{inv}/findings", headers=headers),
        "turn": lambda: client.post(f"{p}/investigations/{inv}/turns", json={"message": "hello"}, headers=headers),
        "attach": lambda: client.put(f"{p}/investigations/{inv}/agents/CFO", json={"attached": False}, headers=headers),
        "resolve": lambda: client.post(f"{p}/investigations/{inv}/resolve", json={"resolution_note": "done"}, headers=headers),
        "archive": lambda: client.post(f"{p}/investigations/{inv}/archive", headers=headers),
        "availability": lambda: client.get(f"{p}/agents/availability", headers=headers),
    }[endpoint]()


# The ONE endpoint that does not answer 403: a turn from a member who holds agent.ceo but not investigation.view is refused INSIDE the turn
# (200 with status DENIED), so the refusal is written to the audit log (spec AC11) and nothing is put into the investigation.
REFUSED_INSIDE_THE_TURN = {("ceo-only", "turn"), ("ceo+create", "turn")}


@pytest.mark.parametrize("grid", list(GRIDS))
def test_neither_key_alone_is_enough_on_any_endpoint(api, clerk, grid):  # noqa: F811
    client, owner, _, a, _ = api
    for endpoint in ENDPOINTS:
        inv = start(client, owner)  # a fresh ACTIVE investigation for every call, created by the OWNER
        headers = login(clerk, a, role=PARTNER_ROLE, permissions=GRIDS[grid])
        r = _request(client, endpoint, inv, headers)
        if (grid, endpoint) in ALLOWED:
            assert r.status_code in (200, 201), (grid, endpoint, r.status_code, r.text)
        elif (grid, endpoint) in REFUSED_INSIDE_THE_TURN:
            assert r.status_code == 200 and r.json()["status"] == "DENIED", (grid, endpoint, r.text)
            assert repo.list_turns(a, inv) == [] and repo.list_findings(a, inv) == [] and repo.list_messages(a, inv) == []
        else:
            assert r.status_code == 403, (grid, endpoint, r.status_code, r.text)
            assert r.json()["detail"].startswith("Missing permission:")  # the same shape the auth chain uses


def test_a_refused_member_changes_nothing(api, clerk):  # noqa: F811
    """A request refused for a missing key must leave no trace in the investigation: no turn, no finding, no message, no attachment change."""
    client, owner, _, a, _ = api
    inv = start(client, owner)
    before = (repo.get_investigation(a, inv), repo.list_messages(a, inv), repo.list_turns(a, inv), repo.list_findings(a, inv), repo.agent_states(a, inv))
    for grid in ("view-only", "ceo-only", "nothing"):
        h = login(clerk, a, role=PARTNER_ROLE, permissions=GRIDS[grid])
        for endpoint in ("attach", "resolve", "archive"):
            assert _request(client, endpoint, inv, h).status_code == 403
        assert _request(client, "turn", inv, h).status_code in (200, 403)  # refused either way (ceo-only: 200 DENIED + audit row)
    after = (repo.get_investigation(a, inv), repo.list_messages(a, inv), repo.list_turns(a, inv), repo.list_findings(a, inv), repo.agent_states(a, inv))
    assert after == before


def test_another_tenants_investigation_is_a_404_on_every_endpoint_and_nothing_changes(api):  # noqa: F811
    client, owner_a, owner_b, a, _ = api
    inv = start(client, owner_a)
    before = repo.get_investigation(a, inv)
    p = f"/api/v1/ceo/investigations/{inv}"
    attempts = [
        ("get", p, None), ("get", p + "/findings", None), ("post", p + "/turns", {"message": "hello"}),
        ("post", p + "/resolve", {"resolution_note": "stolen"}), ("post", p + "/archive", None), ("post", p + "/reopen", None),
        ("put", p + "/agents/CFO", {"attached": False}),
    ]
    for method, path, body in attempts:
        kw = {"json": body} if body is not None else {}
        r = getattr(client, method)(path, headers=owner_b, **kw)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
    assert repo.get_investigation(a, inv) == before
    assert repo.list_messages(a, inv) == [] and repo.agent_states(a, inv).get("CFO") is True
    assert client.get("/api/v1/ceo/investigations", headers=owner_b).json() == []  # and it is not in B's list


def test_two_simultaneous_turns_leave_a_consistent_thread(api, monkeypatch):  # noqa: F811
    """E24: with a wait configured the second turn waits for the first; the thread stays consistent — each turn owns one question and one answer."""
    monkeypatch.setenv("CEO_TURN_LOCK_WAIT_SECONDS", "30")
    client, owner, _, a, _ = api
    inv = start(client, owner)
    out: list = []

    def go() -> None:
        out.append(client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "hello"}, headers=owner))

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [r.status_code for r in out] == [200, 200]
    msgs, turns = repo.list_messages(a, inv), repo.list_turns(a, inv)
    assert len(turns) == 2 and len(msgs) == 4
    by_turn: dict = {}
    for m in msgs:
        by_turn.setdefault(m["turn_id"], []).append(m["role"])
    assert all(sorted(roles) == ["CEO", "USER"] for roles in by_turn.values()), by_turn
