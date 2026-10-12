"""R2: the CEO-unit decision is a pure function. INVARIANT: any failed required leg => no unit, regardless of optional-leg success; a delivered
answer alone does not establish successful execution. Out-of-scope and informational answers keep their (documented) charge."""

from __future__ import annotations

import pytest

from backend.ceo.billing import UnitDecision, unit_decision
from backend.ceo.contract import LegResult, LegStatus


def leg(key: str, status: LegStatus, **payload) -> LegResult:
    return LegResult(key, status, payload=payload or None)


A, B, OPT = "cfo.financial_health", "cfo.reconcile", "cfo.anomaly_check"
PLANNED = [A, B, OPT]
REQUIRED = {A, B}


def decide(legs, *, planned=PLANNED, required=REQUIRED, status="DELIVERED", route="PLAYBOOK") -> UnitDecision:
    return unit_decision(status=status, route=route, planned_leg_keys=planned, required_keys=required, legs=legs)


def test_full_success_is_one_unit():
    d = decide([leg(A, LegStatus.COMPLETE), leg(B, LegStatus.COMPLETE), leg(OPT, LegStatus.COMPLETE)])
    assert (d.due, d.reason, d.outcome) == (True, "ALL_REQUIRED_LEGS_SUCCEEDED", "SUCCEEDED")


def test_an_optional_failure_after_every_required_leg_succeeded_is_one_unit_with_a_partial_outcome():
    d = decide([leg(A, LegStatus.COMPLETE), leg(B, LegStatus.COMPLETE), leg(OPT, LegStatus.FAILED)])
    assert (d.due, d.outcome) == (True, "PARTIAL")
    d = decide([leg(A, LegStatus.COMPLETE), leg(B, LegStatus.COMPLETE)])  # the optional leg never finished (deadline)
    assert (d.due, d.outcome) == (True, "PARTIAL")


def test_a_leg_with_named_gaps_is_a_partial_success_not_a_failure():
    d = decide([leg(A, LegStatus.PARTIAL, partialReason="one source down"), leg(B, LegStatus.COMPLETE), leg(OPT, LegStatus.COMPLETE)])
    assert (d.due, d.outcome) == (True, "PARTIAL")


@pytest.mark.parametrize("bad", [LegStatus.FAILED, LegStatus.UNAVAILABLE, LegStatus.DENIED, LegStatus.NOT_ENTITLED])
def test_any_failed_required_leg_means_no_unit_even_if_the_others_succeeded(bad):
    d = decide([leg(A, bad), leg(B, LegStatus.COMPLETE), leg(OPT, LegStatus.COMPLETE)])
    assert (d.due, d.reason, d.outcome) == (False, "REQUIRED_LEG_FAILED", "FAILED")
    d = decide([leg(A, LegStatus.COMPLETE), leg(B, bad), leg(OPT, LegStatus.COMPLETE)])  # one of two required legs failed
    assert d.due is False and d.outcome == "FAILED"


def test_a_required_leg_that_never_finished_is_a_failure():
    assert decide([leg(A, LegStatus.COMPLETE), leg(OPT, LegStatus.COMPLETE)]).due is False  # B missing (deadline miss)


def test_a_required_data_request_is_pending_input_not_failure_and_not_success_and_never_charged():
    d = decide([leg(A, LegStatus.PARTIAL, dataRequestId="r1"), leg(B, LegStatus.COMPLETE), leg(OPT, LegStatus.COMPLETE)])
    assert (d.due, d.reason, d.outcome) == (False, "REQUIRED_LEG_PENDING_INPUT", "PENDING_INPUT")
    d = decide([leg(A, LegStatus.FAILED), leg(B, LegStatus.PARTIAL, dataRequestId="r1")])  # failure wins over pending input
    assert d.outcome == "FAILED"


def test_an_optional_data_request_is_a_partial_success():
    d = decide([leg(A, LegStatus.COMPLETE), leg(B, LegStatus.COMPLETE), leg(OPT, LegStatus.PARTIAL, dataRequestId="r1")])
    assert (d.due, d.outcome) == (True, "PARTIAL")


def test_when_no_leg_is_required_every_planned_leg_is_treated_as_required():
    assert decide([leg(A, LegStatus.COMPLETE), leg(OPT, LegStatus.FAILED)], planned=[A, OPT], required=set()).due is False


def test_a_required_leg_failure_is_not_rescued_by_a_successful_optional_leg():
    d = decide([leg(A, LegStatus.FAILED), leg(B, LegStatus.FAILED), leg(OPT, LegStatus.COMPLETE)])
    assert d.due is False and d.reason == "REQUIRED_LEG_FAILED"


@pytest.mark.parametrize("status", ["CLARIFIED", "DENIED", "FAILED", "PLANNED"])
def test_turns_that_were_not_delivered_are_never_charged(status):
    d = unit_decision(status=status, route="PLAYBOOK", planned_leg_keys=PLANNED, required_keys=REQUIRED, legs=[leg(A, LegStatus.COMPLETE)])
    assert (d.due, d.reason, d.outcome) == (False, "TURN_NOT_DELIVERED", status)


def test_out_of_scope_delivered_is_chargeable_and_distinct_from_failed_execution():  # F2: explicit, preserved policy
    d = unit_decision(status="DELIVERED", route="OUT_OF_SCOPE")
    assert (d.due, d.reason, d.outcome) == (True, "OUT_OF_SCOPE_DELIVERED", "DECLINED")
    assert unit_decision(status="FAILED", route="OUT_OF_SCOPE").due is False  # an out-of-scope turn that failed to deliver is not charged


@pytest.mark.parametrize("route", ["BUSINESS_STATE", "ADVISORY", "SYNTHESIZE", "PLAYBOOK"])
def test_informational_answers_with_no_legs_keep_their_charge(route):  # F7: a delivered "not available yet" answer is preserved
    d = unit_decision(status="DELIVERED", route=route)
    assert (d.due, d.reason, d.outcome) == (True, "NO_LEGS", "SUCCEEDED")


def test_the_decision_serialises_for_storage_with_the_rule_version():
    assert decide([leg(A, LegStatus.COMPLETE), leg(B, LegStatus.COMPLETE), leg(OPT, LegStatus.COMPLETE)]).to_json() == {
        "rule": 2, "ceoUnit": "DUE", "reason": "ALL_REQUIRED_LEGS_SUCCEEDED", "outcome": "SUCCEEDED",
    }
