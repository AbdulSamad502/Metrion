"""S1 (approval workflow): the approval gate. A pure function over action keys and the R1 metadata. S1 shipped it observe-only; D-8 wired it into the two chat enforcement points (see below).

These tests do NOT claim that any current chat path is compliant with the approval policy: the last test pins the paths that are NOT (see
docs/planning/ceo-approval-s1-readiness.md, F-6 / D-8)."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.ceo import approval_gate as gate
from backend.ceo.approval_gate import evaluate, evaluate_playbook, gate_leg, plan_required
from backend.ceo.effects import ACTION_EFFECTS, ActionEffects, External
from backend.ceo.input_session import SESSIONS
from backend.ceo.plans import ACTIONS, PLAYBOOKS, GST_KEY, GST_ROUTE_KEYS, LegPlan, Playbook
from backend.ceo.registry import get_registry

NONE_ACTION = "cfo.pricing"  # classified NONE by R1
METERED_ACTION = "cmo.generate_hashtags"  # metered by R1
SELLER_OUT_ACTION = "pi.discover"  # SELLER_DATA_OUT + metered


def _playbook(*legs: tuple[str, bool]) -> Playbook:
    return Playbook("TEST", "synthetic", (), tuple(LegPlan(k, r) for k, r in legs))


# ------------------------------------------------------------------------------------------------ the 36 registered actions
def test_the_gate_agrees_with_the_registry_metadata_for_every_registered_action():
    specs = get_registry().specs()
    assert len(specs) == 36
    for spec in specs:
        assert spec.effects is not None, spec.key
        decision = gate_leg(spec.key)
        assert decision.requires_approval == spec.effects.requires_approval, spec.key
        assert (decision.reason is not None) == decision.requires_approval, spec.key


def test_every_metered_or_seller_data_out_registered_action_needs_approval_with_its_own_reason():
    for spec in get_registry().specs():
        fx = spec.effects
        assert fx is not None
        leg = gate_leg(spec.key)
        if fx.meters:
            assert leg.requires_approval and leg.reason == gate.METERED, spec.key
        elif fx.external is External.SELLER_DATA_OUT:
            assert leg.requires_approval and leg.reason == gate.SELLER_DATA_OUT, spec.key
        if leg.requires_approval is False:
            assert not fx.meters and fx.external is not External.SELLER_DATA_OUT and not fx.force_approval, spec.key


def test_a_mis_declared_entry_cannot_hide_a_metered_or_seller_data_out_action():
    class Lies:  # claims no approval while declaring meters / seller data leaving Metrion
        def __init__(self, meters, external):
            self.meters, self.external, self.force_approval, self.requires_approval = meters, external, False, False

    table = {"x.metered": Lies(("x.meter",), External.NONE), "x.out": Lies((), External.SELLER_DATA_OUT)}
    assert gate_leg("x.metered", effects=table).reason == gate.METERED
    assert gate_leg("x.out", effects=table).reason == gate.SELLER_DATA_OUT
    assert plan_required(["x.metered"], effects=table) and plan_required(["x.out"], effects=table)


def test_a_forced_flag_only_adds_approval():
    table = {"x.forced": ActionEffects(force_approval=True), "x.plain": ActionEffects()}
    assert gate_leg("x.forced", effects=table).reason == gate.FORCED
    assert gate_leg("x.plain", effects=table).requires_approval is False


def test_gst_is_one_action_to_the_model_and_gated_iff_a_route_is():
    assert GST_KEY in {"gst_lookup"} and set(GST_ROUTE_KEYS) <= set(ACTION_EFFECTS)
    assert gate_leg(GST_KEY).requires_approval is False  # both routes are PUBLIC_FETCH + model: not approval-gated (Q-S0-2)
    table = {**ACTION_EFFECTS, GST_ROUTE_KEYS[1]: ActionEffects(meters=("service.gst_lookup",))}
    assert gate_leg(GST_KEY, effects=table).requires_approval is True


# ------------------------------------------------------------------------------------------------ playbooks and turns
def test_a_turn_with_no_legs_needs_no_plan_and_nothing_is_flagged():
    d = evaluate(())
    assert d.plan_required is False and d.legs == () and d.flagged == ()


def test_the_real_decision_playbooks_are_not_gated_today_and_there_is_no_blanket_exemption():
    assert PLAYBOOKS
    for pid, pb in PLAYBOOKS.items():
        d = evaluate_playbook(pb)
        assert d.plan_required is any(ACTION_EFFECTS[leg.key].requires_approval for leg in pb.legs if leg.key in ACTION_EFFECTS), pid
        assert d.plan_required is False, f"{pid}: if this changes, a leg became approval-gated: review the playbook (C11)"
    # the same rule gates a playbook the moment one leg is flagged, whatever the playbook is called
    assert evaluate_playbook(_playbook(("ci.request_price_scenario", True), ("cfo.pricing", True))).plan_required is False


def test_one_gated_leg_gates_the_playbook_even_when_that_leg_is_optional():
    d = evaluate_playbook(_playbook((NONE_ACTION, True), (METERED_ACTION, False), ("cfo.reconcile", True)))
    assert d.plan_required is True and d.flagged == (METERED_ACTION,)


def test_several_gated_legs_are_all_reported_in_leg_order():
    d = evaluate_playbook(_playbook((SELLER_OUT_ACTION, True), (NONE_ACTION, True), (METERED_ACTION, True), ("pi.supplier_lookup", False)))
    assert d.plan_required is True
    assert d.flagged == (SELLER_OUT_ACTION, METERED_ACTION, "pi.supplier_lookup")
    assert [leg.key for leg in d.legs] == [SELLER_OUT_ACTION, NONE_ACTION, METERED_ACTION, "pi.supplier_lookup"]


def test_only_ungated_legs_need_no_plan():
    d = evaluate(["cfo.financial_health", "cfo.anomaly_check", "cfo.strategic_briefing", GST_KEY, "pi.report", "ci.request_price_scenario"])
    assert d.plan_required is False and d.flagged == ()


# ------------------------------------------------------------------------------------------------ unknown and malformed: fail closed
@pytest.mark.parametrize("key", ["", "cfo.not_a_real_action", "CFO.PRICING", " cfo.pricing", "cfo.pricing ", "gst_lookup2"])
def test_an_unknown_action_key_needs_approval(key):
    leg = gate_leg(key)
    assert leg.requires_approval is True and leg.reason in (gate.UNKNOWN_ACTION, gate.MALFORMED)
    assert plan_required([NONE_ACTION, key]) is True


@pytest.mark.parametrize("key", [None, 7, 1.5, b"cfo.pricing", ("cfo.pricing",), object()])
def test_a_non_string_key_needs_approval(key):
    leg = gate_leg(key)
    assert leg.requires_approval is True and leg.reason == gate.MALFORMED


def test_malformed_metadata_needs_approval_and_never_raises():
    class Raises:
        meters, external, force_approval = (), External.NONE, False

        @property
        def requires_approval(self):
            raise RuntimeError("boom")

    class NotABool:
        meters, external, force_approval, requires_approval = (), External.NONE, False, "no"

    class BadMeters:
        meters, external, force_approval, requires_approval = "cmo.x", External.NONE, False, False

    class BadExternal:
        meters, external, force_approval, requires_approval = (), 42, False, False

    class Broken(dict):
        def get(self, key, default=None):
            raise RuntimeError("table unreadable")

    table = {
        "m.none": None, "m.empty": SimpleNamespace(), "m.raises": Raises(), "m.notbool": NotABool(), "m.badmeters": BadMeters(), "m.badexternal": BadExternal(),
        "m.string": "requires_approval=False",
    }
    for key in table:
        leg = gate_leg(key, effects=table)
        assert leg.requires_approval is True, key
        assert leg.reason in (gate.UNKNOWN_ACTION, gate.MALFORMED), key
    assert gate_leg("anything", effects=Broken()) == gate.LegGate("anything", True, gate.MALFORMED)


@pytest.mark.parametrize("legs", [None, "cfo.pricing", b"cfo.pricing", 5, object()])
def test_a_malformed_leg_list_needs_approval(legs):
    d = evaluate(legs)
    assert d.plan_required is True and d.legs[0].reason == gate.MALFORMED


def test_a_malformed_playbook_needs_approval():
    for bad in (None, object(), SimpleNamespace(legs=None), SimpleNamespace(legs=[SimpleNamespace()]), SimpleNamespace(legs=5)):
        assert evaluate_playbook(bad).plan_required is True


def test_the_decision_is_pure_and_repeatable():
    keys = [NONE_ACTION, METERED_ACTION]
    assert evaluate(keys) == evaluate(list(keys)) == evaluate(iter(keys))
    assert evaluate(keys).legs == (gate.LegGate(NONE_ACTION, False, None), gate.LegGate(METERED_ACTION, True, gate.METERED))


# ------------------------------------------------------------------------------------------------ where the gate is used (D-8), and that the module itself does no I/O
def test_the_gate_is_used_in_exactly_the_three_d8_places_and_the_module_does_no_io():
    """S1 shipped observe-only; D-8 then wired it into EXACTLY three places and nowhere else: the orchestrator's refusal on the decision (before any question, save or
    preview), `dispatch()`'s backstop, and the availability endpoint (`chatActions` must not advertise blocked actions). No config, billing or frontend uses it. A fourth importer is a deliberate, reviewed change."""
    src = Path(gate.__file__).resolve().parents[2]  # backend/src
    users = sorted(str(p.relative_to(src)).replace("\\", "/") for p in src.rglob("*.py") if p.name != "approval_gate.py" and re.search(r"\bapproval_gate\b", p.read_text(encoding="utf-8")))
    assert users == ["backend/api/v1/ceo.py", "backend/ceo/dispatch.py", "backend/ceo/orchestrator.py"], users
    forbidden = {"logging", "os", "sqlalchemy", "httpx", "requests", "socket", "subprocess", "datetime", "time", "backend.config"}
    imported = {m for m in re.findall(r"^(?:from|import)\s+([\w.]+)", Path(gate.__file__).read_text(encoding="utf-8"), re.M)}
    assert not (imported & forbidden), imported & forbidden


# ------------------------------------------------------------------------------------------------ the known conflict, pinned (not blessed)
CHAT_ACTIONS_NEEDING_APPROVAL_TODAY = frozenset({
    "pi.discover", "cmo.market_trends", "cmo.generate_title_sets", "cmo.generate_hashtags", "cmo.generate_description", "cmo.generate_keywords",
})
WITH_A_CONFIRMATION_CARD = frozenset({"pi.discover", "cmo.market_trends"})
WITH_NO_CONFIRMATION_STEP = CHAT_ACTIONS_NEEDING_APPROVAL_TODAY - WITH_A_CONFIRMATION_CARD


def _has_confirmation_card(action: str) -> bool:
    """A guided-input session of its own, or the follow-on session that runs it (market trends: `dr.trend_run`), has a field named `confirm`."""
    sessions = [action, "dr.trend_run"] if action == "cmo.market_trends" else [action]
    return any(f.name == "confirm" for s in sessions for f in SESSIONS.get(s, ()))


def test_regression_guard_approval_required_actions_still_offered_to_chat_and_blocked_by_d8():
    """RECORDED, NOT BLESSED (readiness F-6 / D-8; approval spec C1/C3 vs orchestration 6.35/6.40). These are the approval-required actions (metered, or seller data
    leaves Metrion) that are still defined as chat actions (`plans.ACTIONS`, with guided input sessions). Before D-8 they ran from chat after a confirmation card (two of
    them) or after the last answered question (the other four); a confirmation answer is NOT approval (C3). D-8 now refuses all six at the orchestrator and in dispatch
    (tests/integration/test_ceo_approval_blocked_chat.py); there is still no stored approval plan, so they cannot run from chat at all. If this set changes, review
    it deliberately; when S3 replaces the confirmation step with plan creation, update this test and the D-8 refusal in the same change."""
    reachable = {k for k in ACTIONS if gate_leg(k).requires_approval}
    assert reachable == CHAT_ACTIONS_NEEDING_APPROVAL_TODAY
    assert {k for k in reachable if _has_confirmation_card(k)} == WITH_A_CONFIRMATION_CARD
    assert {k for k in reachable if not _has_confirmation_card(k)} == WITH_NO_CONFIRMATION_STEP
    # they are all guided-input session actions, and no decision playbook leg is among them
    assert all(ACTIONS[k].session for k in reachable)
    assert all(not evaluate_playbook(pb).plan_required for pb in PLAYBOOKS.values())
