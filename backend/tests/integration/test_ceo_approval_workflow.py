"""CEO approval workflow, end to end over the real app and a real Postgres (ceo-approval-workflow.md S1-S4; ceo-cmo-delegation.md CD9-CD15).

Real: authentication chain (Clerk faked), membership grid, tenant context, RLS, the orchestrator, the plan builder + hash, the repositories, the approve / decline
endpoints, the choke point, the CEO unit billing. Faked: the two model handles and the specialists' handlers (recorders, so "a handler ran" means "a provider could have
been reached") - the registry keeps the REAL specs and their effects metadata.

Every refusal test asserts the same four things: the plan is unchanged, no execution turn exists, no handler ran, nothing was metered."""

from __future__ import annotations

import dataclasses
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import config
from backend.api.v1 import ceo as ceo_api
from backend.auth.permissions import AGENT_CEO, AGENT_CMO, INVESTIGATION_CREATE, INVESTIGATION_VIEW, OWNER_ROLE, PARTNER_ROLE
from backend.ceo import approval, approval_run, orchestrator
from backend.ceo.contract import ApprovalGrant, Denial, LegStatus
from backend.ceo.dispatch import dispatch
from backend.ceo.registry import ActionRegistry, get_registry
from backend.ceo.runtime import CeoRuntime
from backend.ceo.turn_lock import investigation_turn_lock
from backend.repositories import accounting_cutover_repo, agent_run_repo, investigation_plan_repo as plan_repo, investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ALL_AGENTS, ctx_for, seed_platform_cap
from tests.integration.test_ceo_api import clerk, login  # noqa: F401  (fixture + helper)
from tests.integration.test_ceo_dispatch_integration import _open
from tests.integration.test_ceo_turn import Grounded, Scripted, decision

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
ASK = "give me hashtags for my steel water bottle"
HASHTAGS = {"request_key": "ceo-x", "product_name": "Steel water bottle", "marketplace": "AMAZON"}
TRENDS = {"request_key": "ceo-y", "plan_digest": "a" * 64, "marketplaces": ["AMAZON"]}
GATED = ("cmo.generate_hashtags", "cmo.generate_title_sets", "cmo.market_trends")


class Clock:
    """A settable server clock, so expiry is tested exactly (never by sleeping)."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        self.now += timedelta(milliseconds=1)
        return self.now

    def set(self, value: datetime) -> None:
        self.now = value


def recording_registry(calls: dict, *, fail: bool = False, delay: float = 0.0) -> ActionRegistry:
    """The REAL specs (so their effects metadata is attached), every handler a recorder; `fail` makes a handler raise, `delay` makes it slow."""
    real = get_registry()
    specs = []
    for k in GATED:
        def invoke(s, c, leg, k=k):
            calls.setdefault(k, []).append(s.model_dump(mode="json") if hasattr(s, "model_dump") else s)
            if delay:
                time.sleep(delay)
            if fail:
                raise RuntimeError("the provider is down")
            return {}

        specs.append(dataclasses.replace(real.get(k), invoke=invoke, entitlement=None))
    return ActionRegistry(specs)


@dataclass
class Env:
    client: TestClient
    a: uuid.UUID
    b: uuid.UUID
    owner: dict
    other: dict  # a second member of tenant A (a PARTNER who holds the CEO and CMO keys; a tenant has exactly one active OWNER)
    foreign: dict  # an OWNER of tenant B
    calls: dict
    cls: Scripted
    comp: Grounded
    clock: Clock
    rt: CeoRuntime
    migrate_engine: object
    monkeypatch: object


@pytest.fixture
def env(clerk, two_tenants, migrate_engine, monkeypatch):  # noqa: F811
    from backend.main import app

    a, b = two_tenants
    monkeypatch.setenv("CEO_APPROVAL_ENABLED", "true")
    monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: NOW - timedelta(days=1))  # the CEO unit rule (a failed run costs nothing) is in effect, as it is after migration 0017's cut-over
    monkeypatch.delenv("CEO_TURN_LOCK_WAIT_SECONDS", raising=False)
    for k in ("TAVILY_API_KEY", "YOUTUBE_API_KEY"):
        monkeypatch.setenv(k, "test-key")
    for fn in (config.tavily_api_key, config.youtube_api_key):
        fn.cache_clear()
    calls: dict = {}
    cls = Scripted({"yes": decision(), "go ahead": decision(), "run it": decision(), "approve": decision(), "hello again": decision()})
    comp = Grounded()
    clock = Clock()
    rt = CeoRuntime(classifier=cls.model(), composer=comp.model(), leg_timeout_seconds=30, max_legs=5, clock=clock, registry=recording_registry(calls))
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    try:
        yield Env(TestClient(app), a, b, login(clerk, a, role=OWNER_ROLE), login(clerk, a, role=PARTNER_ROLE, permissions={k: True for k in (AGENT_CEO, AGENT_CMO, INVESTIGATION_CREATE, INVESTIGATION_VIEW)}), login(clerk, b, role=OWNER_ROLE), calls, cls, comp, clock, rt, migrate_engine, monkeypatch)
    finally:
        app.dependency_overrides.pop(ceo_api.get_runtime, None)
        for fn in (config.tavily_api_key, config.youtube_api_key):
            fn.cache_clear()


# ------------------------------------------------------------------------------------------------ helpers
def start(e: Env, headers: dict) -> str:
    r = e.client.post("/api/v1/ceo/investigations", json={"title": "Marketing"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["investigationId"]


def turn(e: Env, headers: dict, inv: str, message: str, **extra):
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": message, **extra}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def skip_details(e: Env, headers: dict, inv: str, r: dict) -> dict:
    """Skips the optional extra-detail questions (brand, features...) that follow the required ones."""
    while r["status"] == "CLARIFIED" and str(r.get("clarifyFor", "")).startswith("fact_"):
        r = turn(e, headers, inv, "skip")
    return r


def plan_via_chat(e: Env, headers: dict | None = None, inv: str | None = None) -> tuple[str, dict]:
    """The real path: the seller asks in chat, answers the CEO's one question, and gets a PLANNED turn with a stored plan."""
    headers = headers or e.owner
    inv = inv or start(e, headers)
    first = turn(e, headers, inv, ASK)
    assert first["status"] == "CLARIFIED", first
    planned = skip_details(e, headers, inv, turn(e, headers, inv, "Amazon"))
    assert planned["status"] == "PLANNED", planned
    return inv, planned


def approve(e: Env, headers: dict, inv: str, plan: dict, plan_hash: str | None = None):
    return e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={"plan_hash": plan_hash or plan["planHash"]}, headers=headers)


def decline(e: Env, headers: dict, inv: str, plan: dict, reason: str | None = None):
    return e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/decline", json={"reason": reason}, headers=headers)


def get_plan(e: Env, headers: dict, inv: str, plan_id: str):
    return e.client.get(f"/api/v1/ceo/investigations/{inv}/plans/{plan_id}", headers=headers)


def rows(tenant: uuid.UUID, sql: str, **p):
    with tenant_scope(tenant) as conn:
        return [tuple(r) for r in conn.execute(text(sql), p)]


def counts(tenant: uuid.UUID) -> dict:
    return {
        "plans": rows(tenant, "SELECT count(*) FROM investigation_plan")[0][0], "events": rows(tenant, "SELECT count(*) FROM investigation_plan_event")[0][0],
        "units": rows(tenant, "SELECT count(*) FROM metered_event")[0][0], "approval_turns": rows(tenant, "SELECT count(*) FROM investigation_turn WHERE route_source = 'APPROVAL'")[0][0],
    }


def events_of(tenant: uuid.UUID, plan_id: str) -> list[tuple]:
    return rows(tenant, "SELECT event, from_status, to_status, actor_kind, reason_code FROM investigation_plan_event WHERE plan_id = :p ORDER BY occurred_at, id", p=plan_id)


def assert_untouched(e: Env, inv: str, plan: dict, before: dict, *, status: str = "AWAITING_APPROVAL") -> None:
    """A refused approval leaves the plan, the turns, the meters and the specialists exactly as they were."""
    after = counts(e.a)
    assert after["approval_turns"] == before["approval_turns"] == 0, "an execution turn was created by a refusal"
    assert after["units"] == before["units"], "something was metered by a refusal"
    assert after["plans"] == before["plans"]
    assert e.calls == {}, "a handler ran"
    row = repo_plan(e, inv, plan["id"])
    assert row["status"] == status and row["execution_turn_id"] is None and row["plan_hash"] == plan["planHash"]


def repo_plan(e: Env, inv: str, plan_id: str) -> dict:
    row = plan_repo.get(e.a, uuid.UUID(inv), uuid.UUID(plan_id))
    assert row is not None
    return row


# ------------------------------------------------------------------------------------------------ plan creation (S3, AC-A1, AC-A3)
def test_a_gated_chat_request_ends_planned_with_nothing_run_sent_or_metered(env):
    e = env
    inv, planned = plan_via_chat(e)
    assert e.calls == {}, "a handler ran while only a plan was being made"
    plan = planned["plan"]
    assert planned["planId"] == plan["id"] and plan["status"] == "AWAITING_APPROVAL" and plan["viewerIsRequester"] is True
    assert len(plan["planHash"]) == 64 and plan["plan"]["legs"][0]["action_key"] == "cmo.generate_hashtags"
    assert plan["plan"]["legs"][0]["slots"]["marketplace"] == "AMAZON" and "steel water bottle" in plan["plan"]["legs"][0]["slots"]["product_name"].lower()
    created, expires = datetime.fromisoformat(plan["createdAt"]), datetime.fromisoformat(plan["expiresAt"])
    assert expires - created == timedelta(seconds=1800)  # AC-A5: exactly created_at + 1800 s
    # atomically: one plan, one CREATED event, one PLAN message; the turn is PLANNED; the anchor closed COMPLETE (a plan was produced; no leg ran)
    assert counts(e.a) == {"plans": 1, "events": 1, "units": 0, "approval_turns": 0}
    assert events_of(e.a, plan["id"]) == [("CREATED", None, "AWAITING_APPROVAL", "USER", None)]
    msgs = [m for m in repo.list_messages(e.a, uuid.UUID(inv)) if m["kind"] == "PLAN"]
    assert len(msgs) == 1 and msgs[0]["role"] == "CEO" and str(msgs[0]["turn_id"]) == planned["turnId"] and "typing yes does not approve" in msgs[0]["content"]
    t = repo.get_turn(e.a, uuid.UUID(planned["turnId"]))
    assert t["status"] == "PLANNED" and (t["safety_result"] or {}).get("billing", {}).get("ceoUnit") == "NOT_DUE"
    assert agent_run_repo.get_run(e.a, t["agent_run_id"])["status"] == "COMPLETE"
    assert agent_run_repo.list_children(e.a, t["agent_run_id"]) == []  # zero legs dispatched
    assert rows(e.a, "SELECT count(*) FROM investigation_finding")[0][0] == 0


def test_the_cmo_actions_go_to_a_plan_card_whatever_the_chat_switch_says(env):
    """Checkpoint 2 (ceo-cmo-delegation.md): the five CMO actions are not refused when CEO_APPROVAL_ENABLED is off; they still end PLANNED with nothing run. Product
    Intelligence keeps the old refusal while the switch is off (tests/integration/test_ceo_approval_blocked_chat.py proves that with the real guard)."""
    e = env
    e.monkeypatch.delenv("CEO_APPROVAL_ENABLED")
    inv, planned = plan_via_chat(e)
    assert planned["status"] == "PLANNED" and planned["plan"]["status"] == "AWAITING_APPROVAL" and e.calls == {}
    assert counts(e.a) == {"plans": 1, "events": 1, "units": 0, "approval_turns": 0}


def test_an_unflagged_request_never_creates_a_plan(env):
    e = env
    inv = start(e, e.owner)
    r = turn(e, e.owner, inv, "hello again")
    assert r["status"] in ("CLARIFIED", "DELIVERED", "FAILED") and "plan" not in r
    assert counts(e.a)["plans"] == 0


def test_a_newer_plan_supersedes_the_open_one(env):
    e = env
    inv, first = plan_via_chat(e)
    _, second = plan_via_chat(e, inv=inv)
    old, new = first["plan"], second["plan"]
    assert old["id"] != new["id"] and old["planHash"] != new["planHash"]  # a new id, a new hash: nothing is edited in place
    assert get_plan(e, e.owner, inv, old["id"]).json()["status"] == "SUPERSEDED" and get_plan(e, e.owner, inv, new["id"]).json()["status"] == "AWAITING_APPROVAL"
    assert ("SUPERSEDED", "AWAITING_APPROVAL", "SUPERSEDED", "SYSTEM", "NEWER_PLAN") in events_of(e.a, old["id"])
    sup = rows(e.a, "SELECT metadata->>'newPlanId' FROM investigation_plan_event WHERE plan_id = :p AND event = 'SUPERSEDED'", p=old["id"])
    assert sup == [(new["id"],)]
    assert rows(e.a, "SELECT count(*) FROM investigation_plan WHERE status = 'AWAITING_APPROVAL'")[0][0] == 1
    before = counts(e.a)
    r = approve(e, e.owner, inv, old)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_NOT_AWAITING" and e.calls == {} and counts(e.a)["approval_turns"] == 0 and counts(e.a)["units"] == before["units"]


def test_a_plan_that_cannot_be_built_creates_nothing(env):
    e = env
    rt = dataclasses.replace(e.rt, leg_timeout_seconds=None)
    from backend.main import app

    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    inv = start(e, e.owner)
    turn(e, e.owner, inv, ASK)
    r = skip_details(e, e.owner, inv, turn(e, e.owner, inv, "Amazon"))
    assert r["status"] in ("FAILED", "DENIED") and "plan" not in r
    assert counts(e.a)["plans"] == 0 and e.calls == {}


# ------------------------------------------------------------------------------------------------ typed text is never approval (C3, CD11, AC-A4, AC-D22)
@pytest.mark.parametrize("typed", ["yes", "go ahead", "run it", "approve"])
def test_typed_approval_in_chat_never_approves(env, typed):
    e = env
    inv, planned = plan_via_chat(e)
    before = counts(e.a)
    r = turn(e, e.owner, inv, typed)
    assert r["status"] != "PLANNED" and e.calls == {}
    plan_id = planned["plan"]["id"]
    assert get_plan(e, e.owner, inv, plan_id).json()["status"] == "AWAITING_APPROVAL"
    assert counts(e.a)["approval_turns"] == 0 and counts(e.a)["units"] == before["units"] and events_of(e.a, plan_id) == [("CREATED", None, "AWAITING_APPROVAL", "USER", None)]


def test_a_reply_that_names_the_plan_message_or_the_plan_id_is_not_an_approval(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    plan_msg = next(m for m in repo.list_messages(e.a, uuid.UUID(inv)) if m["kind"] == "PLAN")
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "yes", "clarification": {"id": str(plan_msg["id"]), "option": "approve"}}, headers=e.owner)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_CLARIFICATION"  # a PLAN message is not a decision card
    typed = turn(e, e.owner, inv, f"approve plan {plan['id']} hash {plan['planHash']}")  # the plan id and hash typed into chat: still just text
    assert typed["status"] != "PLANNED" and "plan" not in typed
    assert get_plan(e, e.owner, inv, plan["id"]).json()["status"] == "AWAITING_APPROVAL" and e.calls == {} and counts(e.a)["approval_turns"] == 0


def test_the_plan_text_is_not_fed_back_to_the_classifier(env):
    e = env
    inv, planned = plan_via_chat(e)
    e.cls.prompts.clear()
    turn(e, e.owner, inv, "yes")
    assert e.cls.prompts and not any("Nothing has run yet" in p or planned["plan"]["planHash"] in p for p in e.cls.prompts)


# ------------------------------------------------------------------------------------------------ approve (S4, AC-A6, A7, A8, A9)
def test_approve_runs_exactly_the_frozen_legs_once_with_no_model_call(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    classifier_calls, composer_calls = e.cls.calls, e.comp.calls
    r = approve(e, e.owner, inv, plan)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DELIVERED" and body["routeSource"] == "APPROVAL" and body["plan"]["status"] == "APPROVED" and body["replayed"] is False
    assert list(e.calls) == ["cmo.generate_hashtags"] and len(e.calls["cmo.generate_hashtags"]) == 1
    ran = e.calls["cmo.generate_hashtags"][0]
    frozen = plan["plan"]["legs"][0]["slots"]
    assert ran["marketplace"] == "AMAZON" and ran["request_key"] == frozen["request_key"] == f"ceo-plan-{plan['id']}" and ran["product_name"] == frozen["product_name"]
    assert (e.cls.calls, e.comp.calls) == (classifier_calls, composer_calls), "approval called the classifier or the composer"  # AC-A8
    t = repo.get_turn(e.a, uuid.UUID(body["turnId"]))
    assert t["route_source"] == "APPROVAL" and str(t["plan_id"]) == plan["id"] and t["status"] == "DELIVERED"
    row = repo_plan(e, inv, plan["id"])
    assert row["status"] == "APPROVED" and row["execution_turn_id"] == t["id"] and row["decided_by"] == row["requested_by"]
    assert [ev[0] for ev in events_of(e.a, plan["id"])] == ["CREATED", "APPROVED", "EXECUTION_STARTED", "EXECUTION_FINISHED"]
    assert ("APPROVED", "AWAITING_APPROVAL", "APPROVED", "USER", "USER_APPROVED") in events_of(e.a, plan["id"])
    assert any(m["kind"] == "SYSTEM_NOTE" and m["content"] == f"You approved: {plan['plan']['title']}" for m in repo.list_messages(e.a, uuid.UUID(inv)))
    msgs = repo.list_messages(e.a, uuid.UUID(inv))
    note = next(m for m in msgs if m["kind"] == "SYSTEM_NOTE")
    assert "\n" not in note["content"] and len(note["content"]) < 140  # one short line, not the plan again
    assert next(m for m in msgs if m["kind"] == "PLAN")["content"] == approval.PLAN_MESSAGE_LEAD  # the chat message is the short lead only; the card holds the plan
    assert 3 <= len(plan["plan"]["compact_lines"]) <= 5 and plan["plan"]["summary_text"] and len(plan["plan"]["summary_text"]) > sum(len(l) for l in plan["plan"]["compact_lines"])  # compact card, complete stored text
    # one CEO conversation unit for the approved, delivered execution turn (the planned turn cost nothing)
    assert rows(e.a, "SELECT idempotency_key FROM metered_event") == [(f"ceo:turn:{t['id']}",)]


def test_a_wrong_or_stale_hash_is_a_409_and_changes_nothing(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    before = counts(e.a)
    for bad in ("0" * 64, "x", plan["planHash"][:-1] + ("0" if plan["planHash"][-1] != "0" else "1"), plan["planHash"].upper()):
        r = approve(e, e.owner, inv, plan, plan_hash=bad)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_CHANGED", bad
    assert e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={}, headers=e.owner).status_code == 422  # a missing hash cannot approve
    assert_untouched(e, inv, plan, before)
    refused = [ev for ev in events_of(e.a, plan["id"]) if ev[0] == "APPROVAL_REFUSED"]
    assert len(refused) == 4 and {ev[4] for ev in refused} == {"HASH_MISMATCH"}


def test_the_hash_of_another_plan_cannot_approve_this_one(env):
    e = env
    inv, first = plan_via_chat(e)
    _, second = plan_via_chat(e, inv=inv)
    r = approve(e, e.owner, inv, second["plan"], plan_hash=first["plan"]["planHash"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_CHANGED" and e.calls == {}


def test_another_member_even_the_owner_cannot_approve_or_decline(env):
    e = env
    inv, planned = plan_via_chat(e, headers=e.other)  # a partner asked
    plan = planned["plan"]
    before = counts(e.a)
    r = approve(e, e.owner, inv, plan)  # the tenant's OWNER: roles grant no override (C7)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NOT_REQUESTER"
    d = decline(e, e.owner, inv, plan)
    assert d.status_code == 403 and d.json()["detail"]["code"] == "NOT_REQUESTER"
    assert_untouched(e, inv, plan, before)
    refused = [ev for ev in events_of(e.a, plan["id"]) if ev[0] == "APPROVAL_REFUSED"]
    assert len(refused) == 2 and {ev[4] for ev in refused} == {"NOT_REQUESTER"}
    assert get_plan(e, e.owner, inv, plan["id"]).json()["viewerIsRequester"] is False  # the card shows no Approve / Decline to them
    assert get_plan(e, e.other, inv, plan["id"]).json()["viewerIsRequester"] is True
    assert approve(e, e.other, inv, plan).status_code == 200  # the requester still can


def test_approving_twice_runs_once_and_returns_the_same_turn(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    first = approve(e, e.owner, inv, plan).json()
    second = approve(e, e.owner, inv, plan)
    assert second.status_code == 200 and second.json()["replayed"] is True and second.json()["turnId"] == first["turnId"] and second.json()["status"] == "DELIVERED"
    assert len(e.calls["cmo.generate_hashtags"]) == 1
    assert counts(e.a)["approval_turns"] == 1 and counts(e.a)["units"] == 1  # quota is never charged twice for the same operation
    assert [ev[0] for ev in events_of(e.a, plan["id"])].count("APPROVED") == 1


def test_concurrent_approvals_start_exactly_one_run(env):
    e = env
    e.rt = dataclasses.replace(e.rt, registry=recording_registry(e.calls, delay=0.6))
    from backend.main import app

    app.dependency_overrides[ceo_api.get_runtime] = lambda: e.rt
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    out: list = []
    gate = threading.Barrier(2)

    def go() -> None:
        gate.wait()
        out.append(approve(e, e.owner, inv, plan))

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    codes = sorted(r.status_code for r in out)
    assert codes in ([200, 200], [200, 409]), [r.text for r in out]  # the loser is a replay, or told another request holds the conversation
    assert all(r.json()["detail"]["code"] == "TURN_IN_PROGRESS" for r in out if r.status_code == 409)
    assert len(e.calls["cmo.generate_hashtags"]) == 1
    assert counts(e.a)["approval_turns"] == 1 and counts(e.a)["units"] == 1
    assert [ev[0] for ev in events_of(e.a, plan["id"])].count("APPROVED") == 1


def test_approval_works_whatever_the_chat_switch_says_and_acts_on_stored_plans_only(env):
    e = env
    inv, planned = plan_via_chat(e)
    e.monkeypatch.delenv("CEO_APPROVAL_ENABLED")  # the switch controls whether CHAT creates plans, not whether a stored plan can be decided
    assert approve(e, e.owner, inv, planned["plan"]).status_code == 200


# ------------------------------------------------------------------------------------------------ decline, expiry, supersession (AC-A5, AC-A9, E3)
def test_decline_is_terminal_costs_nothing_and_cannot_be_approved_afterwards(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    d = decline(e, e.owner, inv, plan, "changed my mind")
    assert d.status_code == 200 and d.json()["status"] == "DECLINED" and d.json()["decisionReason"] == "changed my mind"
    assert events_of(e.a, plan["id"])[-1] == ("DECLINED", "AWAITING_APPROVAL", "DECLINED", "USER", "USER_DECLINED")
    assert any(m["kind"] == "SYSTEM_NOTE" and m["content"].startswith("Declined") for m in repo.list_messages(e.a, uuid.UUID(inv)))
    assert counts(e.a)["units"] == 0 and counts(e.a)["approval_turns"] == 0 and e.calls == {} and e.cls.calls == 0 and e.comp.calls == 0
    for call in (lambda: approve(e, e.owner, inv, plan), lambda: decline(e, e.owner, inv, plan)):
        r = call()
        assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_NOT_AWAITING" and r.json()["detail"]["status"] == "DECLINED"
    assert e.calls == {} and counts(e.a)["approval_turns"] == 0


def test_a_plan_expires_exactly_1800_seconds_after_creation(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    created, expires = datetime.fromisoformat(plan["createdAt"]), datetime.fromisoformat(plan["expiresAt"])
    assert expires == created + timedelta(seconds=1800)
    before = counts(e.a)
    e.clock.set(expires)  # now == expires_at: no longer startable (C6: now < expires_at)
    r = approve(e, e.owner, inv, plan)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_EXPIRED"
    assert_untouched(e, inv, plan, before, status="EXPIRED")
    evs = events_of(e.a, plan["id"])
    assert ("EXPIRED", "AWAITING_APPROVAL", "EXPIRED", "SYSTEM", "TTL") in evs and any(ev[0] == "APPROVAL_REFUSED" and ev[4] == "EXPIRED" for ev in evs)
    assert approve(e, e.owner, inv, plan).status_code == 409  # terminal
    assert decline(e, e.owner, inv, plan).status_code == 409


def test_a_plan_one_millisecond_before_expiry_still_approves(env):
    e = env
    inv, planned = plan_via_chat(e)
    e.clock.set(datetime.fromisoformat(planned["plan"]["expiresAt"]) - timedelta(milliseconds=5))
    assert approve(e, e.owner, inv, planned["plan"]).status_code == 200


def test_reading_a_plan_after_expiry_persists_the_expiry_lazily(env):
    e = env
    inv, planned = plan_via_chat(e)
    e.clock.set(NOW + timedelta(seconds=2000))
    assert get_plan(e, e.owner, inv, planned["plan"]["id"]).json()["status"] == "EXPIRED"
    assert [ev[0] for ev in events_of(e.a, planned["plan"]["id"])].count("EXPIRED") == 1
    listed = e.client.get(f"/api/v1/ceo/investigations/{inv}/plans", headers=e.owner).json()["items"]
    assert [p["status"] for p in listed] == ["EXPIRED"] and [x["event"] for x in listed[0]["events"]] == ["CREATED", "EXPIRED"]
    assert counts(e.a)["units"] == 0  # an expired plan costs nothing


def test_a_new_plan_after_expiry_is_a_fresh_plan_with_its_own_hash(env):
    e = env
    inv, first = plan_via_chat(e)
    e.clock.set(NOW + timedelta(seconds=2000))
    _, second = plan_via_chat(e, inv=inv)
    assert second["plan"]["id"] != first["plan"]["id"] and approve(e, e.owner, inv, second["plan"]).status_code == 200


@pytest.mark.parametrize("how", ["resolve", "archive"])
def test_resolving_or_archiving_supersedes_the_open_plan_and_reopening_does_not_revive_it(env, how):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    body = {"resolution_note": "done"} if how == "resolve" else None
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/{how}", json=body, headers=e.owner) if body else e.client.post(f"/api/v1/ceo/investigations/{inv}/{how}", headers=e.owner)
    assert r.status_code in (200, 204), r.text
    assert repo_plan(e, inv, plan["id"])["status"] == "SUPERSEDED"
    assert (f"INVESTIGATION_{how.upper()}D" if how == "resolve" else "INVESTIGATION_ARCHIVED") in {ev[4] for ev in events_of(e.a, plan["id"])}
    a = approve(e, e.owner, inv, plan)
    assert a.status_code == 409 and a.json()["detail"]["code"] == "INVESTIGATION_NOT_ACTIVE"
    repo.reopen_investigation(e.a, uuid.UUID(inv))
    a = approve(e, e.owner, inv, plan)
    assert a.status_code == 409 and a.json()["detail"]["code"] == "PLAN_NOT_AWAITING" and e.calls == {}


# ------------------------------------------------------------------------------------------------ re-validation at approval (6.6 steps 6-10, AC-A13)
def test_a_lost_permission_blocks_execution_and_leaves_a_denied_run(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    row = repo_plan(e, inv, plan["id"])
    # the same person, now a partner who holds the CEO keys but not the CMO key
    ctx = ctx_for(e.a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_VIEW: True}, user_id=row["requested_by"])
    with pytest.raises(approval.ApprovalRefused) as x:
        approval_run.approve_plan(ctx, e.rt, uuid.UUID(inv), uuid.UUID(plan["id"]), plan["planHash"])
    assert x.value.status_code == 403 and x.value.reason_code == "PERMISSION"
    assert e.calls == {} and counts(e.a)["approval_turns"] == 0 and repo_plan(e, inv, plan["id"])["status"] == "AWAITING_APPROVAL"
    assert rows(e.a, "SELECT count(*) FROM agent_run WHERE status = 'DENIED' AND trigger_ref = 'ceo.approved_plan'")[0][0] == 1
    assert any(ev[0] == "APPROVAL_REFUSED" and ev[4] == "PERMISSION" for ev in events_of(e.a, plan["id"]))
    assert approve(e, e.owner, inv, plan).status_code == 200  # the plan was intact: with access restored it still runs


def test_a_lost_ceo_permission_is_refused_the_same_way(env):
    e = env
    inv, planned = plan_via_chat(e)
    row = repo_plan(e, inv, planned["plan"]["id"])
    ctx = ctx_for(e.a, role=PARTNER_ROLE, permissions={}, user_id=row["requested_by"])
    with pytest.raises(approval.ApprovalRefused) as x:
        approval_run.approve_plan(ctx, e.rt, uuid.UUID(inv), uuid.UUID(planned["plan"]["id"]), planned["plan"]["planHash"])
    assert x.value.status_code == 403 and e.calls == {} and counts(e.a)["approval_turns"] == 0


def test_a_detached_agent_blocks_execution(env):
    e = env
    inv, planned = plan_via_chat(e)
    repo.set_agent_attachment(e.a, uuid.UUID(inv), "CMO", attached=False, changed_by=repo_plan(e, inv, planned["plan"]["id"])["requested_by"])
    before = counts(e.a)
    r = approve(e, e.owner, inv, planned["plan"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_STALE"
    assert_untouched(e, inv, planned["plan"], before)
    assert any(ev[0] == "APPROVAL_REFUSED" and ev[4] == "NOT_ATTACHED" for ev in events_of(e.a, planned["plan"]["id"]))


def test_an_exhausted_ceo_allowance_refuses_and_keeps_the_plan_open(env):
    e = env
    inv, planned = plan_via_chat(e)
    seed_platform_cap(e.migrate_engine, agent_code="CEO", meter_code="ceo.chat_turn", cap_value=0)
    before = counts(e.a)
    r = approve(e, e.owner, inv, planned["plan"])
    assert r.status_code == 402 and r.json()["detail"]["code"] == "ENTITLEMENT_DENIED"
    assert counts(e.a)["approval_turns"] == 0 and counts(e.a)["units"] == before["units"] and e.calls == {}
    assert repo_plan(e, inv, planned["plan"]["id"])["status"] == "AWAITING_APPROVAL"  # E5: stays open until expiry
    assert any(ev[0] == "APPROVAL_REFUSED" and ev[4] == "ENTITLEMENT" for ev in events_of(e.a, planned["plan"]["id"]))
    assert rows(e.a, "SELECT count(*) FROM agent_run WHERE status = 'DENIED' AND agent_id = 'CEO'")[0][0] == 1


def test_a_changed_data_basis_makes_the_plan_stale(env):
    e = env
    basis = {"kind": "NICHE_BRIEF", "id": str(uuid.uuid4()), "as_of": "t1", "fingerprint": "f1"}
    state = {"now": dict(basis)}
    e.monkeypatch.setattr(approval, "data_basis_for", lambda tenant, slots, investigation_id=None: [basis])
    e.monkeypatch.setitem(approval._BASIS_RESOLVERS, "NICHE_BRIEF", lambda tenant, ref: state["now"])
    inv, planned = plan_via_chat(e)
    assert planned["plan"]["plan"]["data_basis"] == [basis]
    state["now"] = {**basis, "fingerprint": "f2"}  # the record behind the plan changed
    before = counts(e.a)
    r = approve(e, e.owner, inv, planned["plan"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "PLAN_STALE"
    assert_untouched(e, inv, planned["plan"], before)
    assert any(ev[0] == "APPROVAL_REFUSED" and ev[4] == "DATA_CHANGED" for ev in events_of(e.a, planned["plan"]["id"]))
    state["now"] = None  # no longer resolves at all
    assert approve(e, e.owner, inv, planned["plan"]).status_code == 409
    state["now"] = dict(basis)  # back to what the plan was made on: it approves
    assert approve(e, e.owner, inv, planned["plan"]).status_code == 200


def test_integration_that_disappears_after_planning_blocks_a_data_sending_plan(env):
    e = env
    inv, first = plan_via_chat(e)
    user = uuid.UUID(first["plan"]["requestedBy"])
    built, _ = make_plan(e, inv, user, [("cmo.market_trends", TRENDS)], route_key="cmo.market_trends")  # the real planner, for a data-sending action
    e.monkeypatch.delenv("TAVILY_API_KEY")  # the provider key is removed before approval
    config.tavily_api_key.cache_clear()
    before = counts(e.a)
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{built.plan_id}/approve", json={"plan_hash": built.plan_hash}, headers=e.owner)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INTEGRATION_UNAVAILABLE" and r.json()["detail"]["integration"] == "Tavily"
    assert e.calls == {} and counts(e.a)["approval_turns"] == 0 and counts(e.a)["units"] == before["units"]
    assert any(ev[0] == "APPROVAL_REFUSED" and ev[4] == "INTEGRATION_UNAVAILABLE" for ev in events_of(e.a, str(built.plan_id)))


def test_missing_execution_limits_at_approval_fail_closed(env):
    e = env
    inv, planned = plan_via_chat(e)
    row = repo_plan(e, inv, planned["plan"]["id"])
    ctx = ctx_for(e.a, user_id=row["requested_by"])
    with pytest.raises(approval.ApprovalRefused) as x:
        approval_run.approve_plan(ctx, dataclasses.replace(e.rt, leg_timeout_seconds=None), uuid.UUID(inv), row["id"], row["plan_hash"])
    assert x.value.code == "EXECUTION_LIMITS" and e.calls == {} and counts(e.a)["approval_turns"] == 0


def test_a_busy_conversation_refuses_without_changing_the_plan_then_works_when_free(env):
    e = env
    inv, planned = plan_via_chat(e)
    with investigation_turn_lock(uuid.UUID(inv), None):  # another request holds the conversation
        before = counts(e.a)
        r = approve(e, e.owner, inv, planned["plan"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TURN_IN_PROGRESS"
    assert_untouched(e, inv, planned["plan"], before)
    assert approve(e, e.owner, inv, planned["plan"]).status_code == 200


# ------------------------------------------------------------------------------------------------ failure: consumed, no retry, no quota (D5, AC-A15)
def test_a_failed_execution_consumes_the_plan_charges_nothing_and_is_never_retried(env):
    e = env
    e.rt = dataclasses.replace(e.rt, registry=recording_registry(e.calls, fail=True))
    from backend.main import app

    app.dependency_overrides[ceo_api.get_runtime] = lambda: e.rt
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    r = approve(e, e.owner, inv, plan)
    assert r.status_code == 200 and r.json()["outcome"] == "FAILED"  # the turn is delivered with its outcome shown (D6); it is not a success
    assert len(e.calls["cmo.generate_hashtags"]) == 1
    assert counts(e.a)["units"] == 0  # no CEO unit, and no quota event for the failed leg
    assert repo_plan(e, inv, plan["id"])["status"] == "APPROVED"  # consumed
    assert [ev[0] for ev in events_of(e.a, plan["id"])] == ["CREATED", "APPROVED", "EXECUTION_STARTED", "EXECUTION_FAILED"]
    again = approve(e, e.owner, inv, plan)  # a repeat reports the same failed turn; it never re-runs
    assert again.status_code == 200 and again.json()["replayed"] is True and again.json()["turnId"] == r.json()["turnId"]
    assert len(e.calls["cmo.generate_hashtags"]) == 1 and counts(e.a)["units"] == 0
    # the only way forward is a NEW plan with a NEW approval
    _, fresh = plan_via_chat(e, inv=inv)
    assert fresh["plan"]["id"] != plan["id"] and fresh["plan"]["planHash"] != plan["planHash"] and fresh["plan"]["status"] == "AWAITING_APPROVAL"
    assert len(e.calls["cmo.generate_hashtags"]) == 1


def test_a_denied_leg_at_execution_is_a_failed_run_with_no_charge(env):
    e = env
    inv, planned = plan_via_chat(e)
    real_get = e.rt.registry.get
    # the specialist's own gate refuses at run time (e.g. its quota): a 402 inside the leg
    from fastapi import HTTPException

    def refuse(s, c, leg):
        raise HTTPException(status_code=402)

    spec = dataclasses.replace(real_get("cmo.generate_hashtags"), invoke=refuse)
    e.rt = dataclasses.replace(e.rt, registry=ActionRegistry([spec]))
    from backend.main import app

    app.dependency_overrides[ceo_api.get_runtime] = lambda: e.rt
    r = approve(e, e.owner, inv, planned["plan"])
    assert r.status_code == 200 and r.json()["outcome"] == "FAILED" and counts(e.a)["units"] == 0 and rows(e.a, "SELECT event FROM investigation_plan_event WHERE event = 'EXECUTION_FAILED'")


# ------------------------------------------------------------------------------------------------ tenant isolation (AC-A11)
def test_another_tenant_cannot_read_list_approve_or_decline_a_plan(env):
    e = env
    inv, planned = plan_via_chat(e)
    plan = planned["plan"]
    before = counts(e.a)
    # tenant B, using tenant A's real investigation and plan ids
    unknown = str(uuid.uuid4())
    for call in (
        lambda i, p: get_plan(e, e.foreign, i, p),
        lambda i, p: e.client.get(f"/api/v1/ceo/investigations/{i}/plans", headers=e.foreign),
        lambda i, p: e.client.post(f"/api/v1/ceo/investigations/{i}/plans/{p}/approve", json={"plan_hash": plan["planHash"]}, headers=e.foreign),
        lambda i, p: e.client.post(f"/api/v1/ceo/investigations/{i}/plans/{p}/decline", json={}, headers=e.foreign),
    ):
        real, missing = call(inv, plan["id"]), call(unknown, unknown)
        assert real.status_code == missing.status_code == 404, (real.text, missing.text)  # a foreign id looks exactly like a missing one
        assert real.json() == missing.json()
    own_inv = start(e, e.foreign)
    r = get_plan(e, e.foreign, own_inv, plan["id"])  # B's own investigation, A's plan id
    assert r.status_code == 404
    assert e.client.get(f"/api/v1/ceo/investigations/{own_inv}/plans", headers=e.foreign).json()["items"] == []
    assert_untouched(e, inv, plan, before)
    assert rows(e.b, "SELECT count(*) FROM investigation_plan")[0][0] == 0 and rows(e.b, "SELECT count(*) FROM investigation_plan_event")[0][0] == 0


def test_a_plan_of_another_investigation_of_the_same_tenant_is_a_404(env):
    e = env
    inv1, planned = plan_via_chat(e)
    inv2 = start(e, e.owner)
    r = approve(e, e.owner, inv2, planned["plan"])
    assert r.status_code == 404 and get_plan(e, e.owner, inv2, planned["plan"]["id"]).status_code == 404 and e.calls == {}


def test_missing_tenant_context_fails_closed():
    with pytest.raises(Exception):
        plan_repo.get(None, uuid.uuid4(), uuid.uuid4())  # type: ignore[arg-type]
    with pytest.raises(Exception):
        plan_repo.list_for_investigation(None, uuid.uuid4())  # type: ignore[arg-type]


def test_no_endpoint_takes_a_tenant_id(env):
    e = env
    paths = [p for p in e.client.app.openapi()["paths"] if "/plans" in p]
    assert paths and not any("tenant" in p.lower() for p in paths)
    for p in paths:
        for op in e.client.app.openapi()["paths"][p].values():
            assert not any("tenant" in str(x).lower() for x in op.get("parameters", []))
    inv, planned = plan_via_chat(e)
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{planned['plan']['id']}/approve", json={"plan_hash": "0" * 64, "tenant_id": str(e.b)}, headers=e.owner)
    assert r.status_code == 409 and e.calls == {}  # the extra field is ignored, never used


def test_the_investigation_detail_lists_its_plans_for_the_frontend_card(env):
    e = env
    inv, planned = plan_via_chat(e)
    detail = e.client.get(f"/api/v1/ceo/investigations/{inv}", headers=e.owner).json()
    assert [p["id"] for p in detail["plans"]] == [planned["plan"]["id"]] and detail["plans"][0]["viewerIsRequester"] is True
    assert any(m["kind"] == "PLAN" for m in detail["messages"])


# ------------------------------------------------------------------------------------------------ the dispatch backstop
def test_the_grant_covers_only_its_own_tenant_and_the_keys_frozen_in_its_plan(two_tenants, app_user):
    a, b = two_tenants
    calls: dict = {}
    reg = recording_registry(calls)
    ctx = ctx_for(a, user_id=app_user)
    inv, t = _open(a, app_user, ctx)
    nogrant = dispatch(t, "cmo.generate_hashtags", HASHTAGS, registry=reg, attached=frozenset(ALL_AGENTS), now=NOW)
    wrong_key = dispatch(t, "cmo.generate_hashtags", HASHTAGS, registry=reg, attached=frozenset(ALL_AGENTS), now=NOW, approval=ApprovalGrant(uuid.uuid4(), a, frozenset({"cmo.generate_title_sets"})))
    wrong_tenant = dispatch(t, "cmo.generate_hashtags", HASHTAGS, registry=reg, attached=frozenset(ALL_AGENTS), now=NOW, approval=ApprovalGrant(uuid.uuid4(), b, frozenset({"cmo.generate_hashtags"})))
    for leg in (nogrant, wrong_key, wrong_tenant):
        assert leg.status is LegStatus.DENIED and leg.denial is Denial.APPROVAL_REQUIRED
    assert calls == {}
    ok = dispatch(t, "cmo.generate_hashtags", HASHTAGS, registry=reg, attached=frozenset(ALL_AGENTS), now=NOW, approval=ApprovalGrant(uuid.uuid4(), a, frozenset({"cmo.generate_hashtags"})))
    assert ok.status is LegStatus.COMPLETE and len(calls["cmo.generate_hashtags"]) == 1


def test_a_grant_still_leaves_the_per_leg_permission_check_in_force(two_tenants, app_user):
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_VIEW: True}, user_id=app_user)
    inv = repo.create_investigation(a, created_by=app_user, attached_agents=tuple(ALL_AGENTS), now=NOW)
    from backend.ceo.dispatch import open_turn

    t = open_turn(ctx, investigation_id=inv, now=NOW)
    leg = dispatch(t, "cmo.generate_hashtags", HASHTAGS, registry=recording_registry(calls), attached=frozenset(ALL_AGENTS), now=NOW,
                   approval=ApprovalGrant(uuid.uuid4(), a, frozenset({"cmo.generate_hashtags"})))
    assert leg.status is LegStatus.DENIED and leg.denial is Denial.PERMISSION and calls == {}


# ------------------------------------------------------------------------------------------------ helpers that build a plan below the chat layer
def make_plan(e: Env, inv: str, user: uuid.UUID, legs, *, route_key: str):
    ctx = ctx_for(e.a, user_id=user)
    msg = repo.append_message(e.a, uuid.UUID(inv), role="USER", content="plan", created_by=user, now=NOW)
    from backend.ceo.dispatch import open_turn

    t = open_turn(ctx, investigation_id=uuid.UUID(inv), now=NOW)
    t.turn_id = repo.create_turn(e.a, uuid.UUID(inv), user_message_id=msg, agent_run_id=t.anchor_run_id, route="ACTION", route_key=route_key, status="PLAN_VALIDATED", now=NOW)
    built, mid = approval.create_plan(ctx, e.rt, investigation_id=uuid.UUID(inv), planned_turn_id=t.turn_id, anchor_run_id=t.anchor_run_id, route="ACTION", route_key=route_key, legs=legs, now=NOW)
    t.close(status="COMPLETE", now=NOW)
    return built, mid


def test_without_the_accounting_rule_in_effect_no_plan_is_made_and_nothing_can_cost_a_unit(env):
    e = env
    e.monkeypatch.setattr(accounting_cutover_repo, "effective_at", lambda code: None)
    inv = start(e, e.owner)
    turn(e, e.owner, inv, ASK)
    r = skip_details(e, e.owner, inv, turn(e, e.owner, inv, "Amazon"))
    assert r["status"] == "FAILED" and "plan" not in r and "usage accounting rule" in r["answer"]
    assert counts(e.a) == {"plans": 0, "events": 0, "units": 0, "approval_turns": 0} and e.calls == {}


def test_an_identical_open_plan_is_found_for_reuse_and_nothing_else_is(env):
    """`open_plan_for` (used for a repeated competitor search): the seller's own, undecided, unexpired plan with exactly the same legs and slots - never a changed, expired,
    declined or another member's plan."""
    e = env
    inv, planned = plan_via_chat(e)
    row = repo_plan(e, inv, planned["plan"]["id"])
    legs = [(l["action_key"], l["slots"]) for l in row["plan"]["legs"]]
    owner_id = row["requested_by"]
    now = e.clock()
    found = approval.open_plan_for(e.a, uuid.UUID(inv), owner_id, legs, now=now)
    assert found is not None and str(found["id"]) == planned["plan"]["id"]
    changed = [(k, {**s, "product_name": "Something else"}) for k, s in legs]
    assert approval.open_plan_for(e.a, uuid.UUID(inv), owner_id, changed, now=now) is None
    assert approval.open_plan_for(e.a, uuid.UUID(inv), uuid.uuid4(), legs, now=now) is None  # another member
    assert approval.open_plan_for(e.a, uuid.UUID(inv), owner_id, legs, now=now + timedelta(hours=1)) is None  # expired
    assert decline(e, e.owner, inv, planned["plan"]).status_code == 200
    assert approval.open_plan_for(e.a, uuid.UUID(inv), owner_id, legs, now=e.clock()) is None  # decided
