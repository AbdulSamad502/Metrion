"""CMO entitlement + metering against a real Postgres (docs/specs/slim-cmo-agent.md §8,
entitlement.md rules 3-6). This is the first test of usage actually being WRITTEN by the
code path an agent will use, and then BINDING a cap — before this, only tests inserted
`metered_event` rows directly."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import text

from backend.tenant_context import tenant_scope
from backend.entitlement import (
    cmo_metering_key,
    record_metered_event,
    resolve_cmo_entitlement,
    resolve_market_trends_entitlement,
)

_AS_OF = date(2026, 10, 3)
_NOW = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)


def _seed_cap(migrate_engine, *, agent_code, meter_code, cap_value, period_unit="MONTH"):
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entitlement_cap_config
                  (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
                VALUES (:id, NULL, :a, :m, 'TENANT', :u, :c, :e, 1)
                """
            ),
            {"id": str(uuid.uuid4()), "a": agent_code, "m": meter_code, "u": period_unit, "c": cap_value, "e": _AS_OF},
        )


def _record(tenant, *, kind="cmo.generate_title_sets", key=None, agent="CMO", at=_NOW):
    return record_metered_event(
        tenant, agent_code=agent, event_kind=kind, idempotency_key=key or cmo_metering_key(uuid.uuid4()),
        occurred_at=at, as_of_date=_AS_OF,
    )


def _check(tenant, kind="cmo.generate_title_sets"):
    return resolve_cmo_entitlement(tenant, direct_action_code=kind, occurred_at=_NOW, as_of_date=_AS_OF)


def test_no_cap_configured_passes_and_says_so(two_tenants):
    tenant, _ = two_tenants
    result = _check(tenant)
    assert (result.evaluation_basis, result.passed, result.cap_value) == ("NO_CAP_CONFIGURED", True, None)


def test_recorded_units_are_counted_and_a_seeded_cap_then_binds(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    _seed_cap(migrate_engine, agent_code="CMO", meter_code="cmo.generate_title_sets", cap_value=2)

    assert _check(tenant).passed is True
    assert _record(tenant) is not None
    assert _check(tenant).passed is True and _check(tenant).usage_count == 1
    assert _record(tenant) is not None

    denied = _check(tenant)
    assert denied.passed is False
    assert (denied.evaluation_basis, denied.usage_count, denied.cap_value) == ("OVER_CAP", 2, 2)


def test_idempotent_retry_never_double_counts(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    _seed_cap(migrate_engine, agent_code="CMO", meter_code="cmo.generate_title_sets", cap_value=5)
    key = cmo_metering_key(uuid.uuid4())
    first = _record(tenant, key=key)
    again = _record(tenant, key=key)
    assert first is not None and first == again, "a retried write returns the ORIGINAL event id"
    assert _check(tenant).usage_count == 1


def test_one_tenants_usage_never_counts_against_another(two_tenants, migrate_engine):
    tenant_a, tenant_b = two_tenants
    _seed_cap(migrate_engine, agent_code="CMO", meter_code="cmo.generate_title_sets", cap_value=1)
    _record(tenant_a)
    assert _check(tenant_a).passed is False
    assert _check(tenant_b).passed is True and _check(tenant_b).usage_count == 0


def test_meters_are_per_action_so_a_title_cap_does_not_block_listing_copy(two_tenants, migrate_engine):
    tenant, _ = two_tenants
    _seed_cap(migrate_engine, agent_code="CMO", meter_code="cmo.generate_title_sets", cap_value=1)
    _record(tenant, kind="cmo.generate_title_sets")
    assert _check(tenant, "cmo.generate_title_sets").passed is False
    assert _check(tenant, "cmo.generate_listing_copy").passed is True


def test_shared_trend_meter_is_independent_of_the_cmo_meter(two_tenants, migrate_engine):
    """AC17: two independent meters — exhausting one never denies the other."""
    tenant, _ = two_tenants
    _seed_cap(migrate_engine, agent_code="SHARED", meter_code="research.market_trends", cap_value=1)
    _seed_cap(migrate_engine, agent_code="CMO", meter_code="cmo.market_trends", cap_value=10)

    _record(tenant, kind="research.market_trends", agent="SHARED")
    trends = resolve_market_trends_entitlement(tenant, occurred_at=_NOW, as_of_date=_AS_OF)
    assert trends.passed is False and trends.evaluation_basis == "OVER_CAP"
    assert _check(tenant, "cmo.market_trends").passed is True, "CMO's own meter is untouched"

    _record(tenant, kind="cmo.market_trends")
    assert resolve_market_trends_entitlement(tenant, occurred_at=_NOW, as_of_date=_AS_OF).passed is False


def test_day_cap_records_and_counts_the_same_bucket(two_tenants, migrate_engine):
    """Recorder and check must agree on the period unit, or a DAY cap would never bind."""
    tenant, _ = two_tenants
    _seed_cap(migrate_engine, agent_code="CMO", meter_code="cmo.generate_hashtags", cap_value=1, period_unit="DAY")
    _record(tenant, kind="cmo.generate_hashtags")
    denied = _check(tenant, "cmo.generate_hashtags")
    assert denied.passed is False and denied.period_key == "2026-10-03"


def test_event_row_carries_the_resolved_meter_period_and_unit(two_tenants):
    tenant, _ = two_tenants
    event_id = _record(tenant, kind="cmo.generate_description", key="cmo:row-check")
    # Read as the application role through tenant_scope (RLS in force). Not via the pooled
    # migrate engine: set_config() leaves '' on a pooled connection, which would break the
    # platform-config cleanup that runs on the same pool.
    with tenant_scope(tenant) as conn:
        row = conn.execute(
            text("SELECT agent_code, event_kind, meter_code, quantity, period_key FROM metered_event WHERE id = :i"),
            {"i": str(event_id)},
        ).one()
    assert tuple(row) == ("CMO", "cmo.generate_description", "cmo.generate_description", 1, "2026-10")


def test_write_failure_returns_none_and_does_not_raise():
    """A metering failure (here: a tenant that does not exist, so the FK rejects the insert)
    must never propagate to the caller — the seller's result was already delivered (D4)."""
    assert _record(uuid.uuid4()) is None


def test_concurrent_recordings_of_one_artefact_yield_one_event_and_one_unit(two_tenants, migrate_engine):
    """24 threads record the SAME artefact at once (a retry storm): exactly one stored event,
    every caller gets its id, no caller sees a failure, and it counts as ONE unit."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    tenant, _ = two_tenants
    key = cmo_metering_key(uuid.uuid4())
    barrier = threading.Barrier(24)

    def go(_):
        barrier.wait()
        return _record(tenant, key=key)

    with ThreadPoolExecutor(24) as pool:
        ids = list(pool.map(go, range(24)))
    assert None not in ids and len(set(ids)) == 1
    assert _usage(tenant, "cmo.generate_title_sets") == 1


def test_concurrent_distinct_artefacts_are_all_counted_none_lost(two_tenants):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    tenant, _ = two_tenants
    barrier = threading.Barrier(24)

    def go(_):
        barrier.wait()
        return _record(tenant)

    with ThreadPoolExecutor(24) as pool:
        ids = list(pool.map(go, range(24)))
    assert None not in ids and len(set(ids)) == 24
    assert _usage(tenant, "cmo.generate_title_sets") == 24


def _usage(tenant, meter):
    """Real aggregated usage for the period. NOTE: `resolve_cmo_entitlement(...).usage_count` is
    0 whenever no cap is configured (existing F2 behaviour - usage is only aggregated against a
    cap), so a usage display (P9) must call the repository directly, as here."""
    from backend.repositories import entitlement_repo

    return entitlement_repo.usage_count_for_period(tenant, agent_code="CMO", meter_code=meter, period_key="2026-10")
