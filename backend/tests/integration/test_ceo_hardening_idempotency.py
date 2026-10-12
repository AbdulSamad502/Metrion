"""Hardening Fix 3: a RESEND of one submission must not create a second turn or run its actions again; a NEW submission with identical text must.

Contract under test (internal, `orchestrator.run_turn(..., request_key=...)`): the key identifies ONE logical submission, scoped to its investigation. Same key + same text
returns the stored outcome (`replayed=True`) and writes and runs nothing; same key + different text is refused; a different key is a new submission. The check-then-act is
serialised by the per-investigation Postgres advisory lock, so concurrent copies cannot both run. Without a key nothing changes (the documented baseline below).

NOT claimed: exactly-once for external side effects. An action that completed and whose result was stored is never re-run for the same key; an action interrupted by a crash
may or may not have taken effect, and a retry with the same key will not re-run it (the seller sends a new submission to try again). The public API does not carry the key yet:
that contract change needs approval (see the campaign report)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import text

from backend.ceo import orchestrator
from backend.ceo.registry import ActionRegistry
from backend.ceo.turn_lock import TurnInProgress
from backend.repositories import investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_campaign_routing_e2e import build
from tests.integration.test_ceo_turn import start

pytestmark = pytest.mark.usefixtures("two_tenants")

MSG = "What GST rate applies to steel water bottles?"


def setup(tenant, user, *, handler=None):
    rt, called, _ = build(None)
    if handler is not None:
        rt = replace(rt, registry=ActionRegistry([replace(s, invoke=handler) if s.key == "cfo.gst_lookup" else s for s in rt.registry.specs()]))
    ctx = ctx_for(tenant, user_id=user)
    return ctx, rt, called, start(ctx, rt)


def counts(tenant, inv):
    with tenant_scope(tenant) as conn:
        one = lambda sql: conn.execute(text(sql), {"i": str(inv)}).scalar_one()  # noqa: E731
        return {
            "user_messages": one("SELECT count(*) FROM investigation_message WHERE investigation_id = :i AND role = 'USER'"),
            "ceo_messages": one("SELECT count(*) FROM investigation_message WHERE investigation_id = :i AND role = 'CEO'"),
            "turns": one("SELECT count(*) FROM investigation_turn WHERE investigation_id = :i"),
            "legs": one("SELECT count(*) FROM agent_run WHERE investigation_id = :i AND trigger_ref = 'cfo.gst_lookup'"),
            "ceo_runs": one("SELECT count(*) FROM agent_run WHERE investigation_id = :i AND agent_id = 'CEO'"),
        }


ONCE = {"user_messages": 1, "ceo_messages": 1, "turns": 1, "legs": 1, "ceo_runs": 1}


def test_the_same_submission_sent_twice_in_a_row_runs_once_and_the_second_reply_is_the_first_outcome(two_tenants, app_user):
    a, _ = two_tenants
    ctx, rt, called, inv = setup(a, app_user)
    key = str(uuid.uuid4())
    first = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    second = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    assert not first.replayed and second.replayed
    assert (second.turn_id, second.message_id, second.answer, second.status, second.route_key) == (first.turn_id, first.message_id, first.answer, first.status, first.route_key)
    assert called == ["cfo.gst_lookup"] and counts(a, inv) == ONCE


def test_a_fresh_runtime_after_completion_still_replays_it(two_tenants, app_user):
    a, _ = two_tenants
    ctx, rt, called, inv = setup(a, app_user)
    key = str(uuid.uuid4())
    first = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    rt2, called2, _ = build(None)  # a restarted process: no memory of the first call
    again = orchestrator.run_turn(ctx, rt2, inv, MSG, request_key=key)
    assert again.replayed and again.turn_id == first.turn_id and called2 == [] and counts(a, inv) == ONCE


def test_two_concurrent_copies_of_one_submission_run_the_action_once(two_tenants, app_user, monkeypatch):
    monkeypatch.setenv("CEO_TURN_LOCK_WAIT_SECONDS", "20")  # the second copy waits for the first, then finds its stored outcome
    a, _ = two_tenants
    started = threading.Event()

    def slow(slots, c, leg):
        started.set()
        time.sleep(0.6)
        return {"result": None, "noMatch": None}

    ctx, rt, called, inv = setup(a, app_user, handler=slow)
    key, out, errors = str(uuid.uuid4()), [], []

    def go():
        try:
            out.append(orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert not errors and len(out) == 2
    assert sorted(r.replayed for r in out) == [False, True] and len({r.turn_id for r in out}) == 1
    assert counts(a, inv) == ONCE


def test_a_retry_while_the_first_is_still_running_is_refused_without_writing_anything_and_then_replays(two_tenants, app_user):
    a, _ = two_tenants
    release, entered = threading.Event(), threading.Event()

    def blocked(slots, c, leg):
        entered.set()
        release.wait(timeout=20)
        return {"result": None, "noMatch": None}

    ctx, rt, called, inv = setup(a, app_user, handler=blocked)
    key, first = str(uuid.uuid4()), []
    t = threading.Thread(target=lambda: first.append(orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)))
    t.start()
    assert entered.wait(timeout=20)
    with pytest.raises(TurnInProgress):  # the original is in flight: the retry is told so, and creates nothing
        orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    release.set()
    t.join(timeout=30)
    assert counts(a, inv) == ONCE
    again = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    assert again.replayed and again.turn_id == first[0].turn_id and counts(a, inv) == ONCE


def test_a_genuinely_new_submission_with_identical_text_runs_again(two_tenants, app_user):
    a, _ = two_tenants
    ctx, rt, called, inv = setup(a, app_user)
    one = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=str(uuid.uuid4()))
    two = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=str(uuid.uuid4()))
    assert not one.replayed and not two.replayed and one.turn_id != two.turn_id
    assert called == ["cfo.gst_lookup"] * 2
    assert counts(a, inv) == {"user_messages": 2, "ceo_messages": 2, "turns": 2, "legs": 2, "ceo_runs": 2}


def test_a_failed_original_is_not_silently_re_run_by_a_retry_but_a_new_submission_can_try_again(two_tenants, app_user):
    a, _ = two_tenants
    attempts: list[int] = []

    def flaky(slots, c, leg):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("first attempt fails")
        return {"result": None, "noMatch": None}

    ctx, rt, called, inv = setup(a, app_user, handler=flaky)
    key = str(uuid.uuid4())
    failed = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    retry = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    assert retry.replayed and retry.turn_id == failed.turn_id and retry.status == failed.status and len(attempts) == 1  # the stored (failed) outcome, not a hidden re-run
    fresh = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=str(uuid.uuid4()))  # the seller deliberately tries again
    assert not fresh.replayed and len(attempts) == 2 and fresh.status == "DELIVERED"
    assert counts(a, inv)["turns"] == 2


def test_an_original_that_failed_before_anything_was_recorded_is_run_normally_by_its_retry(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    ctx, rt, called, inv = setup(a, app_user)
    key = str(uuid.uuid4())
    real = repo.create_turn
    monkeypatch.setattr(repo, "create_turn", lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("could not record the turn")))
    original = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)  # dies before any action ran: a stored FAILED answer, no turn row
    assert original.status == "FAILED" and original.turn_id is None
    monkeypatch.setattr(repo, "create_turn", real)
    assert called == []
    retry = orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    assert not retry.replayed and called == ["cfo.gst_lookup"]  # the original never ran anything, so the retry is the one execution
    assert counts(a, inv)["turns"] == 1 and counts(a, inv)["legs"] == 1  # (the failed attempt's own question and answer remain in the thread: they are real events)


def test_the_same_key_with_different_text_is_refused_not_replayed(two_tenants, app_user):
    a, _ = two_tenants
    ctx, rt, called, inv = setup(a, app_user)
    key = str(uuid.uuid4())
    orchestrator.run_turn(ctx, rt, inv, MSG, request_key=key)
    with pytest.raises(orchestrator.IdempotencyConflict):
        orchestrator.run_turn(ctx, rt, inv, "Where am I losing money?", request_key=key)
    assert counts(a, inv) == ONCE


def test_a_key_is_scoped_to_its_investigation_and_its_tenant(two_tenants, app_user):
    a, b = two_tenants
    ctx_a, rt, called, inv_a = setup(a, app_user)
    inv_a2 = start(ctx_a, rt)
    ctx_b, rt_b, called_b, inv_b = setup(b, app_user)
    key = str(uuid.uuid4())
    orchestrator.run_turn(ctx_a, rt, inv_a, MSG, request_key=key)
    other_inv = orchestrator.run_turn(ctx_a, rt, inv_a2, MSG, request_key=key)
    other_tenant = orchestrator.run_turn(ctx_b, rt_b, inv_b, MSG, request_key=key)
    assert not other_inv.replayed and not other_tenant.replayed
    assert called == ["cfo.gst_lookup"] * 2 and called_b == ["cfo.gst_lookup"]


def test_baseline_without_a_key_a_resend_is_a_new_turn(two_tenants, app_user):
    """Documented, unchanged behaviour: with no key there is no way to tell a retry from a repeated question, and identical text is never assumed to be a retry."""
    a, _ = two_tenants
    ctx, rt, called, inv = setup(a, app_user)
    orchestrator.run_turn(ctx, rt, inv, MSG)
    orchestrator.run_turn(ctx, rt, inv, MSG)
    assert called == ["cfo.gst_lookup"] * 2 and counts(a, inv)["turns"] == 2
