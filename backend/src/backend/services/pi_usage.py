"""PI usage: decide once whether a run is billable, record at most one idempotent event per logical run and meter, and protect caps with reservations.

Approval prerequisites R3 and R6 (docs/planning/ceo-approval-remediation-design.md; owner decisions Q-S0-1, Q-R2, Q-R3, Q-R4, Q-R8, F3, F8, F9, F10).

BILLABILITY (documented criteria, F8). Run status alone never establishes billability:
* `pi.discover` is billable iff the run ended COMPLETE or PARTIAL **and** it persisted at least one candidate with a COMPUTED proxy score (the predicate the run
  itself uses to build its shortlist). Today an EMPTY run is already marked PARTIAL, so status cannot decide.
* `pi.supplier_lookup` is billable iff the call returned and at least one candidate result has a usable lead (non-empty `lead_ids`).
Empty, failed and interrupted runs are never billable.

EVENTS. One idempotent `metered_event` per logical run and meter: `pi:run:<pi_research_run.id>:<meter>` for discover (agents PI and SHARED, meters `pi.discover` and
`research.niche_run`) and `pi:supplier:<route agent_run id>` for a lookup. The decision is stored once on the run (`pi_research_run.usage_due/outcome_code`, first writer
wins), and only the call that stored it writes the events. Legacy runs (no `created_at`) and runs before the accounting cut-over are never decided or billed (Q-R4).
The two `agent_run` rows a discover writes are left as they are (F10); usage is keyed to the logical run, never to an `agent_run` row.

CAPS. Reservations (R6) make a cap safe under concurrency: the unit is reserved atomically before any provider is called, settled only after the events are written,
released on failure/empty, and left to expire (fail-safe) after a crash. **A PI cap must not be seeded unless `PI_QUOTA_RESERVATION_TTL_SECONDS` is set and at least the
structural worst-case duration of the action** (`product_intelligence.timing`); otherwise the request is refused with 503 rather than risk an overshoot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from product_intelligence import timing
from product_intelligence.direct_path.pi_discover import PiRunResult
from product_intelligence.direct_path.pi_supplier_lookup import SupplierLookupResult
from product_intelligence.repositories import pi_research_run_repo, product_candidate_repo

from backend import config
from backend.entitlement import (
    NICHE_RUN_AGENT_CODE,
    NICHE_RUN_EVENT_KIND,
    record_metered_event,
    resolve_niche_run_entitlement,
    resolve_pi_entitlement,
)
from backend.repositories import accounting_cutover_repo as cutover
from backend.repositories import quota_reservation_repo as quota

logger = logging.getLogger(__name__)

PI_AGENT_CODE = "PI"
DISCOVER = "pi.discover"
SUPPLIER_LOOKUP = "pi.supplier_lookup"

OUTCOME_USABLE = "USABLE"
OUTCOME_USABLE_PARTIAL = "USABLE_PARTIAL"
OUTCOME_EMPTY = "EMPTY_RESULT"
OUTCOME_FAILED = "FAILED"


# ------------------------------------------------------------------------------------------------ billability (F8)
def decide_discover(tenant_id: UUID, result: PiRunResult) -> tuple[bool, str]:
    if result.status not in ("COMPLETE", "PARTIAL"):
        return False, OUTCOME_FAILED
    candidates = product_candidate_repo.list_candidates_for_run(tenant_id, result.run_id)
    if not any(c.get("proxy_state") == "COMPUTED" and c.get("proxy_score") is not None for c in candidates):
        return False, OUTCOME_EMPTY
    return True, OUTCOME_USABLE if result.status == "COMPLETE" else OUTCOME_USABLE_PARTIAL


def decide_lookup(results: Sequence[SupplierLookupResult]) -> tuple[bool, str]:
    return (True, OUTCOME_USABLE) if any(r.lead_ids for r in results) else (False, OUTCOME_EMPTY)


# ------------------------------------------------------------------------------------------------ reservations (R6)
class QuotaDenied(Exception):
    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__("quota denied")
        self.detail = detail


class QuotaNotConfigured(Exception):
    """A cap exists but the reservation cannot be made safely (TTL missing or shorter than the action's worst case): refuse rather than risk an overshoot."""


class RequestInProgress(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Meter:
    agent_code: str
    kind: str
    resolve: Callable[[UUID], Any]


DISCOVER_METERS = (
    Meter(NICHE_RUN_AGENT_CODE, NICHE_RUN_EVENT_KIND, resolve_niche_run_entitlement),
    Meter(PI_AGENT_CODE, DISCOVER, lambda t: resolve_pi_entitlement(t, direct_action_code=DISCOVER)),
)
LOOKUP_METERS = (Meter(PI_AGENT_CODE, SUPPLIER_LOOKUP, lambda t: resolve_pi_entitlement(t, direct_action_code=SUPPLIER_LOOKUP)),)


@dataclass(slots=True)
class Held:
    """The reservations one request holds (empty when no cap is configured)."""

    ids: list[tuple[str, UUID]] = field(default_factory=list)


def _ttl(worst_case_seconds: int | None) -> int:
    if worst_case_seconds is None:
        raise QuotaNotConfigured("the action's worst-case duration cannot be established (e.g. candidate_cap < 1), so a reservation TTL cannot be validated")
    try:
        ttl = config.pi_quota_reservation_ttl_seconds()
    except (config.MissingConfig, ValueError) as exc:
        raise QuotaNotConfigured(f"PI_QUOTA_RESERVATION_TTL_SECONDS is not usable: {exc}") from None
    if ttl < worst_case_seconds:
        raise QuotaNotConfigured(f"PI_QUOTA_RESERVATION_TTL_SECONDS={ttl} is shorter than the action's worst-case duration ({worst_case_seconds}s)")
    return ttl


def reserve(tenant_id: UUID, meters: Sequence[Meter], *, request_key: str, worst_case_seconds: int | None, now: datetime) -> Held:
    """Reserves one unit on every capped meter, atomically per meter; a denial on a later meter releases the earlier ones. Meters with no cap reserve nothing."""
    held = Held()
    try:
        for m in meters:
            ent = m.resolve(tenant_id)
            if ent.cap_value is None:
                continue
            try:
                res = quota.reserve(
                    tenant_id, agent_code=m.agent_code, meter_code=ent.meter_code, period_key=ent.period_key, units=1,
                    request_key=f"{request_key}:{m.kind}", cap_value=ent.cap_value, now=now, ttl_seconds=_ttl(worst_case_seconds),
                )
            except quota.ReservationInProgress:
                raise RequestInProgress() from None
            if isinstance(res, quota.ReserveDenied):
                c = res.check
                raise QuotaDenied({
                    "reason": "OVER_CAP", "meterCode": ent.meter_code, "service": m.kind, "evaluationBasis": "OVER_CAP",
                    "cap": c.cap, "usage": res.metered_units, "reserved": res.reserved_units, "remaining": c.remaining,
                })
            held.ids.append((m.agent_code, res.reservation_id))
    except Exception:
        release(tenant_id, held, now=now)
        raise
    return held


def _finish(tenant_id: UUID, held: Held | None, state: str, now: datetime) -> None:
    for _agent, rid in (held.ids if held else []):
        try:
            quota.finish(tenant_id, rid, state=state, now=now)
        except Exception:  # noqa: BLE001 — a reservation that cannot be finished simply expires (fail-safe)
            logger.exception("could not mark PI quota reservation %s %s", rid, state)


def release(tenant_id: UUID, held: Held | None, *, now: datetime) -> None:
    _finish(tenant_id, held, "RELEASED", now)


# ------------------------------------------------------------------------------------------------ settlement (R3)
def _write(tenant_id: UUID, *, agent_code: str, kind: str, key: str, member_id: UUID, agent_run_id: UUID | None, source_ref: UUID, at: datetime) -> bool:
    return record_metered_event(
        tenant_id, agent_code=agent_code, event_kind=kind, idempotency_key=key, member_id=member_id, agent_run_id=agent_run_id, source_ref=source_ref, occurred_at=at,
    ) is not None


def settle_discover(tenant_id: UUID, *, requested_by: UUID, result: PiRunResult, route_agent_run_id: UUID | None, held: Held | None, now: datetime) -> str:
    """Decides once, stores the decision on the run, writes the (idempotent) events only for the call that stored it, and settles or releases the reservations."""
    run = pi_research_run_repo.get_run(tenant_id, result.run_id)
    created_at = run.get("created_at") if run else None
    if created_at is None:  # a legacy run: never decided, never billed (Q-R4)
        release(tenant_id, held, now=now)
        return "LEGACY"
    due, code = decide_discover(tenant_id, result)
    if not pi_research_run_repo.record_outcome(tenant_id, result.run_id, outcome_code=code, usage_due=due):
        stored = pi_research_run_repo.get_run(tenant_id, result.run_id) or {}
        if not stored.get("usage_due"):
            release(tenant_id, held, now=now)  # not billable: nothing to protect
        return str(stored.get("outcome_code") or code)  # another call already decided; only that call writes usage and settles its own reservation
    if not due:
        release(tenant_id, held, now=now)
        return code
    ok = True
    for agent, kind, rule in ((PI_AGENT_CODE, DISCOVER, cutover.PI_USAGE_1), (NICHE_RUN_AGENT_CODE, NICHE_RUN_EVENT_KIND, cutover.NICHE_RUN_USAGE_1)):
        if cutover.is_post_cutover(rule, created_at):
            ok = _write(tenant_id, agent_code=agent, kind=kind, key=f"pi:run:{result.run_id}:{kind}", member_id=requested_by, agent_run_id=route_agent_run_id,
                        source_ref=result.run_id, at=now) and ok
    if ok:
        _finish(tenant_id, held, "SETTLED", now)
    # a failed write leaves the reservation RESERVED until its TTL, so an unmetered unit cannot be used to exceed the cap (repair of the event is R5c, blocked)
    return code


def settle_lookup(tenant_id: UUID, *, requested_by: UUID, results: Sequence[SupplierLookupResult], route_agent_run_id: UUID, held: Held | None, now: datetime) -> str:
    due, code = decide_lookup(results)
    if not due:
        release(tenant_id, held, now=now)
        return code
    ok = True
    if cutover.is_post_cutover(cutover.PI_USAGE_1, now):
        ok = _write(tenant_id, agent_code=PI_AGENT_CODE, kind=SUPPLIER_LOOKUP, key=f"pi:supplier:{route_agent_run_id}", member_id=requested_by,
                    agent_run_id=route_agent_run_id, source_ref=route_agent_run_id, at=now)
    if ok:
        _finish(tenant_id, held, "SETTLED", now)
    return code


def discover_worst_case(candidate_cap: int) -> int | None:
    """None when no bound can be established (candidate_cap < 1): a capped meter then refuses the request instead of trusting a figure that is not a maximum."""
    try:
        return timing.discover_worst_case_seconds(candidate_cap)
    except ValueError:
        return None


def lookup_worst_case(candidates: int) -> int:
    return timing.supplier_lookup_worst_case_seconds(candidates)
