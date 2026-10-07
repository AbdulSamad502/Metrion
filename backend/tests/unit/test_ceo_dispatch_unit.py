"""The CEO choke point's decision logic, with every write captured in memory (spec §6.15 R1/R2/R5/R6/R13/R14, AC7, AC11, AC22, AC31).

The deterministic invariants here are exact-match tests, not evals: the permission matrix, registry closure, attachment,
verdict uniformity and slot strictness.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, INVESTIGATION_VIEW, RESEARCH_NICHE_RUN
from backend.ceo.contract import AgentCode, Denial, InvalidSlots, LegStatus, TurnDenied, UnregisteredAction
from backend.ceo.dispatch import dispatch, open_turn
from tests.unit.ceo_fakes import NOW, CHAT_KEYS, Verdict, owner, partner, registry_of, runlog, spec  # noqa: F401 (runlog is a fixture)

SLOTS = {"period": "2026-09"}


def _turn(ctx, **kw):
    return open_turn(ctx, now=NOW, **kw)


# ------------------------------------------------------------------------------------------------ open_turn
def test_open_turn_requires_a_tenant_context():
    from tests.unit.ceo_fakes import make_ctx

    ctx = make_ctx()
    object.__setattr__(ctx, "tenant_id", None)
    with pytest.raises(ValueError):
        open_turn(ctx)


def test_open_turn_without_agent_ceo_is_denied_and_logged(runlog):
    ctx = partner(AGENT_CFO)
    with pytest.raises(TurnDenied) as exc:
        _turn(ctx)
    assert exc.value.kind is Denial.PERMISSION
    [row] = runlog.inserted
    assert row["agent_id"] == "CEO" and row["status"] == "DENIED" and row["permission_check"] == f"DENIED:{AGENT_CEO}"
    assert row["parent_run_id"] is None


def test_open_turn_inside_an_investigation_needs_investigation_view(runlog):
    ctx = partner(AGENT_CEO)
    with pytest.raises(TurnDenied) as exc:
        _turn(ctx, investigation_id=uuid.uuid4())
    assert INVESTIGATION_VIEW in exc.value.reason


def test_open_turn_cap_exhausted_is_denied_before_any_leg(runlog, monkeypatch):
    from backend.ceo import dispatch as module

    monkeypatch.setattr(module, "resolve_ceo_entitlement", lambda tenant_id, occurred_at=None: Verdict(False, "OVER_CAP", "ceo.chat_turn", "OVER_CAP"))
    with pytest.raises(TurnDenied) as exc:
        _turn(partner(*CHAT_KEYS))
    assert exc.value.kind is Denial.ENTITLEMENT
    [row] = runlog.inserted
    assert row["status"] == "DENIED" and row["entitlement_check"] == "DENIED:ceo.chat_turn"


def test_open_turn_records_an_honest_entitlement_basis(runlog):
    turn = _turn(partner(*CHAT_KEYS))
    [row] = runlog.inserted
    assert row["entitlement_check"] == "NO_CAP_CONFIGURED" and row["status"] == "RUNNING" and row["trigger_type"] == "CONVERSATIONAL"
    assert row["inherit_parent"] is False and turn.anchor_run_id == row["id"]


def test_system_turn_consumes_no_seller_unit_and_never_checks_the_cap(runlog, monkeypatch):
    from backend.ceo import dispatch as module

    def boom(*a, **k):
        raise AssertionError("a SYSTEM turn must not evaluate the seller conversation cap")

    monkeypatch.setattr(module, "resolve_ceo_entitlement", boom)
    _turn(partner(AGENT_CEO), trigger_type="SYSTEM")
    assert runlog.inserted[0]["entitlement_check"] == "NOT_APPLICABLE"


def test_a_turn_cannot_be_a_direct_run(runlog):
    with pytest.raises(ValueError):
        _turn(partner(*CHAT_KEYS), trigger_type="DIRECT")


# ------------------------------------------------------------------------------------------------ registry closure
def test_an_unregistered_key_is_never_executed(runlog):
    turn = _turn(partner(*CHAT_KEYS))
    with pytest.raises(UnregisteredAction):
        dispatch(turn, "cfo.drop_all_tables", {}, registry=registry_of(spec()), attached=frozenset({"CFO"}))
    assert len(runlog.inserted) == 1  # only the anchor: nothing was attempted


# ------------------------------------------------------------------------------------------------ permission matrix (R2)
@pytest.mark.parametrize(
    "keys, missing",
    [
        ((AGENT_CFO,), AGENT_CEO),  # agent.cfo without agent.ceo (auth.md T8b: direct paths only, no conversational)
        ((AGENT_CEO,), AGENT_CFO),  # agent.ceo without agent.cfo (T8e)
        ((), AGENT_CEO),
    ],
)
def test_missing_agent_key_is_denied_with_the_failing_key_named(runlog, keys, missing):
    turn = _turn(partner(*CHAT_KEYS))  # the turn itself is allowed to open ...
    turn.ctx = partner(*keys, tenant_id=turn.ctx.tenant_id)  # ... the leg is then judged against the grid under test
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(spec(invoke=lambda *a: pytest.fail("must not run"))), attached=frozenset({"CFO"}), now=NOW)
    assert leg.status is LegStatus.DENIED and leg.denial is Denial.PERMISSION
    child = [r for r in runlog.inserted if r["trigger_ref"] == "cfo.test_read"][0]
    assert child["status"] == "DENIED" and child["permission_check"] == f"DENIED:{missing}"
    assert child["parent_run_id"] == turn.anchor_run_id and child["entitlement_check"] == "NOT_EVALUATED"


def test_registry_extra_permission_is_enforced(runlog):
    s = spec("pi.discover", agent=AgentCode.PI, source="PI", required_permissions=(RESEARCH_NICHE_RUN,), invoke=lambda *a: pytest.fail("must not run"))
    turn = _turn(partner(*CHAT_KEYS, "agent.pi"))
    leg = dispatch(turn, "pi.discover", SLOTS, registry=registry_of(s), attached=frozenset({"PI"}), now=NOW)
    assert leg.denial is Denial.PERMISSION and "research.niche_run" in (leg.reason or "")


def test_owner_passes_the_whole_chain(runlog):
    turn = _turn(owner())
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(spec()), attached=frozenset({"CFO"}), now=NOW)
    assert leg.status is LegStatus.COMPLETE


# ------------------------------------------------------------------------------------------------ attachment (R13)
def test_a_detached_agent_is_refused_even_for_an_owner(runlog):
    turn = _turn(owner())
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(spec(invoke=lambda *a: pytest.fail("must not run"))), attached=frozenset({"CI"}), now=NOW)
    assert leg.status is LegStatus.DENIED and leg.denial is Denial.NOT_ATTACHED
    child = [r for r in runlog.inserted if r["trigger_ref"] == "cfo.test_read"][0]
    assert child["status"] == "DENIED" and "not attached" in child["error_reason"]


def test_attachment_unknown_fails_closed(runlog):
    runlog.attached = frozenset()
    turn = _turn(owner(), investigation_id=uuid.uuid4())
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(spec(invoke=lambda *a: pytest.fail("must not run"))), now=NOW)
    assert leg.denial is Denial.NOT_ATTACHED


def test_the_shared_gst_service_has_no_attachment(runlog):
    s = spec("service.gst_lookup", agent=None, source="GST_LOOKUP")
    turn = _turn(owner())
    assert dispatch(turn, "service.gst_lookup", SLOTS, registry=registry_of(s), attached=frozenset(), now=NOW).status is LegStatus.COMPLETE


# ------------------------------------------------------------------------------------------------ entitlement (R2, R6)
def test_entitlement_refusal_is_denied_not_failed(runlog):
    s = spec(entitlement=lambda tenant_id, now: Verdict(False, "OVER_CAP", "cfo.test"), invoke=lambda *a: pytest.fail("must not run"))
    turn = _turn(owner())
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(s), attached=frozenset({"CFO"}), now=NOW)
    assert leg.status is LegStatus.NOT_ENTITLED and leg.denial is Denial.ENTITLEMENT
    child = [r for r in runlog.inserted if r["trigger_ref"] == "cfo.test_read"][0]
    assert child["status"] == "DENIED" and child["entitlement_check"] == "DENIED:cfo.test"  # R6: never FAILED


def test_the_specialists_own_402_is_also_denied(runlog):
    def refuse(slots, ctx, leg):
        raise HTTPException(status_code=402, detail="over cap")

    turn = _turn(owner())
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(spec(invoke=refuse)), attached=frozenset({"CFO"}), now=NOW)
    assert leg.status is LegStatus.NOT_ENTITLED
    assert [r for r in runlog.finished if r.get("status") == "DENIED"], "the choke point's RUNNING row must finish DENIED"


# ------------------------------------------------------------------------------------------------ slots (R14)
@pytest.mark.parametrize("bad", [{"period": "x", "tenant_id": str(uuid.uuid4())}, {"period": "x", "tenantId": "t"}, {"period": "x", "role": "OWNER"},
                                 {"period": "x", "permissions": {"agent.cfo": True}}, {"period": "x", "surprise": 1}, {"period": "x", "requested_by": "u"}])
def test_undeclared_or_identity_slots_are_refused_before_any_leg_row(runlog, bad):
    turn = _turn(owner())
    before = len(runlog.inserted)
    with pytest.raises(InvalidSlots):
        dispatch(turn, "cfo.test_read", bad, registry=registry_of(spec(invoke=lambda *a: pytest.fail("must not run"))), attached=frozenset({"CFO"}), now=NOW)
    assert len(runlog.inserted) == before


def test_wrong_slot_type_is_a_request_error_not_a_crash(runlog):
    turn = _turn(owner())
    with pytest.raises(InvalidSlots):
        dispatch(turn, "cfo.test_read", {"period": ["not", "a", "string"]}, registry=registry_of(spec()), attached=frozenset({"CFO"}), now=NOW)


def test_fixed_params_override_the_callers_value(runlog):
    seen = {}

    def invoke(slots, ctx, leg):
        seen["include_narration"] = slots.include_narration
        return {"ok": True}

    s = spec(invoke=invoke, fixed_params={"include_narration": False})
    turn = _turn(owner())
    dispatch(turn, "cfo.test_read", {"period": "p", "include_narration": True}, registry=registry_of(s), attached=frozenset({"CFO"}), now=NOW)
    assert seen["include_narration"] is False  # the CEO composes; the specialist must not narrate twice (§6.4)


# ------------------------------------------------------------------------------------------------ audit shape (R5, AC31)
def test_a_successful_leg_is_one_child_row_with_refs(runlog):
    ref = uuid.uuid4()
    s = spec(invoke=lambda slots, ctx, leg: {"engineResultRef": str(ref), "dataRequestId": None})
    turn = _turn(owner())
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(s), attached=frozenset({"CFO"}), now=NOW)
    children = [r for r in runlog.inserted if r["parent_run_id"] == turn.anchor_run_id]
    assert len(children) == 1 and children[0]["agent_id"] == "CFO" and children[0]["trigger_type"] == "CONVERSATIONAL"
    assert leg.status is LegStatus.COMPLETE and [r.id for r in leg.figure_refs] == [ref]
    done = [f for f in runlog.finished if f["id"] == leg.agent_run_id][0]
    assert done["status"] == "COMPLETE" and done["output_refs"] == [{"kind": "ENGINE_RESULT", "id": str(ref)}]


def test_a_specialist_that_writes_its_own_row_gets_no_duplicate_and_inherits_the_parent(runlog):
    from backend.repositories import agent_run_repo

    def own_row(slots, ctx, leg):
        assert leg.leg_run_id is None
        agent_run_repo.insert_run(ctx.tenant_id, agent_id="CMO", trigger_type="DIRECT", trigger_ref="cmo.test", requested_by=ctx.app_user_id,
                                  permission_check="PASS", entitlement_check="PASS", status="COMPLETE", started_at=NOW)
        return {"generationId": str(uuid.uuid4())}

    s = spec("cmo.test", agent=AgentCode.CMO, source="CMO", invoke=own_row, writes_own_run=True)
    turn = _turn(owner())
    leg = dispatch(turn, "cmo.test", SLOTS, registry=registry_of(s), attached=frozenset({"CMO"}), now=NOW)
    cmo_rows = [r for r in runlog.inserted if r["agent_id"] == "CMO"]
    assert len(cmo_rows) == 1 and cmo_rows[0]["parent_run_id"] == turn.anchor_run_id  # linked via parent_run_scope, no duplicate
    assert leg.agent_run_id is None and leg.status is LegStatus.COMPLETE


def test_parent_scope_never_leaks_outside_a_leg(runlog):
    from backend.repositories import agent_run_repo

    turn = _turn(owner())
    dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(spec()), attached=frozenset({"CFO"}), now=NOW)
    assert agent_run_repo.CURRENT_PARENT_RUN_ID.get() is None


def test_partial_payload_marks_the_leg_partial(runlog):
    s = spec(invoke=lambda *a: {"dataRequestId": str(uuid.uuid4())})
    turn = _turn(owner())
    assert dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(s), attached=frozenset({"CFO"}), now=NOW).status is LegStatus.PARTIAL


def test_unexpected_failure_does_not_leak_internals(runlog):
    def boom(*a):
        raise RuntimeError("password=hunter2 at /srv/internal/secret.py")

    turn = _turn(owner())
    leg = dispatch(turn, "cfo.test_read", SLOTS, registry=registry_of(spec(invoke=boom)), attached=frozenset({"CFO"}), now=NOW)
    assert leg.status is LegStatus.FAILED and "hunter2" not in (leg.reason or "") and "secret" not in (leg.reason or "")
    assert all("hunter2" not in str(r.get("error_reason")) for r in runlog.finished)


def test_an_unwired_action_refuses_and_says_so(runlog):
    s = spec("cfo.gst_lookup", invoke=None, not_wired_reason="needs B4")
    turn = _turn(owner())
    leg = dispatch(turn, "cfo.gst_lookup", SLOTS, registry=registry_of(s), attached=frozenset({"CFO"}), now=NOW)
    assert leg.status is LegStatus.UNAVAILABLE and leg.denial is Denial.NOT_WIRED
    assert [r for r in runlog.inserted if r["trigger_ref"] == "cfo.gst_lookup"][0]["status"] == "FAILED"


def test_turn_status_derivation(runlog):
    turn = _turn(owner())
    reg = registry_of(spec("a.ok", agent=None, source="GST_LOOKUP"), spec("b.nope", entitlement=lambda t, n: Verdict(False)))
    dispatch(turn, "a.ok", SLOTS, registry=reg, attached=frozenset({"CFO"}), now=NOW)
    dispatch(turn, "b.nope", SLOTS, registry=reg, attached=frozenset({"CFO"}), now=NOW)
    assert turn.derive_status() == "PARTIAL"
    turn.close(status=turn.derive_status(), now=NOW)
    anchor = [f for f in runlog.finished if f["id"] == turn.anchor_run_id][0]
    assert anchor["status"] == "PARTIAL" and anchor["output_refs"]


@pytest.mark.parametrize("name", ["tenant_id", "role", "permissions", "permission_check", "requested_by"])
def test_a_slot_model_that_declares_an_identity_field_still_cannot_receive_one(runlog, name):
    """Defence in depth (spec §6.11, R14): even a model that — by mistake — declares `tenant_id` or `permissions` must never be fed one
    from a caller. The reserved-name guard is independent of the model's own strictness."""
    from pydantic import create_model

    leaky = create_model("Leaky", period=(str, ...), **{name: (str | None, None)})
    turn = _turn(owner())
    with pytest.raises(InvalidSlots):
        dispatch(turn, "cfo.test_read", {"period": "p", name: "x"}, registry=registry_of(spec(slot_model=leaky, invoke=lambda *a: pytest.fail("must not run"))),
                 attached=frozenset({"CFO"}), now=NOW)
