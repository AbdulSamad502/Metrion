"""resolve_fee_reference (§5.14) against a real Postgres — resolution order (latest
effective_from wins, effective_to gates the upper bound, exact (marketplace, category,
fee_type) match only) is proven here, not assumed from the SQL alone.

fee_reference is platform-owned (no tenant_id column, no RLS policy) and metrion_app only
has SELECT on it (see migrations/versions/20260917_0001_engine_tables.py) — seeding is a
metrion_migrate-run data migration in production, so this test seeds/cleans up via
migrate_engine (DATABASE_URL), the table owner, exactly like conftest.py's
_clean_engine_tables does for the other engine-owned tables.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from calc_engine.repositories.config_repo import resolve_fee_reference


@pytest.fixture(autouse=True)
def _clean_fee_reference(migrate_engine):
    """fee_reference isn't in conftest.py's _clean_engine_tables list (it's out of scope for
    every other test file) — clean up explicitly here so this file leaves no residual rows."""
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM fee_reference"))
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM fee_reference"))


def _insert_fee_reference(
    migrate_engine,
    *,
    marketplace,
    category,
    fee_type,
    rate_pct=None,
    effective_from="2026-01-01",
    effective_to=None,
    version=1,
):
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fee_reference
                    (id, marketplace, category, fee_type, rate_pct, effective_from, effective_to,
                     source, confidence, version, last_verified_at)
                VALUES
                    (:id, :marketplace, :category, :fee_type, :rate_pct, :effective_from, :effective_to,
                     'test fixture', 'VERIFIED', :version, now())
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "marketplace": marketplace,
                "category": category,
                "fee_type": fee_type,
                "rate_pct": rate_pct,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "version": version,
            },
        )


def test_latest_effective_from_wins_among_overlapping_rows(migrate_engine, two_tenants):
    tenant_a, _ = two_tenants
    _insert_fee_reference(
        migrate_engine,
        marketplace="AMAZON",
        category="ELECTRONICS",
        fee_type="COMMISSION",
        rate_pct="10.0000",
        effective_from="2026-01-01",
        version=1,
    )
    _insert_fee_reference(
        migrate_engine,
        marketplace="AMAZON",
        category="ELECTRONICS",
        fee_type="COMMISSION",
        rate_pct="12.5000",
        effective_from="2026-06-01",
        version=2,
    )

    row = resolve_fee_reference(
        tenant_a, marketplace="AMAZON", category="ELECTRONICS", fee_type="COMMISSION", as_of_date=date(2026, 9, 17)
    )
    assert row is not None
    assert row["version"] == 2
    assert row["rate_pct"] == pytest.approx(12.5)


def test_non_matching_marketplace_category_fee_type_excluded(migrate_engine, two_tenants):
    tenant_a, _ = two_tenants
    _insert_fee_reference(
        migrate_engine,
        marketplace="FLIPKART",
        category="APPAREL",
        fee_type="COMMISSION",
        rate_pct="8.0000",
        effective_from="2026-01-01",
    )

    row = resolve_fee_reference(
        tenant_a, marketplace="AMAZON", category="ELECTRONICS", fee_type="COMMISSION", as_of_date=date(2026, 9, 17)
    )
    assert row is None


def test_missing_combination_returns_none(migrate_engine, two_tenants):
    tenant_a, _ = two_tenants
    row = resolve_fee_reference(
        tenant_a, marketplace="MEESHO", category="HOME", fee_type="COMMISSION", as_of_date=date(2026, 9, 17)
    )
    assert row is None


def test_effective_to_gates_a_lapsed_row(migrate_engine, two_tenants):
    tenant_a, _ = two_tenants
    _insert_fee_reference(
        migrate_engine,
        marketplace="MEESHO",
        category="HOME",
        fee_type="SHIPPING",
        rate_pct="5.0000",
        effective_from="2026-01-01",
        effective_to="2026-03-31",
        version=1,
    )

    row = resolve_fee_reference(
        tenant_a, marketplace="MEESHO", category="HOME", fee_type="SHIPPING", as_of_date=date(2026, 9, 17)
    )
    assert row is None  # excluded: effective_to already passed

    row_in_window = resolve_fee_reference(
        tenant_a, marketplace="MEESHO", category="HOME", fee_type="SHIPPING", as_of_date=date(2026, 2, 1)
    )
    assert row_in_window is not None
    assert row_in_window["version"] == 1
