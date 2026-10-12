"""Task 1 campaign: CEO orchestration outcome classes through the REAL `run_turn` against a real Postgres.

Evidence category: real-dispatcher integration + database persistence, with a FAKE (scripted) classifier and composer and, where the test is about a failure
class, a fake registry whose handlers fail in a controlled way. No live model, no network, no paid call. Nothing here checks a financial number: the legs
are only used as stand-in specialists whose STATUSES the CEO must propagate honestly."""

from __future__ import annotations

import dataclasses
import threading
import time

import pytest
from sqlalchemy import text

from backend.ceo import orchestrator
from backend.repositories import agent_run_repo, investigation_repo as repo
from backend.tenant_context import tenant_scope
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_turn import (  # noqa: F401  (fixtures + helpers shared with the B3 suite)
    MSG_PROFIT, PROFIT, Grounded, Scripted, children, fake_registry, health_config, runtime, start,
)

pytestmark = pytest.mark.usefixtures("two_tenants")

OK_HEALTH = {"overallBand": None, "perMetricBands": {}, "engineResultRefs": [], "unavailableReason": "stand-in"}


def _count(tenant, sql):
    with tenant_scope(tenant) as conn:
        return conn.execute(text(sql)).scalar_one()


def _unsettled(tenant):
    return _count(tenant, "SELECT count(*) FROM agent_run WHERE status IN ('RUNNING','QUEUED')")


# ------------------------------------------------------------------------------------------------ malformed specialist output
@pytest.mark.parametrize(
    "bad",
    [None, "plain text", ["a", "list"], 42, {"engineResultRef": "not-a-uuid"}, {"dataRequestId": 5, "partialReason": {"x": 1}}, {"nested": {"engineResultRef": [None, 7, "x"]}}],
    ids=["none", "string", "list", "int", "bad-ref", "odd-partial", "bad-nested-ref"],
)
def test_a_malformed_specialist_response_cannot_leave_a_run_open_or_sink_the_other_legs(bad, two_tenants, app_user, health_config):
    a, _ = two_tenants
    reg = fake_registry({"cfo.financial_health": lambda: dict(OK_HEALTH), "cfo.anomaly_check": lambda: bad, "cfo.strategic_briefing": lambda: {"signals": []}})
    comp = Grounded()
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), comp, registry=reg)
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)

    by_key = {c["trigger_ref"]: c for c in children(a, res)}
    assert by_key["cfo.financial_health"]["status"] == "COMPLETE" and by_key["cfo.strategic_briefing"]["status"] == "COMPLETE"  # unrelated legs survive
    assert _unsettled(a) == 0, "a malformed response left a child run RUNNING"  # every run reached a terminal state
    assert res.status in ("DELIVERED", "FAILED") and "Traceback" not in res.answer and "AttributeError" not in res.answer
    anomaly = [f for f in repo.list_findings(a, inv, turn_id=res.turn_id) if f["action_key"] == "cfo.anomaly_check"]
    if res.status == "DELIVERED":
        assert anomaly and anomaly[0]["status"] in ("COMPLETE", "PARTIAL", "FAILED")
        if anomaly[0]["status"] == "FAILED":
            assert "anomaly check could not be completed" in res.answer


@pytest.mark.parametrize(
    "key,bad",
    [
        ("cfo.anomaly_check", {"methods": ["not-a-dict", 5]}),
        ("cfo.anomaly_check", {"methods": {"unexpected": "shape"}}),
        ("cfo.strategic_briefing", {"signals": [7, None, "x"]}),
        ("cfo.financial_health", {"overallBand": "WATCH", "perMetricBands": ["a", "b"]}),
        ("cfo.financial_health", {"overallBand": {"nested": 1}, "perMetricBands": 3}),
    ],
    ids=["methods-list-of-junk", "methods-dict", "signals-junk", "bands-list", "band-object"],
)
def test_a_response_with_the_wrong_inner_shape_costs_only_its_own_leg_not_the_turn(key, bad, two_tenants, app_user, health_config):
    a, _ = two_tenants
    good = {"cfo.financial_health": dict(OK_HEALTH), "cfo.anomaly_check": {"methods": []}, "cfo.strategic_briefing": {"signals": []}}
    reg = fake_registry({k: (lambda k=k: bad if k == key else good[k]) for k in good})
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=reg)
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    assert res.status == "DELIVERED", res.answer  # the other legs' results still reach the seller
    assert _unsettled(a) == 0
    assert "Traceback" not in res.answer and "AttributeError" not in res.answer
    assert "could not be read" in res.answer or "could not be completed" in res.answer  # the broken leg is named, not hidden or presented as a finding
    others = [f for f in repo.list_findings(a, inv, turn_id=res.turn_id) if f["source"] == "CFO" and f["action_key"] != key]
    assert others and all(f["status"] == "COMPLETE" for f in others)


# ------------------------------------------------------------------------------------------------ synthesis / persistence failure
def test_a_composer_that_raises_fails_the_turn_honestly_and_keeps_the_completed_work(two_tenants, app_user, health_config):
    a, _ = two_tenants
    reg = fake_registry({"cfo.financial_health": lambda: dict(OK_HEALTH), "cfo.anomaly_check": lambda: {"methods": []}, "cfo.strategic_briefing": lambda: {"signals": []}})
    comp = Grounded()

    def boom(prompt, schema):
        raise RuntimeError("composer exploded: postgresql://user:pw@host/db")

    from backend.llm.model import ScriptedModel

    rt = dataclasses.replace(runtime(Scripted({MSG_PROFIT: PROFIT}), comp, registry=reg), composer=ScriptedModel(boom, name="boom"))
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    # The caller never learns what broke, never gets a success message, and the turn is not billed as delivered.
    assert "postgresql" not in res.answer and "exploded" not in res.answer
    turn = repo.get_turn(a, res.turn_id)
    assert res.status != "DELIVERED" or res.composition_mode in ("TEMPLATE", "template")  # a failed model path may ship the deterministic template, never a model draft
    assert _unsettled(a) == 0
    done = [f for f in repo.list_findings(a, inv, turn_id=res.turn_id) if f["status"] == "COMPLETE" and f["source"] == "CFO"]
    assert len(done) == 3  # nothing completed was lost (the three legs; the state reads are separate findings)
    assert turn["status"] in ("DELIVERED", "FAILED")
    # and the conversation is still usable
    again = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    assert again.turn_id != res.turn_id


# ------------------------------------------------------------------------------------------------ required leg slow / hung
def test_a_required_leg_that_misses_its_deadline_is_not_reported_as_a_completed_investigation(two_tenants, app_user, health_config):
    a, _ = two_tenants
    release = threading.Event()

    def slow():
        release.wait(timeout=20)
        return dict(OK_HEALTH)

    reg = fake_registry({"cfo.financial_health": slow, "cfo.anomaly_check": lambda: {"methods": []}, "cfo.strategic_briefing": lambda: {"signals": []}})
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), registry=reg, leg_timeout=1)
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    assert res.status == "FAILED" and "could not complete this investigation" in res.answer
    assert "still running" in res.answer  # named, not silently absent
    # The late leg is honest about being in flight, then settles by itself and lands in the findings.
    open_rows = [c["status"] for c in children(a, res) if c["trigger_ref"] == "cfo.financial_health"]
    assert open_rows == ["RUNNING"]
    release.set()
    deadline = time.time() + 15
    while time.time() < deadline and _unsettled(a):
        time.sleep(0.1)
    assert _unsettled(a) == 0
    assert any(f["action_key"] == "cfo.financial_health" and f["status"] == "COMPLETE" for f in repo.list_findings(a, inv))


# ------------------------------------------------------------------------------------------------ repeats and retries
def test_the_same_message_twice_is_two_turns_with_their_own_runs_and_no_shared_state(two_tenants, app_user, health_config):
    a, _ = two_tenants
    calls: list[int] = []
    reg = fake_registry({k: (lambda k=k: calls.append(1) or {"signals": []}) for k in ("cfo.financial_health", "cfo.anomaly_check", "cfo.strategic_briefing")})
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), registry=reg)
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    first = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    second = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    assert first.turn_id != second.turn_id and len(calls) == 6  # DOCUMENTED: the API has no client idempotency key, so a resend runs the legs again
    ids1 = {c["id"] for c in children(a, first)}
    ids2 = {c["id"] for c in children(a, second)}
    assert not (ids1 & ids2) and len(ids1) == len(ids2) == 3
    users = [m for m in repo.list_messages(a, inv) if m["role"] == "USER"]
    assert len(users) == 2  # the resend is visible as a resend; it is not silently merged
    assert _unsettled(a) == 0


# ------------------------------------------------------------------------------------------------ context separation
def test_a_new_investigation_does_not_inherit_the_old_conversation(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    cls = Scripted({"Thinking about marigold-7731 packaging today": '{"route":"ADVISORY","route_key":null,"slots":{},"needs_agent":null,"clarify_for":null}',
                    "What did I just ask?": '{"route":"ADVISORY","route_key":null,"slots":{},"needs_agent":null,"clarify_for":null}'})
    rt = runtime(cls)
    first = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, first, "Thinking about marigold-7731 packaging today")
    second = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, second, "What did I just ask?")
    assert "marigold-7731" in cls.prompts[0]
    assert "marigold-7731" not in cls.prompts[-1]  # the classifier for the new conversation saw none of the old one
    assert [m["content"] for m in repo.list_messages(a, second) if m["role"] == "USER"] == ["What did I just ask?"]


# ------------------------------------------------------------------------------------------------ persistence failures during a turn
def _stand_in_registry():
    return fake_registry({"cfo.financial_health": lambda: dict(OK_HEALTH), "cfo.anomaly_check": lambda: {"methods": []}, "cfo.strategic_briefing": lambda: {"signals": []}})


def test_a_finding_that_cannot_be_written_never_becomes_a_success_the_seller_is_told_about(two_tenants, app_user, health_config, monkeypatch):
    a, _ = two_tenants
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=_stand_in_registry())
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    real = repo.insert_finding

    def flaky(tenant, inv_id, **kw):
        if kw.get("action_key") == "cfo.anomaly_check":
            raise RuntimeError("db down: postgresql://u:p@h/db")
        return real(tenant, inv_id, **kw)

    monkeypatch.setattr(repo, "insert_finding", flaky)
    res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    assert "postgresql" not in res.answer and "db down" not in res.answer
    assert res.status in ("DELIVERED", "FAILED")
    if res.status == "DELIVERED":
        assert "anomaly check could not be completed" in res.answer  # the leg whose record was lost is not presented as a result
    assert _unsettled(a) == 0
    ok = {f["action_key"] for f in repo.list_findings(a, inv, turn_id=res.turn_id) if f["status"] == "COMPLETE" and f["source"] == "CFO"}
    assert {"cfo.financial_health", "cfo.strategic_briefing"} <= ok


def test_a_failure_while_saving_the_answer_leaves_no_open_run_and_no_false_success(two_tenants, app_user, monkeypatch):
    a, _ = two_tenants
    rt = runtime(Scripted({MSG_PROFIT: PROFIT}), Grounded(), registry=_stand_in_registry())
    ctx = ctx_for(a, user_id=app_user)
    inv = start(ctx, rt)
    real = repo.append_message

    def no_ceo_message(tenant, inv_id, **kw):
        if kw.get("role") == "CEO":
            raise RuntimeError("write failed")
        return real(tenant, inv_id, **kw)

    monkeypatch.setattr(repo, "append_message", no_ceo_message)
    try:
        res = orchestrator.run_turn(ctx, rt, inv, MSG_PROFIT)
    except Exception as exc:  # noqa: BLE001
        res = exc
    # whichever way it surfaces, the seller's question is stored once, no CEO answer was invented, and nothing is left open
    msgs = repo.list_messages(a, inv)
    assert [m["role"] for m in msgs] == ["USER"]
    assert _unsettled(a) == 0, "an open (RUNNING) run was left behind when the answer could not be saved"
    if not isinstance(res, Exception):
        assert res.status != "DELIVERED"


# ------------------------------------------------------------------------------------------------ concurrent turns stay isolated
def test_simultaneous_turns_across_tenants_and_investigations_never_share_messages_acks_or_runs(two_tenants, app_user, health_config):
    a, b = two_tenants
    advisory = '{"route":"ADVISORY","route_key":null,"slots":{},"needs_agent":null,"clarify_for":null}'
    plan = {f"question {t} {n}": advisory for t in "ab" for n in (1, 2)}
    plan["My business name is Zyquora Traders"] = advisory
    cls = Scripted(plan)
    rt = runtime(cls, Grounded(), registry=_stand_in_registry())
    from backend.auth.permissions import OWNER_ROLE

    ctx = {t: ctx_for(t, user_id=app_user) for t in (a, b)}
    invs = {(t, n): start(ctx[t], rt) for t in (a, b) for n in (1, 2)}
    out: dict = {}
    errors: list = []

    def go(t, n, text):
        try:
            out[(t, n)] = orchestrator.run_turn(ctx[t], rt, invs[(t, n)], text)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    jobs = [(a, 1, "My business name is Zyquora Traders"), (a, 2, "question a 2"), (b, 1, "question b 1"), (b, 2, "question b 2")]
    threads = [threading.Thread(target=go, args=j) for j in jobs]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert not errors
    # the acknowledgement of what tenant A just told us appears only in A's own turn
    assert "Zyquora" in out[(a, 1)].answer or "Noted" in out[(a, 1)].answer
    for key in ((a, 2), (b, 1), (b, 2)):
        assert "Zyquora" not in out[key].answer and "remember" not in out[key].answer.lower()
    for (t, n), inv in invs.items():
        users = [m["content"] for m in repo.list_messages(t, inv) if m["role"] == "USER"]
        assert len(users) == 1 and users[0] == dict(zip([(x, y) for x, y, _ in jobs], [j[2] for j in jobs]))[(t, n)]
    other = {a: b, b: a}
    for (t, n), inv in invs.items():
        assert repo.get_investigation(other[t], inv) is None
    assert _unsettled(a) == 0 and _unsettled(b) == 0
