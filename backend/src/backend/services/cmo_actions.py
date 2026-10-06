"""Slim CMO request orchestration (P5): the boundary that keeps these concerns SEPARATE (spec §8, entitlement.md):

    request acceptance -> entitlement / quota admission -> domain execution (P3/P4)
    -> terminal artefact status -> metering settlement -> metered-event idempotency

The P3/P4 services are called, never modified or duplicated: this module adds no generation or catalog
logic. Billing source of truth: the PERSISTED artefact `status` (re-read after execution) plus idempotent
`metered_event` rows keyed `cmo:<generation_id>`. `billable_units` is never read. Reservations
(`cmo_quota_repo`) are quota protection only and never a billing record.

`run_billable` flow:
  1. request-level validation (key, shape) - raises before anything is written;
  2. `billing.plan_request`: artefacts already COMPLETE under this key are REUSED - free, no reservation,
     no new `agent_run`, and their (idempotent) metering is re-asserted so a missed write is reconciled (E3);
  3. admission: if a cap is configured for the resolved meter, RESERVE the whole request's units atomically
     (transaction-scoped advisory lock; denial = 402, identical in-flight request = 409). No cap -> no reservation;
  4. execute the domain action with NO database connection held;
  5. re-read the persisted rows, write ONE `agent_run` for the accepted execution, record one metered event per
     COMPLETE artefact (never for FAILED), then settle the reservation.
A metering write that fails never blocks or reverts the delivered result (D4); the reservation then stays
RESERVED until its TTL so the unmetered units keep counting against the cap.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from slim_cmo import billing
from slim_cmo.service.errors import GroundingRequired, InvalidApproval, InvalidConfirmation, NotFound
from slim_cmo.service.generate import RunReport
from slim_cmo.service.models import StoredGeneration
from slim_cmo.types import GenerationStatus, OutputType

from backend import config
from backend.entitlement import cmo_metering_key, record_metered_event, resolve_cmo_entitlement
from backend.repositories import agent_run_repo, cmo_quota_repo
from backend.services import cmo_response
from backend.services.cmo_runtime import CmoNotConfigured, CmoRuntime

logger = logging.getLogger(__name__)

AGENT_CODE = "CMO"
AGENT_ID = "CMO"

# Set ONLY by the CEO hub's `dispatch_cmo_*` functions for the duration of one dispatched call: every `agent_run` a CMO action
# records then carries the CEO turn's run id as `parent_run_id` (agent-orchestration: parent/child linkage). Direct-path HTTP
# calls never set it, so their runs have no parent. A context variable keeps the action signatures unchanged.
PARENT_RUN_ID: contextvars.ContextVar[UUID | None] = contextvars.ContextVar("cmo_parent_run_id", default=None)

# Failures that mean "this request was never accepted": nothing is persisted, no run row is written.
REQUEST_ERRORS = (billing.InvalidRequest, GroundingRequired, InvalidApproval, InvalidConfirmation, NotFound)


class QuotaDenied(Exception):
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__("quota denied")


class RequestInProgress(Exception):
    """An identical request (same tenant, meter, request_key) holds an active reservation."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Derived ONLY from the authenticated context - never from a request body."""

    tenant_id: UUID
    user_id: UUID


# ---- admission (entitlement + quota) --------------------------------------------------------


def _admit(principal: Principal, action: billing.Action, key: str, units: int, now: datetime) -> UUID | None:
    ent = resolve_cmo_entitlement(principal.tenant_id, direct_action_code=action.value, occurred_at=now)
    if ent.cap_value is None:
        return None  # NO_CAP_CONFIGURED: stated honestly, nothing to serialise (entitlement.md E1)
    try:
        ttl = config.cmo_quota_reservation_ttl_seconds()
    except (config.MissingConfig, ValueError) as exc:
        logger.error("CMO quota reservation TTL is not configured: %s", exc)
        raise CmoNotConfigured() from None
    try:
        res = cmo_quota_repo.reserve(
            principal.tenant_id, agent_code=AGENT_CODE, meter_code=ent.meter_code, period_key=ent.period_key,
            units=units, request_key=key, cap_value=ent.cap_value, now=now, ttl_seconds=ttl,
        )
    except cmo_quota_repo.ReservationInProgress:
        raise RequestInProgress() from None
    if isinstance(res, cmo_quota_repo.ReserveDenied):
        c = res.check
        raise QuotaDenied(
            {
                "reason": "OVER_CAP", "meterCode": ent.meter_code, "evaluationBasis": "OVER_CAP",
                "cap": c.cap, "usage": res.metered_units, "reserved": res.reserved_units,
                "requested": c.requested, "remaining": c.remaining,
            }
        )
    return res.reservation_id


def _finish_reservation(principal: Principal, reservation_id: UUID | None, state: str, now: datetime) -> None:
    if reservation_id is None:
        return
    try:
        cmo_quota_repo.finish(principal.tenant_id, reservation_id, state=state, now=now)
    except Exception:  # noqa: BLE001 - an unreleased reservation simply expires at its TTL
        logger.exception("could not finish CMO quota reservation %s", reservation_id)


# ---- agent_run ------------------------------------------------------------------------------


def _record_run(
    principal: Principal, trigger: str, run_id: UUID, *, status: str, started: datetime, finished: datetime, error: str | None = None
) -> bool:
    """One `agent_run` per ACCEPTED execution, written once it has a terminal status. Best-effort: the
    delivered result is never blocked by it."""
    try:
        agent_run_repo.insert_run(
            principal.tenant_id, agent_id=AGENT_ID, trigger_type="DIRECT", trigger_ref=trigger,
            requested_by=principal.user_id, permission_check="PASS", entitlement_check="PASS", status=status,
            started_at=started, finished_at=finished, error_reason=error, run_id=run_id, parent_run_id=PARENT_RUN_ID.get(),
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("could not record CMO agent_run %s", run_id)
        return False


# ---- settlement -----------------------------------------------------------------------------


def _settle(
    principal: Principal, runtime: CmoRuntime, report: RunReport, rows: dict[UUID, StoredGeneration],
    run_id: UUID | None, now: datetime,
) -> bool:
    """Record one metered event per artefact whose PERSISTED status is COMPLETE. A FAILED row never reaches
    `record_metered_event`. Idempotent per artefact (`cmo:<id>`), so a replay re-asserts, never double-counts."""
    complete = True
    for art in report.artefacts:
        row = rows[art.generation_id]
        if row.status is not GenerationStatus.COMPLETE:
            continue
        event = record_metered_event(
            principal.tenant_id,
            agent_code=AGENT_CODE,
            event_kind=billing.EVENT_KIND_BY_OUTPUT_TYPE[row.output_type],
            idempotency_key=cmo_metering_key(row.id),
            member_id=principal.user_id,
            agent_run_id=row.agent_run_id if art.reused else run_id,
            source_ref=row.id,
            occurred_at=row.created_at if art.reused else now,
        )
        complete = complete and event is not None
    return complete


# ---- the billable action --------------------------------------------------------------------


def run_billable(
    principal: Principal,
    runtime: CmoRuntime,
    *,
    action: billing.Action,
    items: Sequence[billing.RequestedArtefact],
    request_key: str,
    execute: Callable[[UUID | None], RunReport],
) -> dict[str, Any]:
    store, tenant = runtime.store, principal.tenant_id
    now = runtime.clock()
    key = billing.normalise_request_key(request_key)
    plan = billing.plan_request(items, request_key=key, existing=store.find_artefacts(tenant, key))

    reservation_id: UUID | None = None
    run_id: UUID | None = None
    if plan.to_generate:
        reservation_id = _admit(principal, action, key, plan.units_required, now)
        run_id = uuid4()

    try:
        report = execute(run_id)
    except REQUEST_ERRORS:
        _finish_reservation(principal, reservation_id, "RELEASED", runtime.clock())
        raise
    except Exception:
        _finish_reservation(principal, reservation_id, "RELEASED", runtime.clock())
        if run_id is not None:
            _record_run(principal, action.value, run_id, status="FAILED", started=now, finished=runtime.clock(), error="execution failed")
        raise

    rows: dict[UUID, StoredGeneration] = {}
    for art in report.artefacts:
        row = store.load_generation(tenant, art.generation_id)
        if row is None:  # an artefact the service just reported must exist for this tenant
            raise RuntimeError("persisted artefact missing")
        rows[art.generation_id] = row

    executed = any(not a.reused for a in report.artefacts)  # a pure replay / lost race creates no new run
    run_recorded = False
    if executed and run_id is not None:
        run_recorded = _record_run(principal, action.value, run_id, status=report.run_status.value, started=now, finished=runtime.clock())

    metered_ok = _settle(principal, runtime, report, rows, run_id if run_recorded else None, runtime.clock())
    # Reservation: SETTLED only when every delivered unit is now a recorded metered event; otherwise it keeps
    # counting until its TTL so an unmetered unit cannot be used to exceed the cap.
    if metered_ok:
        _finish_reservation(principal, reservation_id, "SETTLED", runtime.clock())

    shown_run = run_id if run_recorded else next((r.agent_run_id for r in rows.values() if r.agent_run_id), None)
    return cmo_response.run_json(
        [cmo_response.artefact_json(rows[a.generation_id], reused=a.reused) for a in report.artefacts],
        run_status=report.run_status.value, units_billed=len(report.delivered_ids), agent_run_id=shown_run,
    )


# ---- zero-unit actions ----------------------------------------------------------------------


def record_free_run(
    principal: Principal, runtime: Any, action: billing.Action | str, run_id: UUID, started: datetime, *, status: str = "COMPLETE"
) -> None:
    """Zero-unit actions (`cmo.approve_title`, `cmo.confirm_image_hint`, and the P6 image actions) write an `agent_run`
    for an accepted, executed call - and NOTHING else: no reservation, no entitlement check, no metered event.
    `runtime` is anything with a `clock` (the generation runtime or the image runtime)."""
    trigger = action.value if isinstance(action, billing.Action) else action
    _record_run(principal, trigger, run_id, status=status, started=started, finished=runtime.clock())


def output_type_of(action: billing.Action) -> OutputType | None:
    return billing.ACTION_OUTPUT_TYPE[action]
