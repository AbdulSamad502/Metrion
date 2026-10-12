"""The approval gate, OBSERVE-ONLY (approval workflow S1; docs/planning/ceo-approval-s1-readiness.md §2, spec decisions C1, C11, D1).

Given the action keys a turn or playbook would run, say whether the turn would need an approval PLAN, using the R1 metadata that already exists
(`ceo/effects.py`: `ActionEffects.requires_approval`). It classifies nothing itself: the one table of what each action really does stays in `effects.py`.

What this module IS: a pure function over keys and that metadata. No database, network, configuration, logging, clock or registry construction.
What it is NOT, deliberately:
* It is imported by nothing in orchestration, chat, an API or execution. It changes no behaviour: nothing is refused, planned or run differently
  because of it. It does not make any current chat path compliant with the approval policy.
* It is not an authorization or a billing decision, and it creates no plan, hash, status or event (those are S2/S3, and approval is not enabled).

Rules (owner decisions C1, C11, D1):
* A turn or playbook needs a plan iff AT LEAST ONE leg needs approval. There is no blanket exemption for decision playbooks.
* An action with recorded meters, or one that sends seller data to a third party (`SELLER_DATA_OUT`), is NEVER reported as not needing approval, even
  if the metadata's own `requires_approval` said otherwise (a defence against a mis-declared entry, not a second classification table).
* FAIL CLOSED: an unknown action key, a non-string key, a missing entry, or metadata that is malformed (wrong type, raises when read, answers
  something other than a bool) counts as "needs approval".
* A turn with no legs (a Business State read, an advisory or informational answer) needs no plan: nothing runs.
* GST is one action to the model but two registry routes (`plans.VIRTUAL_ROUTES`); the virtual key needs approval iff either route does.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from backend.ceo.effects import ACTION_EFFECTS, ActionEffects, External
from backend.ceo.plans import VIRTUAL_ROUTES

# Why one leg needs approval. Reason codes only: nothing here is shown to a seller.
METERED = "METERED"
SELLER_DATA_OUT = "SELLER_DATA_OUT"
FORCED = "FORCED"
FLAGGED = "FLAGGED"  # the metadata's own derived `requires_approval` said so
UNKNOWN_ACTION = "UNKNOWN_ACTION"  # fail closed: not in the metadata table
MALFORMED = "MALFORMED"  # fail closed: the entry (or the key, or the leg list) could not be read as designed


@dataclass(frozen=True, slots=True)
class LegGate:
    key: str  # the key exactly as given (a non-string key is shown as its repr)
    requires_approval: bool
    reason: str | None  # None only when requires_approval is False


@dataclass(frozen=True, slots=True)
class GateDecision:
    plan_required: bool
    legs: tuple[LegGate, ...]

    @property
    def flagged(self) -> tuple[str, ...]:
        """The keys that need approval, in leg order."""
        return tuple(leg.key for leg in self.legs if leg.requires_approval)


_FAIL_CLOSED_MALFORMED = GateDecision(True, (LegGate("<malformed legs>", True, MALFORMED),))


def gate_leg(key: object, *, effects: Mapping[str, ActionEffects] = ACTION_EFFECTS) -> LegGate:
    """Does ONE action key need approval? Never raises; anything it cannot read as designed needs approval."""
    if not isinstance(key, str) or not key:
        return LegGate(repr(key), True, MALFORMED)
    if key in VIRTUAL_ROUTES:  # one action to the model, several registry routes: gated iff any route is
        parts = [gate_leg(route, effects=effects) for route in VIRTUAL_ROUTES[key]]
        first = next((p for p in parts if p.requires_approval), None)
        return LegGate(key, True, first.reason) if first is not None else LegGate(key, False, None)
    try:
        entry: Any = effects.get(key)
    except Exception:  # noqa: BLE001 - a broken mapping is a malformed table: fail closed, never propagate
        return LegGate(key, True, MALFORMED)
    if entry is None:
        return LegGate(key, True, UNKNOWN_ACTION)
    try:
        meters, external, forced = entry.meters, entry.external, entry.force_approval
        derived = entry.requires_approval
    except Exception:  # noqa: BLE001 - missing attribute, or a property that raises
        return LegGate(key, True, MALFORMED)
    if not isinstance(derived, bool) or not isinstance(forced, bool) or not isinstance(meters, (tuple, list)):
        return LegGate(key, True, MALFORMED)
    # The invariant checks read the declared facts directly, so a mis-declared `requires_approval` can never hide a metered or seller-data-out action.
    if meters:
        return LegGate(key, True, METERED)
    if external is External.SELLER_DATA_OUT or external == External.SELLER_DATA_OUT.value:
        return LegGate(key, True, SELLER_DATA_OUT)
    if forced:
        return LegGate(key, True, FORCED)
    if derived:
        return LegGate(key, True, FLAGGED)
    if not isinstance(external, (External, str)):
        return LegGate(key, True, MALFORMED)
    return LegGate(key, False, None)


def evaluate(leg_keys: Iterable[object] | None, *, effects: Mapping[str, ActionEffects] = ACTION_EFFECTS) -> GateDecision:
    """The decision for a turn that would run these legs. `None` or a value that is not an iterable of keys is malformed and fails closed."""
    if leg_keys is None or isinstance(leg_keys, (str, bytes)):
        return _FAIL_CLOSED_MALFORMED
    try:
        keys = tuple(leg_keys)
    except TypeError:
        return _FAIL_CLOSED_MALFORMED
    legs = tuple(gate_leg(k, effects=effects) for k in keys)
    return GateDecision(any(leg.requires_approval for leg in legs), legs)


def plan_required(leg_keys: Iterable[object] | None, *, effects: Mapping[str, ActionEffects] = ACTION_EFFECTS) -> bool:
    return evaluate(leg_keys, effects=effects).plan_required


def evaluate_playbook(playbook: object, *, effects: Mapping[str, ActionEffects] = ACTION_EFFECTS) -> GateDecision:
    """The decision for a decision playbook (`plans.Playbook`): gated iff at least one of its legs is (C11). An object that does not carry a
    readable `legs` tuple of leg plans with a `key` is malformed and fails closed."""
    try:
        keys = [leg.key for leg in playbook.legs]  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return _FAIL_CLOSED_MALFORMED
    return evaluate(keys, effects=effects)
