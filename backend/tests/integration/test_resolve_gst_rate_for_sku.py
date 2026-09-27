"""`resolve_gst_rate_for_sku` — OP13's three-tier GST rate-resolution order, against real
Postgres (deterministic-engine.md §7.2.1 `gst_rate_override` tier 0, §8.2.2 `hsn_gst_reference`
tier 2). Mirrors `test_cfo_gst_lookup_accept.py`'s own real-Postgres seeding conventions.

Covers:
1. A real `gst_rate_override` manual_adjustment (seeded via `accept_gst_lookup_result` itself,
   mirroring G4's own insert shape exactly) is picked over a real, seeded `hsn_gst_reference`
   row (HSN 8517, from the G1 migration seed) for the SKU it was created for.
2. A different SKU with no override, but a matching `hsn_code`, correctly falls through to the
   real `hsn_gst_reference` table.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from fractions import Fraction

import pytest
from sqlalchemy import text

from calc_engine.gst_lookup.types import GstLookupResult
from calc_engine.repositories import gst_lookup_repo

_NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
_AS_OF = date(2026, 9, 26)


@pytest.fixture(autouse=True)
def _clean_gst_tables(migrate_engine):
    """`gst_lookup_result` and `manual_adjustment` are calc-engine-owned tables, cleaned
    directly — `hsn_gst_reference` is platform-owned, seeded once by migration, and never
    cleaned (mirrors `test_cfo_gst_lookup_accept.py`'s own convention: real seed data is left
    alone, only tenant-owned rows this test itself creates are cleaned)."""
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM gst_lookup_result"))
        conn.execute(text("DELETE FROM manual_adjustment"))
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM gst_lookup_result"))
        conn.execute(text("DELETE FROM manual_adjustment"))


def _seed_real_override(tenant_id: uuid.UUID, *, sku: str, rate_pct: Fraction, hsn: str) -> None:
    """Mirrors G4's own insert shape exactly: a real `gst_lookup_result` row, accepted via the
    real `accept_gst_lookup_result` composition, never a hand-crafted manual_adjustment insert
    that might drift from what G4 actually writes."""
    from backend.services.cfo_actions import AcceptGstLookupRequest, accept_gst_lookup_result

    seeded = GstLookupResult(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        query_text=f"seed for {sku}",
        source_url="https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
        retrieved_at=_NOW,
        likely_rate_pct=rate_pct,
        likely_hsn=hsn,
        likely_category="mobile phones",
        source_title="GetSwipe",
    )
    gst_lookup_repo.save(tenant_id, seeded)
    outcome = accept_gst_lookup_result(
        tenant_id,
        AcceptGstLookupRequest(gst_lookup_result_id=seeded.id, sku=sku, accepted_by=uuid.uuid4(), accepted_at=_NOW),
    )
    assert outcome.manual_adjustment_id is not None


def test_composer_picks_override_over_hsn_reference_for_the_overridden_sku(two_tenants):
    from backend.services.cfo_actions import ResolvedGstRate, resolve_gst_rate_for_sku

    tenant_a, _ = two_tenants
    # Real seed data: HSN 8517 -> 18% in hsn_gst_reference (20260925_0007's own migration seed).
    # The override below deliberately uses a DIFFERENT rate (5%) so the test can prove which
    # tier actually won, not just that a number came back.
    _seed_real_override(tenant_a, sku="SKU-OVERRIDDEN", rate_pct=Fraction(5), hsn="8517")

    result = resolve_gst_rate_for_sku(
        tenant_a,
        sku="SKU-OVERRIDDEN",
        hsn_code="8517",
        observed_rate_pct=None,
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "OVERRIDE"
    assert result.rate_pct == Fraction(5)
    assert result.confidence == "MANUAL"
    assert result.manual_adjustment_id is not None


def test_composer_falls_through_to_hsn_reference_for_a_different_sku_with_no_override(two_tenants):
    from backend.services.cfo_actions import ResolvedGstRate, resolve_gst_rate_for_sku

    tenant_a, _ = two_tenants
    # An override exists for a DIFFERENT sku — must not leak into this SKU's resolution.
    _seed_real_override(tenant_a, sku="SKU-OVERRIDDEN", rate_pct=Fraction(5), hsn="8517")

    result = resolve_gst_rate_for_sku(
        tenant_a,
        sku="SKU-NO-OVERRIDE",
        hsn_code="8517",
        observed_rate_pct=None,
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "HSN_REFERENCE"
    assert result.rate_pct == Fraction(18)  # the real seeded hsn_gst_reference rate for 8517
    assert result.confidence == "PROVISIONAL"
    assert result.hsn_code_matched == "8517"
    assert result.hsn_reference_source_url is not None


def test_composer_returns_unresolved_when_no_override_no_hsn_match(two_tenants):
    from backend.services.cfo_actions import GstRateUnresolved, resolve_gst_rate_for_sku

    tenant_a, _ = two_tenants

    result = resolve_gst_rate_for_sku(
        tenant_a,
        sku="SKU-NOTHING",
        hsn_code="0000000",  # no seeded hsn_gst_reference row matches this
        observed_rate_pct=None,
        as_of_date=_AS_OF,
    )

    assert isinstance(result, GstRateUnresolved)
    assert result.sku == "SKU-NOTHING"
