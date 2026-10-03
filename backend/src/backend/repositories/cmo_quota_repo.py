"""CMO quota reservations (migration 20261004_0005; entitlement.md E2/Q5 amendment; spec §8.4).

`reserve` is the ONE place a capped CMO request is admitted. In a single short transaction it
(1) takes `pg_advisory_xact_lock` on (tenant, agent, meter, period) - concurrent requests for the
same meter queue here, briefly, instead of all reading the same usage; (2) releases reservations
that have expired; (3) computes usage = recorded `metered_event` units + unexpired reservations;
(4) rejects an identical in-flight request (same key) as in progress; (5) applies the all-or-nothing
`billing.precheck`; (6) inserts the reservation. No DB connection is
held while a model runs: the transaction ends before execution begins.

A reservation is quota protection, NOT a billing record. It never contributes a unit to billing;
`metered_event` rows (written after a COMPLETE artefact) are the only usage that persists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text

from slim_cmo.billing import PreCheck, precheck

from backend.tenant_context import tenant_scope

_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))")
_EXPIRE_SQL = text(
    """
    UPDATE cmo_quota_reservation SET state = 'RELEASED', settled_at = :now
    WHERE tenant_id = :tenant_id AND agent_code = :agent_code AND meter_code = :meter_code
      AND period_key = :period_key AND state = 'RESERVED' AND expires_at <= :now
    """
)
_METERED_SQL = text(
    """
    SELECT COALESCE(SUM(quantity), 0) FROM metered_event
    WHERE tenant_id = :tenant_id AND agent_code = :agent_code AND meter_code = :meter_code AND period_key = :period_key
    """
)
_RESERVED_SQL = text(
    """
    SELECT COALESCE(SUM(units), 0) FROM cmo_quota_reservation
    WHERE tenant_id = :tenant_id AND agent_code = :agent_code AND meter_code = :meter_code
      AND period_key = :period_key AND state = 'RESERVED' AND expires_at > :now
    """
)
_ACTIVE_SAME_KEY_SQL = text(
    """
    SELECT 1 FROM cmo_quota_reservation
    WHERE tenant_id = :tenant_id AND agent_code = :agent_code AND meter_code = :meter_code
      AND request_key = :request_key AND state = 'RESERVED' AND expires_at > :now
    """
)
_INSERT_SQL = text(
    """
    INSERT INTO cmo_quota_reservation (tenant_id, agent_code, meter_code, period_key, units, request_key, state, created_at, expires_at)
    VALUES (:tenant_id, :agent_code, :meter_code, :period_key, :units, :request_key, 'RESERVED', :now, :expires_at)
    ON CONFLICT (tenant_id, agent_code, meter_code, request_key) WHERE state = 'RESERVED' DO NOTHING
    RETURNING id
    """
)
_FINISH_SQL = text(
    """
    UPDATE cmo_quota_reservation SET state = :state, settled_at = :now
    WHERE tenant_id = :tenant_id AND id = :id AND state = 'RESERVED'
    """
)


@dataclass(frozen=True, slots=True)
class Reserved:
    reservation_id: UUID


@dataclass(frozen=True, slots=True)
class ReserveDenied:
    check: PreCheck  # requested / usage (metered + reserved) / cap / remaining / shortfall
    metered_units: int
    reserved_units: int


class ReservationInProgress(Exception):
    """An identical request (same tenant, meter and request_key) already holds an active reservation."""


def _scope_key(tenant_id: UUID, agent_code: str, meter_code: str, period_key: str) -> str:
    return f"cmo-quota|{tenant_id}|{agent_code}|{meter_code}|{period_key}"


def reserve(
    tenant_id: UUID,
    *,
    agent_code: str,
    meter_code: str,
    period_key: str,
    units: int,
    request_key: str,
    cap_value: int,
    now: datetime,
    ttl_seconds: int,
) -> Reserved | ReserveDenied:
    scope = {"tenant_id": str(tenant_id), "agent_code": agent_code, "meter_code": meter_code, "period_key": period_key}
    with tenant_scope(tenant_id) as conn:
        conn.execute(_LOCK_SQL, {"scope": _scope_key(tenant_id, agent_code, meter_code, period_key)})
        conn.execute(_EXPIRE_SQL, {**scope, "now": now})
        # An identical request already in flight is "in progress" (409) - decided BEFORE any cap arithmetic, so a
        # double-submit at the cap boundary is never misreported as quota exhaustion.
        if conn.execute(_ACTIVE_SAME_KEY_SQL, {**scope, "request_key": request_key, "now": now}).first() is not None:
            raise ReservationInProgress()
        metered = int(conn.execute(_METERED_SQL, scope).scalar_one())
        reserved = int(conn.execute(_RESERVED_SQL, {**scope, "now": now}).scalar_one())
        check = precheck(units, usage=metered + reserved, cap=cap_value)
        if not check.allowed:
            return ReserveDenied(check, metered, reserved)
        row = conn.execute(
            _INSERT_SQL,
            {**scope, "units": units, "request_key": request_key, "now": now, "expires_at": now + timedelta(seconds=ttl_seconds)},
        ).first()
        if row is None:
            raise ReservationInProgress()
        return Reserved(UUID(str(row[0])))


def finish(tenant_id: UUID, reservation_id: UUID, *, state: str, now: datetime) -> None:
    """RESERVED -> SETTLED | RELEASED. A no-op if it already left RESERVED (e.g. expired)."""
    if state not in ("SETTLED", "RELEASED"):
        raise ValueError(f"unsupported reservation state {state!r}")
    with tenant_scope(tenant_id) as conn:
        conn.execute(_FINISH_SQL, {"tenant_id": str(tenant_id), "id": str(reservation_id), "state": state, "now": now})
