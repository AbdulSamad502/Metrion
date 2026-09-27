"""gst_lookup_repo (§8.4 / §8.4.1) against a real Postgres — migration application, RLS
isolation, and the TTL-based cache-hit/cache-miss behaviour (L6). Mirrors
`test_reconciliation_tables.py`/`test_hsn_gst_reference_config_repo.py`'s conventions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import pytest
from sqlalchemy import inspect, text

from calc_engine.gst_lookup.types import GstLookupResult
from calc_engine.repositories import gst_lookup_repo
from calc_engine.repositories.tenant_context import tenant_scope

_NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def _make_result(tenant_id: uuid.UUID, *, retrieved_at: datetime, query_text: str = "Mobile phone") -> GstLookupResult:
    return GstLookupResult(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        query_text=query_text,
        source_url="https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
        retrieved_at=retrieved_at,
        likely_rate_pct=Fraction(18),
        likely_hsn="8517",
        likely_category="mobile phones",
        source_title="GetSwipe",
    )


def test_migration_applied_table_and_rls_policy_exist(migrate_engine):
    inspector = inspect(migrate_engine)
    assert "gst_lookup_result" in inspector.get_table_names()

    with migrate_engine.connect() as conn:
        forced = conn.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'gst_lookup_result'"
            )
        ).scalar()
    assert forced is True

    with migrate_engine.connect() as conn:
        policy = conn.execute(
            text(
                "SELECT policyname FROM pg_policies WHERE tablename = 'gst_lookup_result' "
                "AND policyname = 'tenant_isolation'"
            )
        ).first()
    assert policy is not None


def test_save_inserts_a_row_readable_by_the_same_tenant(two_tenants):
    tenant_a, _ = two_tenants
    result = _make_result(tenant_a, retrieved_at=_NOW)

    saved_id = gst_lookup_repo.save(tenant_a, result)
    assert saved_id == result.id

    with tenant_scope(tenant_a) as conn:
        row = conn.execute(
            text("SELECT id, likely_rate_pct, source_url FROM gst_lookup_result WHERE id = :id"),
            {"id": str(result.id)},
        ).first()
    assert row is not None
    assert str(row.id) == str(result.id)
    assert row.likely_rate_pct == pytest.approx(18.0)


def test_rls_isolation_row_invisible_to_other_tenant(two_tenants):
    tenant_a, tenant_b = two_tenants
    result = _make_result(tenant_a, retrieved_at=_NOW)
    gst_lookup_repo.save(tenant_a, result)

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT id FROM gst_lookup_result")).fetchall()
    assert len(rows) == 1

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT id FROM gst_lookup_result")).fetchall()
    assert rows == []


def test_save_is_append_only_never_mutates_a_prior_row(two_tenants):
    """§8.4.1's L6 mechanism: a second lookup for the same query inserts a NEW row; the first
    row is retained unchanged."""
    tenant_a, _ = two_tenants
    first = _make_result(tenant_a, retrieved_at=_NOW - timedelta(days=20))
    second = _make_result(tenant_a, retrieved_at=_NOW)

    gst_lookup_repo.save(tenant_a, first)
    gst_lookup_repo.save(tenant_a, second)

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(
            text("SELECT id FROM gst_lookup_result WHERE query_text = :q ORDER BY retrieved_at"),
            {"q": "Mobile phone"},
        ).fetchall()
    assert len(rows) == 2
    assert {str(r.id) for r in rows} == {str(first.id), str(second.id)}


def test_find_cached_returns_none_when_no_row_exists(two_tenants):
    tenant_a, _ = two_tenants
    assert gst_lookup_repo.find_cached(tenant_a, query_text="Nothing seeded", now=_NOW) is None


def test_find_cached_cache_hit_within_ttl(two_tenants):
    tenant_a, _ = two_tenants
    fresh = _make_result(tenant_a, retrieved_at=_NOW - timedelta(days=3))
    gst_lookup_repo.save(tenant_a, fresh)

    cached = gst_lookup_repo.find_cached(tenant_a, query_text="Mobile phone", now=_NOW)
    assert cached is not None
    assert str(cached["id"]) == str(fresh.id)


def test_find_cached_cache_miss_past_the_14_day_ttl(two_tenants):
    tenant_a, _ = two_tenants
    stale = _make_result(tenant_a, retrieved_at=_NOW - timedelta(days=15))
    gst_lookup_repo.save(tenant_a, stale)

    cached = gst_lookup_repo.find_cached(tenant_a, query_text="Mobile phone", now=_NOW)
    assert cached is None


def test_find_cached_picks_the_most_recent_row_when_several_exist(two_tenants):
    tenant_a, _ = two_tenants
    older = _make_result(tenant_a, retrieved_at=_NOW - timedelta(days=10))
    newer = _make_result(tenant_a, retrieved_at=_NOW - timedelta(days=1))
    gst_lookup_repo.save(tenant_a, older)
    gst_lookup_repo.save(tenant_a, newer)

    cached = gst_lookup_repo.find_cached(tenant_a, query_text="Mobile phone", now=_NOW)
    assert cached is not None
    assert str(cached["id"]) == str(newer.id)


def test_find_cached_scoped_by_tenant(two_tenants):
    tenant_a, tenant_b = two_tenants
    gst_lookup_repo.save(tenant_a, _make_result(tenant_a, retrieved_at=_NOW))

    assert gst_lookup_repo.find_cached(tenant_b, query_text="Mobile phone", now=_NOW) is None
