"""resolve_hsn_gst_reference (§8.2.2) against a real Postgres — the prefix-matching rule
(exact match, longest-prefix-wins, effective_to gating, and the "queried code shorter than
every candidate" -> None case) is proven here, not assumed from the SQL alone. Covers spec
§13's T35-T39.

hsn_gst_reference is platform-owned (no tenant_id column, no RLS policy) and metrion_app only
has SELECT on it (see migrations/versions/20260925_0007_hsn_gst_reference.py) — seeding is a
metrion_migrate-run data migration in production, so test-fixture rows are inserted/cleaned up
via migrate_engine (DATABASE_URL), the table owner, exactly like
test_fee_reference_config_repo.py does for fee_reference.

The table is NOT empty by default in this environment (migration 20260925_0007 seeds 15 real
rows) — unlike fee_reference. Test-fixture rows below use hsn_code prefixes ("77", "99...")
deliberately outside the real seeded set, and cleanup deletes only rows this file itself
inserted (by source_url = 'test fixture'), so the real seed data is never disturbed.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from calc_engine.repositories.config_repo import resolve_hsn_gst_reference


@pytest.fixture(autouse=True)
def _clean_hsn_gst_reference_fixtures(migrate_engine):
    """Deletes only test-fixture rows (source_url = 'test fixture') — the real seeded rows
    from migration 20260925_0007 are never touched by this file."""
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM hsn_gst_reference WHERE source_url = 'test fixture'"))
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM hsn_gst_reference WHERE source_url = 'test fixture'"))


def _insert_hsn_row(
    migrate_engine,
    *,
    hsn_code,
    description="test row",
    rate_pct="18.0000",
    effective_from="2026-01-01",
    effective_to=None,
    version=1,
):
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO hsn_gst_reference
                    (id, hsn_code, description, rate_pct, source_url, source_title,
                     retrieved_at, effective_from, effective_to, version, confidence)
                VALUES
                    (:id, :hsn_code, :description, :rate_pct, 'test fixture', 'test fixture',
                     now(), :effective_from, :effective_to, :version, 'PROVISIONAL')
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "hsn_code": hsn_code,
                "description": description,
                "rate_pct": rate_pct,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "version": version,
            },
        )


def test_t35_exact_match_resolution(migrate_engine, two_tenants):
    """T35: line with no observed GST rate; queried hsn_code exactly matches a seeded row
    effective as of as_of_date -> resolved."""
    tenant_a, _ = two_tenants
    _insert_hsn_row(migrate_engine, hsn_code="77011000", rate_pct="12.0000")

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="77011000", as_of_date=date(2026, 9, 25))
    assert row is not None
    assert row["hsn_code"] == "77011000"
    assert row["rate_pct"] == pytest.approx(12.0)


def test_t36_prefix_match_resolution_8_digit_query_against_4_digit_row(migrate_engine, two_tenants):
    """T36: line queried with an 8-digit hsn_code; table holds only a 4-digit chapter-level
    row as a prefix -> the 4-digit row matches by prefix rule 1."""
    tenant_a, _ = two_tenants
    _insert_hsn_row(migrate_engine, hsn_code="7701", rate_pct="12.0000")

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="77011000", as_of_date=date(2026, 9, 25))
    assert row is not None
    assert row["hsn_code"] == "7701"
    assert row["rate_pct"] == pytest.approx(12.0)


def test_longest_prefix_wins_among_multiple_matching_candidates(migrate_engine, two_tenants):
    """§8.2.2 matching rule 2: the longest (most specific) matching prefix wins."""
    tenant_a, _ = two_tenants
    _insert_hsn_row(migrate_engine, hsn_code="77", rate_pct="5.0000")
    _insert_hsn_row(migrate_engine, hsn_code="7701", rate_pct="12.0000")
    _insert_hsn_row(migrate_engine, hsn_code="770110", rate_pct="18.0000")

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="77011000", as_of_date=date(2026, 9, 25))
    assert row is not None
    assert row["hsn_code"] == "770110"
    assert row["rate_pct"] == pytest.approx(18.0)


def test_ties_broken_by_latest_effective_from(migrate_engine, two_tenants):
    """§8.2.2 matching rule 2: ties on prefix length broken by latest effective_from."""
    tenant_a, _ = two_tenants
    _insert_hsn_row(migrate_engine, hsn_code="7701", rate_pct="5.0000", effective_from="2026-01-01", version=1)
    _insert_hsn_row(migrate_engine, hsn_code="7701", rate_pct="12.0000", effective_from="2026-06-01", version=2)

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="77011000", as_of_date=date(2026, 9, 25))
    assert row is not None
    assert row["version"] == 2
    assert row["rate_pct"] == pytest.approx(12.0)


def test_t37_queried_code_shorter_than_every_candidate_returns_none(migrate_engine, two_tenants):
    """T37: line queried with a 2-digit hsn_code; table holds only 6- and 8-digit rows under
    that chapter -> None returned — queried code shorter than every candidate row
    (§8.2.2 matching rule 4); this is the easiest case to get wrong, tested explicitly."""
    tenant_a, _ = two_tenants
    _insert_hsn_row(migrate_engine, hsn_code="770110", rate_pct="12.0000")
    _insert_hsn_row(migrate_engine, hsn_code="77011000", rate_pct="18.0000")

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="77", as_of_date=date(2026, 9, 25))
    assert row is None


def test_effective_to_gates_a_lapsed_row(migrate_engine, two_tenants):
    tenant_a, _ = two_tenants
    _insert_hsn_row(
        migrate_engine,
        hsn_code="7701",
        rate_pct="5.0000",
        effective_from="2026-01-01",
        effective_to="2026-03-31",
        version=1,
    )

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="77011000", as_of_date=date(2026, 9, 25))
    assert row is None  # excluded: effective_to already passed

    row_in_window = resolve_hsn_gst_reference(tenant_a, hsn_code="77011000", as_of_date=date(2026, 2, 1))
    assert row_in_window is not None
    assert row_in_window["version"] == 1


def test_t39_no_matching_row_at_all_returns_none(migrate_engine, two_tenants):
    """T39-style logical/config-gap check: a hsn_code genuinely not present in the (non-empty,
    seeded) table falls through to None cleanly, exactly as it would if the table were empty
    (C15) — no rate is ever guessed in the gap."""
    tenant_a, _ = two_tenants

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="1234", as_of_date=date(2026, 9, 25))
    assert row is None


def test_t38_style_seeded_real_data_resolves_for_a_known_code(migrate_engine, two_tenants):
    """Sanity check against the real seed data from migration 20260925_0007 — confirms the
    seeded rows are actually resolvable through the same resolver, not just fixture rows."""
    tenant_a, _ = two_tenants

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="85171200", as_of_date=date(2026, 9, 25))
    assert row is not None
    assert row["hsn_code"] == "8517"
    assert row["rate_pct"] == pytest.approx(18.0)
    assert row["confidence"] == "PROVISIONAL"


def test_never_applied_retroactively_before_effective_from(migrate_engine, two_tenants):
    """The real seeded rows carry effective_from = 2025-09-22 (GST 2.0 reform date) — querying
    before that date must not resolve them."""
    tenant_a, _ = two_tenants

    row = resolve_hsn_gst_reference(tenant_a, hsn_code="85171200", as_of_date=date(2025, 1, 1))
    assert row is None
