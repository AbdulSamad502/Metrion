"""Integration coverage for F2's real `resolve_cfo_entitlement` rewrite (docs/specs/
entitlement.md) against a real Postgres — mirrors `test_rls_isolation.py`'s own pattern:
connected as `metrion_app` for entitlement resolution/repo calls, `migrate_engine` for
seeding platform-default config rows (mirrors `fee_reference`'s precedent — seeding a
platform-default row is a `metrion_migrate`-run data migration, never an application code
path, entitlement.md §7 rule 2).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from backend.entitlement import resolve_cfo_entitlement
from backend.repositories import entitlement_repo
from backend.tenant_context import tenant_scope

_AS_OF = date(2026, 9, 25)
_OCCURRED_AT = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)


def _seed_platform_cap(migrate_engine, *, agent_code: str, meter_code: str, cap_value: int) -> None:
    """A platform-default (tenant_id IS NULL) entitlement_cap_config row — the same posture
    every other config table here ships (N2/§7 rule 2), written as metrion_migrate never as
    the application role."""
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entitlement_cap_config
                  (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
                VALUES
                  (:id, NULL, :agent_code, :meter_code, 'TENANT', 'MONTH', :cap_value, :effective_from, 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "cap_value": cap_value,
                "effective_from": _AS_OF,
            },
        )


def test_resolve_cfo_entitlement_with_zero_seeded_config_is_no_cap_configured(two_tenants):
    """T1: today's real, universal state — no entitlement_cap_config row exists anywhere."""
    tenant_a, _ = two_tenants
    result = resolve_cfo_entitlement(
        tenant_a, direct_action_code="cfo.pricing", occurred_at=_OCCURRED_AT, as_of_date=_AS_OF
    )
    assert result.evaluation_basis == "NO_CAP_CONFIGURED"
    assert result.passed is True
    assert result.cap_value is None
    assert result.usage_count == 0


def test_resolve_cfo_entitlement_over_cap_denies_once_usage_exceeds_seeded_cap(
    two_tenants, migrate_engine
):
    """T2/T3: seed a platform-default cap, write enough metered_event rows via
    insert_metered_event to exceed it, confirm OVER_CAP/passed=False."""
    tenant_a, _ = two_tenants
    meter_code = "cfo.pricing"
    _seed_platform_cap(migrate_engine, agent_code="CFO", meter_code=meter_code, cap_value=2)

    for i in range(2):
        entitlement_repo.insert_metered_event(
            tenant_a,
            member_id=None,
            agent_code="CFO",
            event_kind="cfo.pricing",
            meter_code=meter_code,
            quantity=1,
            agent_run_id=None,
            source_ref=None,
            idempotency_key=f"idem-{i}",
            occurred_at=_OCCURRED_AT,
            period_key="2026-09",
        )

    result = resolve_cfo_entitlement(
        tenant_a, direct_action_code="cfo.pricing", occurred_at=_OCCURRED_AT, as_of_date=_AS_OF
    )
    assert result.evaluation_basis == "OVER_CAP"
    assert result.passed is False
    assert result.usage_count == 2
    assert result.cap_value == 2


def test_resolve_cfo_entitlement_under_cap_passes_before_usage_reaches_it(two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    meter_code = "cfo.reconcile"
    _seed_platform_cap(migrate_engine, agent_code="CFO", meter_code=meter_code, cap_value=5)

    entitlement_repo.insert_metered_event(
        tenant_a,
        member_id=None,
        agent_code="CFO",
        event_kind="cfo.reconcile",
        meter_code=meter_code,
        quantity=1,
        agent_run_id=None,
        source_ref=None,
        idempotency_key="idem-only",
        occurred_at=_OCCURRED_AT,
        period_key="2026-09",
    )

    result = resolve_cfo_entitlement(
        tenant_a, direct_action_code="cfo.reconcile", occurred_at=_OCCURRED_AT, as_of_date=_AS_OF
    )
    assert result.evaluation_basis == "UNDER_CAP"
    assert result.passed is True
    assert result.usage_count == 1


def test_insert_metered_event_idempotency_key_retry_is_a_no_op(two_tenants):
    """AC4/T5: two calls with the same idempotency_key for the same tenant produce exactly
    one row, never an unhandled exception."""
    tenant_a, _ = two_tenants

    first_id = entitlement_repo.insert_metered_event(
        tenant_a,
        member_id=None,
        agent_code="CFO",
        event_kind="cfo.pnl",
        meter_code="cfo.pnl",
        quantity=1,
        agent_run_id=None,
        source_ref=None,
        idempotency_key="retry-key",
        occurred_at=_OCCURRED_AT,
        period_key="2026-09",
    )
    second_id = entitlement_repo.insert_metered_event(
        tenant_a,
        member_id=None,
        agent_code="CFO",
        event_kind="cfo.pnl",
        meter_code="cfo.pnl",
        quantity=1,
        agent_run_id=None,
        source_ref=None,
        idempotency_key="retry-key",
        occurred_at=_OCCURRED_AT,
        period_key="2026-09",
    )

    assert first_id == second_id
    with tenant_scope(tenant_a) as conn:
        count = conn.execute(
            text("SELECT count(*) FROM metered_event WHERE tenant_id = :t AND idempotency_key = 'retry-key'"),
            {"t": str(tenant_a)},
        ).scalar_one()
    assert count == 1


def test_metered_event_meter_map_fallback_when_no_mapping_row_exists(two_tenants):
    """E5/T6: meter_code falls back to the event_kind itself, never dropped."""
    tenant_a, _ = two_tenants
    result = resolve_cfo_entitlement(
        tenant_a, direct_action_code="cfo.batch_size", occurred_at=_OCCURRED_AT, as_of_date=_AS_OF
    )
    assert result.meter_code == "cfo.batch_size"


def test_active_cart_item_returns_none_when_no_row_exists(two_tenants):
    """`active_cart_item` is built for completeness (E6) but not yet wired into
    resolve_cfo_entitlement — proven correct in isolation only, per F2's explicit scope."""
    tenant_a, _ = two_tenants
    assert entitlement_repo.active_cart_item(tenant_a, agent_code="CFO") is None


def test_active_cart_item_returns_the_active_row(two_tenants):
    tenant_a, _ = two_tenants
    with tenant_scope(tenant_a) as conn:
        conn.execute(
            text(
                """
                INSERT INTO tenant_cart_item
                  (id, tenant_id, agent_code, tier, status, started_at, source)
                VALUES
                  (:id, :tenant_id, 'CFO', 'FREE', 'ACTIVE', now(), 'SIGNUP_DEFAULT')
                """
            ),
            {"id": str(uuid.uuid4()), "tenant_id": str(tenant_a)},
        )

    row = entitlement_repo.active_cart_item(tenant_a, agent_code="CFO")
    assert row is not None
    assert row["tier"] == "FREE"
    assert row["status"] == "ACTIVE"


def test_rls_isolation_on_metered_event(two_tenants):
    tenant_a, tenant_b = two_tenants
    entitlement_repo.insert_metered_event(
        tenant_a,
        member_id=None,
        agent_code="CFO",
        event_kind="cfo.pnl",
        meter_code="cfo.pnl",
        quantity=1,
        agent_run_id=None,
        source_ref=None,
        idempotency_key="rls-a",
        occurred_at=_OCCURRED_AT,
        period_key="2026-09",
    )
    entitlement_repo.insert_metered_event(
        tenant_b,
        member_id=None,
        agent_code="CFO",
        event_kind="cfo.pnl",
        meter_code="cfo.pnl",
        quantity=1,
        agent_run_id=None,
        source_ref=None,
        idempotency_key="rls-b",
        occurred_at=_OCCURRED_AT,
        period_key="2026-09",
    )

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT tenant_id FROM metered_event")).fetchall()
    assert [r[0] for r in rows] == [tenant_a]

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT tenant_id FROM metered_event")).fetchall()
    assert [r[0] for r in rows] == [tenant_b]


def test_rls_isolation_on_tenant_cart_item(two_tenants):
    tenant_a, tenant_b = two_tenants
    for tid in (tenant_a, tenant_b):
        with tenant_scope(tid) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenant_cart_item
                      (id, tenant_id, agent_code, tier, status, started_at, source)
                    VALUES
                      (:id, :tenant_id, 'CFO', 'FREE', 'ACTIVE', now(), 'SIGNUP_DEFAULT')
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": str(tid)},
            )

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT tenant_id FROM tenant_cart_item")).fetchall()
    assert [r[0] for r in rows] == [tenant_a]
