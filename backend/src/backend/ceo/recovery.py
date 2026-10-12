"""Settling CEO turns whose process died (hardening Fix 4).

Ownership, not age. A turn holds its investigation's Postgres advisory lock (`turn_lock`) for its whole life, on a dedicated session that ends when the process does. So:

* a RUNNING conversational CEO run whose investigation lock is HELD belongs to a live turn, however long it has been running: it is never touched;
* a RUNNING conversational CEO run whose investigation lock is FREE has no owner: the process that ran it is gone. It is settled here.

No staleness threshold is used or needed, and none is invented. Recovery takes the SAME lock while it settles, so two workers (or a restart racing a live worker) cannot both settle
the same turn, a new turn cannot start in the middle of it, and a repeated pass finds nothing to do.

What is settled: the abandoned turn's own run, the child legs still RUNNING/QUEUED under it (terminal reason `INTERRUPTED`), the turn row (FAILED, never charged), and the seller's
thread gets one honest answer saying the request did not finish. Legs that had already completed, and the findings they wrote, are never rewritten. Nothing is re-run.

What is deliberately NOT settled (it cannot be told from legitimate work without a deadline decision that has not been made): a leg that hangs inside a LIVE process, and a leg that
is still running after its turn already ended (the existing late-leg behaviour). A leg that finishes after being settled here does not overwrite the recovery mark
(`finish_run_if_unfinished`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from backend.ceo import deadlines
from backend.ceo.billing import REASON_NOT_DELIVERED, UnitDecision
from backend.ceo.turn_lock import TurnInProgress, investigation_turn_lock
from backend.repositories import accounting_cutover_repo, agent_run_repo, ceo_runtime_repo, investigation_repo as repo, run_liveness

logger = logging.getLogger(__name__)

INTERRUPTED_REASON = "INTERRUPTED: the process running this turn stopped before it finished"
INTERRUPTED_ANSWER = (
    "That request was interrupted and did not finish, so I have no answer for it. Anything that had already finished is saved in this investigation's findings, "
    "and nothing was charged for this request. Please ask again."
)


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    owned: bool = False  # the turn lock was held: a live turn exists, so nothing was touched
    turns_settled: int = 0
    legs_settled: int = 0
    legs_timed_out: int = 0  # past the HARD leg deadline (ceo/deadlines.py), a different thing from an abandoned turn
    orphans_settled: int = 0  # RUNNING rows with no live owner outside the seller-turn path (direct routes, late legs); see `sweep_orphan_runs`
    pi_runs_settled: int = 0
    package_runs_settled: int = 0  # reconciliation_run / ci_capture_run rows whose owner is gone

    def __add__(self, other: "RecoveryReport") -> "RecoveryReport":
        return RecoveryReport(
            self.owned or other.owned, self.turns_settled + other.turns_settled, self.legs_settled + other.legs_settled, self.legs_timed_out + other.legs_timed_out,
            self.orphans_settled + other.orphans_settled, self.pi_runs_settled + other.pi_runs_settled, self.package_runs_settled + other.package_runs_settled,
        )


def settle_abandoned_locked(tenant: UUID, investigation_id: UUID, *, now: datetime | None = None) -> RecoveryReport:
    """Settles every RUNNING conversational CEO run of this investigation. The CALLER MUST HOLD the investigation's turn lock: that is what proves nobody owns them."""
    at = now or datetime.now(timezone.utc)
    report = RecoveryReport()
    for anchor in repo.list_open_ceo_runs(tenant, investigation_id):
        anchor_id: UUID = anchor["id"]
        legs = 0
        for child in agent_run_repo.list_children(tenant, anchor_id):
            if child["status"] in ("RUNNING", "QUEUED") and agent_run_repo.finish_run_if_unfinished(
                tenant, child["id"], status="FAILED", error_reason=INTERRUPTED_REASON, finished_at=at
            ):
                legs += 1
        turn = repo.get_turn_for_run(tenant, anchor_id)
        message_id = _answer_once(tenant, investigation_id, anchor_id, turn, at)
        if turn is not None and turn["completed_at"] is None:
            _finalise_turn(tenant, turn, message_id, at)
        if agent_run_repo.finish_run_if_unfinished(tenant, anchor_id, status="FAILED", error_reason=INTERRUPTED_REASON, finished_at=at):
            report += RecoveryReport(False, 1, legs)
            logger.warning("settled an abandoned CEO turn (tenant=%s investigation=%s run=%s)", tenant, investigation_id, anchor_id)
        else:
            report += RecoveryReport(False, 0, legs)
    return report


def _answer_once(tenant: UUID, investigation_id: UUID, anchor_id: UUID, turn: dict | None, at: datetime) -> UUID | None:
    messages = repo.list_messages(tenant, investigation_id)
    existing = next((m for m in messages if m["role"] == "CEO" and m["agent_run_id"] == anchor_id), None)  # a pass that died half way must not answer twice
    if existing is not None:
        return existing["id"]
    unanswered = (turn is not None and not turn.get("ceo_message_id")) or (turn is None and bool(messages) and messages[-1]["role"] == "USER")
    if not unanswered:
        return None
    return repo.append_message(
        tenant, investigation_id, role="CEO", kind="ANSWER", content=INTERRUPTED_ANSWER, agent_run_id=anchor_id, turn_id=turn["id"] if turn else None, now=at
    )


def _finalise_turn(tenant: UUID, turn: dict, message_id: UUID | None, at: datetime) -> None:
    if accounting_cutover_repo.is_post_cutover(accounting_cutover_repo.CEO_UNIT_RULE_2, turn["created_at"]):
        # the billing decision is stored once, with the turn, and an interrupted turn is never due
        repo.finalise_turn(tenant, turn["id"], status="FAILED", billing=UnitDecision(False, REASON_NOT_DELIVERED, "FAILED").to_json(), ceo_message_id=message_id, completed_at=at)
    else:
        repo.update_turn(tenant, turn["id"], status="FAILED", ceo_message_id=message_id, completed_at=at)


def recover_investigation(tenant: UUID, investigation_id: UUID, *, now: datetime | None = None) -> RecoveryReport:
    """Settles this investigation's abandoned turns, then (only when a hard deadline is configured) its overdue legs, unless a live turn owns it (then nothing is touched)."""
    try:
        with investigation_turn_lock(investigation_id, None):
            report = settle_abandoned_locked(tenant, investigation_id, now=now)
            return report + RecoveryReport(legs_timed_out=deadlines.settle_overdue_legs_locked(tenant, investigation_id, now=now).settled)
    except TurnInProgress:
        return RecoveryReport(owned=True)


@dataclass(frozen=True, slots=True)
class LastPass:
    at: datetime
    report: RecoveryReport


LAST_PASS: LastPass | None = None  # this process's most recent sweep (start-up or periodic); None until one has run


def diagnose() -> dict[str, object]:
    """Counts only, no tenant data: how many runs are RUNNING right now, how many of those have a live owner and how many are ownerless (waiting for the next sweep), the oldest
    RUNNING start, and what this process's last sweep did. Walks every tenant through its own RLS scope, so cost grows with the number of tenants."""
    now = datetime.now(timezone.utc)
    running: dict[str, int] = {}
    owned = ownerless = 0
    oldest: datetime | None = None
    pi_active = 0
    for tenant in ceo_runtime_repo.list_tenant_ids():
        rows = [(r["agent_id"], r["id"], "agent_run", r["started_at"]) for r in agent_run_repo.list_running_all(tenant)]
        for table in run_liveness.PACKAGE_RUN_KINDS:
            rows += [(table, run_id, table, None) for run_id in agent_run_repo.list_running_package_runs(tenant, table)]
        for label, run_id, kind, started in rows:
            running[label] = running.get(label, 0) + 1
            if run_liveness.is_owned_elsewhere(run_id, kind):
                owned += 1
            else:
                ownerless += 1
            if started is not None and (oldest is None or started < oldest):
                oldest = started
        pi_active += agent_run_repo.count_active_pi_research_runs(tenant)
    last = LAST_PASS
    return {
        "running": {"total": owned + ownerless, "withLiveOwner": owned, "ownerless": ownerless, "byKind": dict(sorted(running.items()))},
        "oldestRunningSeconds": int((now - oldest).total_seconds()) if oldest is not None else None,
        "piResearchRunsActive": pi_active,
        "thisProcess": {"ownedRuns": run_liveness.held_count()},
        "lastSweep": None if last is None else {
            "at": last.at.isoformat(), "turnsSettled": last.report.turns_settled, "ownerlessRunsSettled": last.report.orphans_settled,
            "piRunsSettled": last.report.pi_runs_settled, "packageRunsSettled": last.report.package_runs_settled,
        },
    }


def sweep_all(*, now: datetime | None = None, tenants: Iterable[UUID] | None = None) -> RecoveryReport:
    """One pass over every tenant's (or the given tenants') investigations that have a RUNNING conversational CEO run. Safe to run from every worker at start-up and to repeat."""
    total = RecoveryReport()
    tenant_list = list(tenants) if tenants is not None else ceo_runtime_repo.list_tenant_ids()
    for tenant in tenant_list:
        pending = set(repo.investigations_with_open_ceo_runs(tenant))
        if deadlines.effective_abandon_seconds() is not None:
            pending |= set(repo.investigations_with_late_legs(tenant))
        for investigation_id in pending:
            try:
                total += recover_investigation(tenant, investigation_id, now=now)
            except Exception:  # noqa: BLE001 — one bad investigation must not stop the pass
                logger.exception("could not recover investigation %s (tenant=%s)", investigation_id, tenant)
    global LAST_PASS
    total = total + sweep_orphan_runs(now=now, tenants=tenant_list)  # after the turn pass, so a settled turn's legs are already terminal
    LAST_PASS = LastPass(datetime.now(timezone.utc), total)
    return total


def sweep_orphan_runs(*, now: datetime | None = None, tenants: Iterable[UUID] | None = None) -> RecoveryReport:
    """R5: settles RUNNING `agent_run` rows that have NO LIVE OWNER and are not seller-turn anchors (a direct route whose process was killed, a leg whose process died).

    Ownership is the advisory lock each RUNNING run holds while its process works on it (`repositories/run_liveness.py`). Lock held (by any session, including this
    process) => the run is alive, however long it has taken, and is never touched. Lock free => nobody is working on it. No age, no deadline, no retry, no dispatch:
    the row is only moved to FAILED `INTERRUPTED` through the guarded write, so a finisher that wins the race keeps its real result and a repeated pass finds nothing.
    An effect an interrupted external call may have had is NOT assumed either way and NOT repeated; the seller is told it was interrupted, not that it failed to happen.

    Also settles a tenant's orphaned `pi_research_run` rows (they block editing and re-running the brief for as long as they stay RUNNING) when the tenant has no
    live PI run at all. Rows written before this ownership rule existed are treated as ownerless once their process is gone: deploy it with no older worker running.
    """
    at = now or datetime.now(timezone.utc)
    total = RecoveryReport()
    for tenant in (list(tenants) if tenants is not None else ceo_runtime_repo.list_tenant_ids()):
        try:
            total += _sweep_tenant_orphans(tenant, at)
        except Exception:  # noqa: BLE001 — one tenant must not stop the pass
            logger.exception("could not sweep orphaned runs (tenant=%s)", tenant)
    return total


def _sweep_tenant_orphans(tenant: UUID, at: datetime) -> RecoveryReport:
    settled = 0
    for row in agent_run_repo.list_running_unconversational(tenant):
        if run_liveness.is_owned_elsewhere(row["id"]):
            continue
        if agent_run_repo.finish_run_if_unfinished(tenant, row["id"], status="FAILED", error_reason=INTERRUPTED_REASON, finished_at=at):
            settled += 1
            logger.warning("settled an ownerless run (tenant=%s run=%s agent=%s trigger=%s)", tenant, row["id"], row["agent_id"], row["trigger_ref"])
    pi = 0
    looked_from = datetime.now(timezone.utc)  # before the live-owner check: a PI run that starts after this instant is never swept
    if not any(run_liveness.is_owned_elsewhere(r) for r in agent_run_repo.has_running_agent(tenant, "PI")):
        pi = agent_run_repo.settle_orphan_pi_research_runs(tenant, finished_at=at, created_before=looked_from)
        if pi:
            logger.warning("settled %d orphaned PI research run(s) (tenant=%s)", pi, tenant)
    package = 0
    for table in run_liveness.PACKAGE_RUN_KINDS:
        for run_id in agent_run_repo.list_running_package_runs(tenant, table):
            if run_liveness.is_owned_elsewhere(run_id, table):
                continue
            if agent_run_repo.settle_package_run_failed(tenant, table, run_id, finished_at=at):
                package += 1
                logger.warning("settled an ownerless %s (tenant=%s run=%s)", table, tenant, run_id)
    return RecoveryReport(orphans_settled=settled, pi_runs_settled=pi, package_runs_settled=package)
