"""The CEO conversation unit: one pure decision, taken once when a turn is finalised (approval prerequisite R2, owner decisions Q-S0-3, Q-R1, Q-R6, F6, F7).

INVARIANT: a CEO turn with any failed required leg consumes no CEO unit, regardless of optional-leg success. A delivered answer alone does not
establish successful execution.

Nothing here calls anything or touches the database: it classifies already-known leg results. The decision is stored ONCE on the turn
(`investigation_turn.safety_result.billing`) by `investigation_repo.finalise_turn` (first writer wins), and only the call that finalised the
turn may write the usage event (`entitlement.meter_ceo_turn`, key `ceo:turn:<id>`, idempotent).

Leg vocabulary
* failed          = FAILED, UNAVAILABLE, DENIED, NOT_ENTITLED, or planned-but-never-finished (a deadline miss).
* pending input   = a leg that finished PARTIAL because its payload carries a data request (`dataRequestId`): the seller still has to supply
                    something. That is not a failed execution and not a successful completion (F6): a required leg in this state means NO unit.
* succeeded       = COMPLETE, or PARTIAL for any other reason (`partialReason`: a result with named gaps).

Outcomes (stored with the decision and shown to the seller): SUCCEEDED, PARTIAL (every required leg succeeded but an optional one did not, or a
leg has named gaps), FAILED, PENDING_INPUT, DECLINED (an out-of-scope explanation), and the turn status itself for turns that were not delivered.
Optional results are still returned with the outcome clearly represented.

Policies preserved on purpose (documented here and pinned by tests, owner decisions F2/F7): a successfully DELIVERED `OUT_OF_SCOPE` explanation is
chargeable, and so is a successfully delivered informational answer from saved data, including "not available yet" (no legs are involved). Neither is
a failed execution, and neither is affected by the required-leg rule.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from backend.ceo.contract import LegResult, LegStatus

RULE_VERSION = 2  # matches the accounting cut-over code CEO_UNIT_RULE_2

REASON_NOT_DELIVERED = "TURN_NOT_DELIVERED"
REASON_OUT_OF_SCOPE = "OUT_OF_SCOPE_DELIVERED"
REASON_NO_LEGS = "NO_LEGS"
REASON_REQUIRED_FAILED = "REQUIRED_LEG_FAILED"
REASON_REQUIRED_PENDING = "REQUIRED_LEG_PENDING_INPUT"
REASON_ALL_REQUIRED_OK = "ALL_REQUIRED_LEGS_SUCCEEDED"

_FAILED_STATUSES = frozenset({LegStatus.FAILED, LegStatus.UNAVAILABLE, LegStatus.DENIED, LegStatus.NOT_ENTITLED})


@dataclass(frozen=True, slots=True)
class UnitDecision:
    due: bool
    reason: str
    outcome: str

    def to_json(self) -> dict[str, object]:
        return {"rule": RULE_VERSION, "ceoUnit": "DUE" if self.due else "NOT_DUE", "reason": self.reason, "outcome": self.outcome}


def _pending_input(leg: LegResult) -> bool:
    return leg.status is LegStatus.PARTIAL and bool(leg.payload and leg.payload.get("dataRequestId"))


def unit_decision(
    *, status: str, route: str, planned_leg_keys: Sequence[str] = (), required_keys: Collection[str] = (), legs: Sequence[LegResult] = ()
) -> UnitDecision:
    if status != "DELIVERED":
        return UnitDecision(False, REASON_NOT_DELIVERED, status)
    if route == "OUT_OF_SCOPE":
        return UnitDecision(True, REASON_OUT_OF_SCOPE, "DECLINED")
    if not planned_leg_keys:
        return UnitDecision(True, REASON_NO_LEGS, "SUCCEEDED")
    by_key = {leg.action_key: leg for leg in legs}
    required = set(required_keys) or set(planned_leg_keys)  # a plan with no required leg treats every leg as required

    def failed(key: str) -> bool:
        leg = by_key.get(key)
        return leg is None or leg.status in _FAILED_STATUSES

    if any(failed(k) for k in required):
        return UnitDecision(False, REASON_REQUIRED_FAILED, "FAILED")
    if any(_pending_input(by_key[k]) for k in required):
        return UnitDecision(False, REASON_REQUIRED_PENDING, "PENDING_INPUT")
    clean = all(
        (leg := by_key.get(k)) is not None and leg.status is LegStatus.COMPLETE and not _pending_input(leg) for k in planned_leg_keys
    )
    return UnitDecision(True, REASON_ALL_REQUIRED_OK, "SUCCEEDED" if clean else "PARTIAL")
