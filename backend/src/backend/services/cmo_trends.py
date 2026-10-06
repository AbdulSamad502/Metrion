"""`cmo.market_trends` request orchestration (spec §6.8.9, 7f): permissions are checked by the route; this module adds the TWO
independent entitlement meters (CMO `cmo.market_trends` and the shared `research.market_trends`), one `agent_run`, and settlement.

Flow (provider calls happen only after BOTH checks pass):
  1. an identical COMPLETE report already delivered under this key is replayed: no admission, no reservation, no run, no units;
  2. required configuration is verified (fail closed, nothing reserved yet);
  3. admission on each meter whose cap resolves: RESERVE one unit atomically (the P5 advisory-locked reservation). Either denial
     is a 402 naming the meter, and a reservation already taken on the first meter is released;
  4. the domain service runs (preview-bound plan -> retrieval -> findings -> interpretation -> evidence -> persistence) with no
     database connection held while a provider or the model is awaited;
  5. a COMPLETE, newly delivered report records ONE metered event on each meter (idempotent); a FAILED report records none
     (0 units). Reservations are SETTLED only when every event was recorded, else they keep counting until their TTL.
Metering failures never block or revert the delivered result (entitlement.md D4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from slim_cmo import billing
from slim_cmo.service.models import Actor
from slim_cmo.service.trends import StoredTrendReport, TrendReportService, TrendRequest, TrendRunReport
from slim_cmo.types import GenerationStatus, Marketplace, OutputType, TrendSection

from backend import config
from backend.entitlement import (
    MARKET_TRENDS_AGENT_CODE, MARKET_TRENDS_EVENT_KIND, cmo_metering_key, record_metered_event, resolve_cmo_entitlement,
    resolve_market_trends_entitlement,
)
from backend.repositories import cmo_quota_repo
from backend.services.cmo_actions import AGENT_CODE, Principal, QuotaDenied, RequestInProgress, _finish_reservation, _record_run
from backend.services.cmo_runtime import CmoNotConfigured

logger = logging.getLogger(__name__)

SHARED_KEY_PREFIX = "shared-trends:"


@dataclass(frozen=True, slots=True)
class _Held:
    agent_code: str
    meter_code: str
    reservation_id: UUID


def shared_metering_key(generation_id: UUID) -> str:
    return f"{SHARED_KEY_PREFIX}{generation_id}"


def _reserve(principal: Principal, *, agent_code: str, ent: Any, key: str, now: datetime) -> _Held | None:
    if ent.cap_value is None:
        return None  # NO_CAP_CONFIGURED: stated honestly, nothing to serialise
    try:
        ttl = config.cmo_quota_reservation_ttl_seconds()
    except (config.MissingConfig, ValueError) as exc:
        logger.error("CMO quota reservation TTL is not configured: %s", exc)
        raise CmoNotConfigured() from None
    try:
        res = cmo_quota_repo.reserve(
            principal.tenant_id, agent_code=agent_code, meter_code=ent.meter_code, period_key=ent.period_key, units=1,
            request_key=key, cap_value=ent.cap_value, now=now, ttl_seconds=ttl,
        )
    except cmo_quota_repo.ReservationInProgress:
        raise RequestInProgress() from None
    if isinstance(res, cmo_quota_repo.ReserveDenied):
        c = res.check
        raise QuotaDenied(
            {
                "reason": "OVER_CAP", "meterCode": ent.meter_code, "agentCode": agent_code, "evaluationBasis": "OVER_CAP",
                "cap": c.cap, "usage": res.metered_units, "reserved": res.reserved_units, "requested": c.requested, "remaining": c.remaining,
            }
        )
    return _Held(agent_code, ent.meter_code, res.reservation_id)


def _admit_both(principal: Principal, key: str, now: datetime) -> list[_Held]:
    held: list[_Held] = []
    try:
        for agent_code, ent in (
            (AGENT_CODE, resolve_cmo_entitlement(principal.tenant_id, direct_action_code=billing.Action.MARKET_TRENDS.value, occurred_at=now)),
            (MARKET_TRENDS_AGENT_CODE, resolve_market_trends_entitlement(principal.tenant_id, occurred_at=now)),
        ):
            got = _reserve(principal, agent_code=agent_code, ent=ent, key=key, now=now)
            if got is not None:
                held.append(got)
    except Exception:
        for h in held:  # a denial on the second meter must not leave the first one's units reserved
            _finish_reservation(principal, h.reservation_id, "RELEASED", now)
        raise
    return held


def _release(principal: Principal, held: list[_Held], now: datetime) -> None:
    for h in held:
        _finish_reservation(principal, h.reservation_id, "RELEASED", now)


def report_json(row: StoredTrendReport, *, reused: bool, units: int, run_id: UUID | None) -> dict[str, Any]:
    return {
        "generationId": str(row.generation_id), "status": row.status.value, "reused": reused,
        "failureReason": row.failure_reason, "createdAt": row.created_at.isoformat(),
        "unitsBilled": {"cmo": units, "shared": units}, "agentRunId": str(run_id) if run_id else (str(row.agent_run_id) if row.agent_run_id else None),
        "report": row.report,
    }


def run_trend_report(
    principal: Principal,
    service: TrendReportService,
    *,
    request_key: str,
    plan_digest: str,
    sections: tuple[TrendSection, ...],
    marketplaces: tuple[Marketplace, ...],
) -> dict[str, Any]:
    actor = Actor(principal.tenant_id, principal.user_id)
    now = service.clock()
    key = billing.normalise_request_key(request_key)

    existing = service.find_existing(actor, key)
    if existing is not None:  # idempotent replay: free, no run, no reservation; metering is re-asserted below (reconciliation)
        service.check_replay(actor, existing, plan_digest)  # same key + different plan = 409, never a silently different report
        row = service.get(actor, existing)
        _settle(principal, existing, None, row.created_at)
        return report_json(row, reused=True, units=0, run_id=None)

    service.ensure_configured(actor)  # fail closed BEFORE anything is reserved
    held = _admit_both(principal, key, now)
    run_id = uuid4()
    try:
        outcome: TrendRunReport = service.generate(
            actor, TrendRequest(key, plan_digest, sections, marketplaces, agent_run_id=run_id)
        )
    except Exception as exc:
        _release(principal, held, service.clock())
        if _is_unexpected(exc):
            _record_run(principal, billing.Action.MARKET_TRENDS.value, run_id, status="FAILED", started=now, finished=service.clock(), error="execution failed")
        raise

    if outcome.reused:  # lost a race to an identical request: the winner recorded the run and the metering; release our reservations
        _release(principal, held, service.clock())
        row = service.get(actor, outcome.generation_id)
        return report_json(row, reused=True, units=0, run_id=None)
    run_recorded = False
    if not outcome.reused:
        run_recorded = _record_run(principal, billing.Action.MARKET_TRENDS.value, run_id, status=outcome.status.value, started=now, finished=service.clock())
    metered_ok = True
    if outcome.status is GenerationStatus.COMPLETE:
        metered_ok = _settle(principal, outcome.generation_id, run_id if run_recorded else None, service.clock())
    if metered_ok or outcome.status is GenerationStatus.FAILED:
        for h in held:
            _finish_reservation(principal, h.reservation_id, "SETTLED" if outcome.status is GenerationStatus.COMPLETE else "RELEASED", service.clock())
    row = service.get(actor, outcome.generation_id)
    return report_json(row, reused=outcome.reused, units=outcome.units_to_bill, run_id=run_id if run_recorded else None)


def _is_unexpected(exc: Exception) -> bool:
    from slim_cmo.service.trends import PlanChanged, RequestKeyReused, TrendConfigMissing

    return not isinstance(exc, (PlanChanged, RequestKeyReused, TrendConfigMissing, QuotaDenied, RequestInProgress))


def _settle(principal: Principal, generation_id: UUID, run_id: UUID | None, at: datetime) -> bool:
    """One idempotent metered event per meter for a COMPLETE report. Safe to repeat (a replay re-asserts, never double counts)."""
    ok = True
    for agent_code, kind, idem in (
        (AGENT_CODE, billing.EVENT_KIND_BY_OUTPUT_TYPE[OutputType.TREND_REPORT], cmo_metering_key(generation_id)),
        (MARKET_TRENDS_AGENT_CODE, MARKET_TRENDS_EVENT_KIND, shared_metering_key(generation_id)),
    ):
        event = record_metered_event(
            principal.tenant_id, agent_code=agent_code, event_kind=kind, idempotency_key=idem, member_id=principal.user_id,
            agent_run_id=run_id, source_ref=generation_id, occurred_at=at,
        )
        ok = ok and event is not None
    return ok
