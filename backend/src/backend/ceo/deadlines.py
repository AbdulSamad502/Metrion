"""The hard leg deadline: what happens to a leg that is still running long after its turn answered without it.

Three different situations must never be confused:

* a SLOW leg in a live process (the soft deadline `CEO_LEG_TIMEOUT_SECONDS` passed; the turn answered "still running"; the leg may yet finish and its finding lands as before);
* an ABANDONED turn whose process died (`recovery.settle_abandoned_locked`: ownership, proven by the free turn lock, no age involved);
* a leg that has now run longer than the HARD deadline `CEO_LEG_ABANDON_SECONDS` (this module). Python cannot cancel a thread, so the leg may STILL be executing and may already have had its
  effect; all this module can truthfully do is stop the system from waiting for it and say so.

Outcome of a leg past the hard deadline (the agent_run row ends FAILED with a distinct reason; no schema is involved):

* `TIMED_OUT_REPEATABLE`: the action only reads saved data or computes a deterministic result (no external call, no meter, no seller choice recorded). Nothing outside Metrion can have
  happened, so the seller is told asking again is safe.
* `TIMED_OUT_UNCERTAIN`: the action calls an outside service, spends a meter, generates a metered artefact or records a seller choice. It may still be running and may already have taken
  effect. The seller is told exactly that; it is NEVER re-run automatically, and the outcome is never described as "did not happen". An action this module cannot classify is treated as
  uncertain.

Guarantees (tested): only a leg whose row is still QUEUED/RUNNING is touched, by the same guarded write recovery uses, so a late completion can never overwrite the timeout state (and the
timeout can never overwrite a completion); two settlers race to exactly one winner; a repeated pass finds nothing; legs that completed and the findings they wrote are never rewritten; the
caller must hold the investigation's turn lock, which proves no live turn can be waiting on these legs.

Nothing is re-run here and no model is called."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from backend import config
from backend.ceo.contract import ActionSpec, Effect
from backend.ceo.effects import External
from backend.repositories import agent_run_repo, investigation_repo as repo

if TYPE_CHECKING:
    from backend.ceo.registry import ActionRegistry

logger = logging.getLogger(__name__)

REPEATABLE_REASON = "TIMED_OUT_REPEATABLE: did not finish within the time limit; it only reads or computes saved data, so asking again is safe"
UNCERTAIN_REASON = "TIMED_OUT_UNCERTAIN: did not finish within the time limit; it may still be running or may already have taken effect, and it was not run again"


class LegClass(str, Enum):
    REPEATABLE = "REPEATABLE"
    UNCERTAIN = "UNCERTAIN"


def classify(spec: ActionSpec | None) -> LegClass:
    """REPEATABLE only when the registry says the action has no effect outside Metrion: it reads or computes, calls nothing external, spends no meter and records no seller choice."""
    if spec is None or spec.effects is None:
        return LegClass.UNCERTAIN  # unknown or unclassified: never assume it is harmless
    if spec.effect in (Effect.READ, Effect.COMPUTE_PERSIST) and spec.effects.external is External.NONE and not spec.effects.meters:
        return LegClass.REPEATABLE
    return LegClass.UNCERTAIN


def seller_note(label: str, kind: LegClass) -> str:
    if kind is LegClass.REPEATABLE:
        return f"{label} did not finish within the time limit. It only reads or works out saved figures, so it is safe to ask again."
    return (f"{label} did not finish within the time limit. It may still be running, or it may already have done its work, so I have not run it again. "
            "Check this investigation's findings before asking again.")


@dataclass(frozen=True, slots=True)
class OverdueReport:
    repeatable: int = 0
    uncertain: int = 0

    @property
    def settled(self) -> int:
        return self.repeatable + self.uncertain

    def __add__(self, other: "OverdueReport") -> "OverdueReport":
        return OverdueReport(self.repeatable + other.repeatable, self.uncertain + other.uncertain)


def effective_abandon_seconds() -> int | None:
    """The hard deadline in force: the configured value, never shorter than the soft deadline (a leg is not abandoned before the turn has finished waiting for it)."""
    hard = config.ceo_leg_abandon_seconds()
    if hard is None:
        return None
    soft = config.ceo_leg_timeout_seconds()
    return max(hard, soft) if soft is not None else hard


def settle_overdue_legs_locked(
    tenant: UUID, investigation_id: UUID, *, now: datetime | None = None, abandon_seconds: int | None = None, registry: "ActionRegistry | None" = None,
) -> OverdueReport:
    """Settles every leg of this investigation that is still open past the hard deadline. THE CALLER MUST HOLD the investigation's turn lock. With no deadline configured nothing is done."""
    seconds = abandon_seconds if abandon_seconds is not None else effective_abandon_seconds()
    if seconds is None:
        return OverdueReport()
    if registry is None:
        from backend.ceo.registry import get_registry

        registry = get_registry()
    at = now or datetime.now(timezone.utc)
    report = OverdueReport()
    for leg in repo.list_late_legs(tenant, investigation_id):
        if leg["started_at"] is None or leg["started_at"] + timedelta(seconds=seconds) > at:
            continue  # still inside the hard deadline: a slow leg in a live process is left alone
        key = str(leg["trigger_ref"] or "")
        spec = next((s for s in registry.specs() if s.key == key), None)
        kind = classify(spec)
        reason = REPEATABLE_REASON if kind is LegClass.REPEATABLE else UNCERTAIN_REASON
        if not agent_run_repo.finish_run_if_unfinished(tenant, leg["id"], status="FAILED", error_reason=reason, finished_at=at):
            continue  # it finished (or another settler won) between the read and the write: nothing to do
        report += OverdueReport(1, 0) if kind is LegClass.REPEATABLE else OverdueReport(0, 1)
        logger.warning("settled an overdue CEO leg as %s (tenant=%s investigation=%s run=%s action=%s)", kind.value, tenant, investigation_id, leg["id"], key or "?")
        _tell_the_seller(tenant, investigation_id, leg, spec, kind, reason, at)
    return report


def _tell_the_seller(tenant: UUID, investigation_id: UUID, leg: dict[str, Any], spec: ActionSpec | None, kind: LegClass, reason: str, at: datetime) -> None:
    """Records the outcome where the seller reads it: a finding (so the timeline shows the leg) and one plain note. Best effort: the row is already settled."""
    try:
        turn = repo.get_turn_for_run(tenant, leg["parent_run_id"])
        from backend.ceo.evidence import LEG_LABELS  # the same plain names the answer uses

        label = LEG_LABELS.get(str(leg["trigger_ref"] or ""), "A step of this request")
        if turn is not None:
            repo.insert_finding(
                tenant, investigation_id, turn_id=turn["id"], source=spec.source if spec is not None else str(leg["agent_id"]), action_key=str(leg["trigger_ref"] or "unknown"),
                status="FAILED", agent_run_id=leg["id"], figure_refs=[], gap_reason=reason, now=at,
            )
        repo.append_message(tenant, investigation_id, role="SYSTEM", kind="SYSTEM_NOTE", content=seller_note(label, kind), agent_run_id=leg["id"], turn_id=turn["id"] if turn else None, now=at)
    except Exception:  # noqa: BLE001 — the settle itself stands; a note that could not be written is logged
        logger.exception("could not record the timed-out leg for the seller (tenant=%s run=%s)", tenant, leg.get("id"))
