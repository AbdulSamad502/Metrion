"""entitlement_repo — docs/specs/entitlement.md §5/§6 rule 2's resolution order (a
tenant-specific row beats a platform-default row for the same key; the latest
`effective_from <= as_of_date` wins within each tier), mirroring
`calc_engine.repositories.config_repo.resolve_reconciliation_tolerance`'s exact SQL shape and
`ORDER BY` clause.

Every function here receives its connection only via `tenant_scope()` — no function opens
its own connection — mirroring every other tenant-scoped repository in `backend`.

`active_cart_item()` exists for completeness (the schema needs a way to answer "is there an
ACTIVE tenant_cart_item for this agent", per E6's `NO_ACTIVE_CART_ITEM` denial reason) but is
NOT called by `backend.entitlement.resolve_cfo_entitlement` yet. No tenant — existing or
future, until onboarding is separately changed — has a `tenant_cart_item` row today
(`tenant_repo.create()` writes none), so wiring that check into the live entitlement chokepoint
now would deny CFO for every tenant. That wiring is a separate, later task.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tenant_context import tenant_scope

_RESOLVE_CAP_CONFIG_SQL = text(
    """
    SELECT cap_value, saved_resource_cap, scope, period_unit, effective_from, version
    FROM entitlement_cap_config
    WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
      AND agent_code = :agent_code
      AND meter_code = :meter_code
      AND scope = :scope
      AND effective_from <= :as_of_date
    ORDER BY (tenant_id IS NOT NULL) DESC, effective_from DESC
    LIMIT 1
    """
)

_RESOLVE_METER_MAP_SQL = text(
    """
    SELECT meter_code, effective_from, version
    FROM metered_event_meter_map
    WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
      AND event_kind = :event_kind
      AND effective_from <= :as_of_date
    ORDER BY (tenant_id IS NOT NULL) DESC, effective_from DESC
    LIMIT 1
    """
)

_RESOLVE_CAPABILITY_RULE_SQL = text(
    """
    SELECT denial_rendering, reduced_payload_action_code, effective_from, version
    FROM capability_entitlement_rule
    WHERE (tenant_id = :tenant_id OR tenant_id IS NULL)
      AND agent_code = :agent_code
      AND direct_action_code = :direct_action_code
      AND effective_from <= :as_of_date
    ORDER BY (tenant_id IS NOT NULL) DESC, effective_from DESC
    LIMIT 1
    """
)

_USAGE_COUNT_SQL = text(
    """
    SELECT COALESCE(SUM(quantity), 0)
    FROM metered_event
    WHERE tenant_id = :tenant_id
      AND agent_code = :agent_code
      AND meter_code = :meter_code
      AND period_key = :period_key
    """
)

_ACTIVE_CART_ITEM_SQL = text(
    """
    SELECT id, tier, status, started_at, ended_at, source
    FROM tenant_cart_item
    WHERE tenant_id = :tenant_id AND agent_code = :agent_code AND status = 'ACTIVE'
    LIMIT 1
    """
)

_INSERT_METERED_EVENT_SQL = text(
    """
    INSERT INTO metered_event (
      id, tenant_id, member_id, agent_code, event_kind, meter_code, quantity,
      agent_run_id, source_ref, idempotency_key, occurred_at, period_key
    ) VALUES (
      :id, :tenant_id, :member_id, :agent_code, :event_kind, :meter_code, :quantity,
      :agent_run_id, :source_ref, :idempotency_key, :occurred_at, :period_key
    )
    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
    RETURNING id
    """
)

_EXISTING_METERED_EVENT_BY_IDEMPOTENCY_SQL = text(
    "SELECT id FROM metered_event WHERE tenant_id = :tenant_id AND idempotency_key = :idempotency_key"
)


def resolve_cap_config(
    tenant_id: UUID, *, agent_code: str, meter_code: str, scope: str, as_of_date: date
) -> dict[str, Any] | None:
    """§6 rule 2's resolution order. Returns None when no row covers this
    (agent_code, meter_code, scope) at all — callers treat that as NO_CAP_CONFIGURED
    (cap_value=None, always passes, §5.5/E1), never a guessed cap."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _RESOLVE_CAP_CONFIG_SQL,
            {
                "tenant_id": str(tenant_id),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "scope": scope,
                "as_of_date": as_of_date,
            },
        ).first()
        return dict(row._mapping) if row is not None else None


def resolve_meter_map(tenant_id: UUID, *, event_kind: str, as_of_date: date) -> dict[str, Any] | None:
    """§5.2.1: returns None when no mapping row exists for this event_kind — callers fall
    back to `meter_code = event_kind` itself (E5/T6), never dropping the event."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _RESOLVE_METER_MAP_SQL,
            {"tenant_id": str(tenant_id), "event_kind": event_kind, "as_of_date": as_of_date},
        ).first()
        return dict(row._mapping) if row is not None else None


def resolve_capability_rule(
    tenant_id: UUID, *, agent_code: str, direct_action_code: str, as_of_date: date
) -> dict[str, Any] | None:
    """§5.4/§6 rule 9: returns None when no row exists at all — callers treat a None result
    as `denial_rendering='ERROR'`, the column's own default, never `REDUCED_PAYLOAD` by
    absence (E7 guards the inverse: a bad reduced_payload_action_code must also fail closed
    to ERROR, which is the calling agent's job, not this repository's)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _RESOLVE_CAPABILITY_RULE_SQL,
            {
                "tenant_id": str(tenant_id),
                "agent_code": agent_code,
                "direct_action_code": direct_action_code,
                "as_of_date": as_of_date,
            },
        ).first()
        return dict(row._mapping) if row is not None else None


def usage_count_for_period(tenant_id: UUID, *, agent_code: str, meter_code: str, period_key: str) -> int:
    """Live aggregation (D3) — no cached counter table exists in V1. No matching rows sums to
    0, never NULL — this is a usage count, not money (N5), so there is no UNAVAILABLE state
    here the way there is in the deterministic engine."""
    with tenant_scope(tenant_id) as conn:
        total = conn.execute(
            _USAGE_COUNT_SQL,
            {
                "tenant_id": str(tenant_id),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "period_key": period_key,
            },
        ).scalar_one()
        return int(total)


def active_cart_item(tenant_id: UUID, *, agent_code: str) -> dict[str, Any] | None:
    """Built for completeness (E6's `NO_ACTIVE_CART_ITEM` denial needs a way to query this)
    — see this module's own docstring for why `resolve_cfo_entitlement` does not call this
    function yet."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _ACTIVE_CART_ITEM_SQL, {"tenant_id": str(tenant_id), "agent_code": agent_code}
        ).first()
        return dict(row._mapping) if row is not None else None


def insert_metered_event(
    tenant_id: UUID,
    *,
    member_id: UUID | None,
    agent_code: str,
    event_kind: str,
    meter_code: str,
    quantity: int,
    agent_run_id: UUID | None,
    source_ref: UUID | None,
    idempotency_key: str,
    occurred_at: datetime,
    period_key: str,
) -> UUID:
    """AC4/T5: a retried write with a previously-used `idempotency_key` for the same tenant is
    a no-op, never a double count and never an unhandled exception. The `unique (tenant_id,
    idempotency_key)` constraint (Task 1's DDL) is enforced via `ON CONFLICT DO NOTHING`
    rather than letting the database's `IntegrityError` bubble up to the caller — the cleaner
    of the two approaches named in the task brief, since it avoids a driver-specific exception
    check entirely. Either branch returns the real, stable id of the row that now exists for
    this idempotency_key: the newly inserted one, or (on a duplicate) the original one."""
    new_id = uuid4()
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _INSERT_METERED_EVENT_SQL,
            {
                "id": str(new_id),
                "tenant_id": str(tenant_id),
                "member_id": str(member_id) if member_id else None,
                "agent_code": agent_code,
                "event_kind": event_kind,
                "meter_code": meter_code,
                "quantity": quantity,
                "agent_run_id": str(agent_run_id) if agent_run_id else None,
                "source_ref": str(source_ref) if source_ref else None,
                "idempotency_key": idempotency_key,
                "occurred_at": occurred_at,
                "period_key": period_key,
            },
        ).first()
        if row is not None:
            return UUID(str(row[0]))
        existing = conn.execute(
            _EXISTING_METERED_EVENT_BY_IDEMPOTENCY_SQL,
            {"tenant_id": str(tenant_id), "idempotency_key": idempotency_key},
        ).one()
        return UUID(str(existing[0]))
