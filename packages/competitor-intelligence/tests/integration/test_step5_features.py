"""Step 5 — snapshot/price-event history, per-URL alert overrides, tags, archiving, the
handoff payload and the digest aggregation, against a real Postgres. Reuses the same
research-session flow as `test_research_run_flow.py` rather than hand-inserting rows, so
these tests exercise the real write path, not a shortcut around it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from competitor_intelligence.delta.compute import is_stale
from competitor_intelligence.digest.build_weekly_digest import build_digest
from competitor_intelligence.direct_path.research_run import submit_research_session
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.handoff import build_ci_handoff_snapshot
from competitor_intelligence.repositories import (
    ci_digest_subscription_repo,
    competitor_price_event_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.types import Marketplace, Unavailable

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _make_url(tenant_id: uuid.UUID, url: str = "https://amazon.in/dp/fixture-step5"):
    added_by = uuid.uuid4()
    url_id = competitor_url_repo.create_url(tenant_id, marketplace=Marketplace.AMAZON, url=url, added_by=added_by)
    return url_id, added_by


def _research(tenant_id, url_id, requested_by, extractor, *, price: int, availability: str, when: datetime):
    image_ref = f"img-{when.isoformat()}"
    extractor.responses[image_ref] = ExtractionResult(
        fields=(
            ExtractedField("listed_price_paise", price),
            ExtractedField("availability", availability),
        )
    )
    return submit_research_session(
        tenant_id,
        requested_by=requested_by,
        competitor_url_id=url_id,
        image_refs=[image_ref],
        manual_fields=None,
        permission_check="PASS",
        entitlement_check="PASS",
        extractor=extractor,
        now=when,
    )


def test_snapshot_history_lists_newest_first(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    t0 = datetime.now(timezone.utc) - timedelta(days=2)
    t1 = t0 + timedelta(days=1)

    r0 = _research(tenant_id, url_id, requested_by, fake_extractor, price=100000, availability="IN_STOCK", when=t0)
    r1 = _research(tenant_id, url_id, requested_by, fake_extractor, price=90000, availability="IN_STOCK", when=t1)

    history = competitor_snapshot_repo.list_snapshots(tenant_id, url_id)

    assert [row["id"] for row in history] == [r1.snapshot_id, r0.snapshot_id]
    assert history[0]["listed_price_paise"] == 90000


def test_price_event_history_reflects_detected_change(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    t0 = datetime.now(timezone.utc) - timedelta(days=1)
    t1 = t0 + timedelta(hours=1)

    _research(tenant_id, url_id, requested_by, fake_extractor, price=100000, availability="IN_STOCK", when=t0)
    result = _research(tenant_id, url_id, requested_by, fake_extractor, price=80000, availability="IN_STOCK", when=t1)

    assert result.price_event_id is not None
    events = competitor_price_event_repo.list_events(tenant_id, url_id)
    assert len(events) == 1
    assert events[0]["direction"] == "DECREASE"
    assert events[0]["delta_paise"] == -20000


def test_per_url_price_threshold_override_takes_precedence(two_tenants, fake_extractor):
    """A 50% override means a 20% drop must NOT breach threshold, even though the tenant
    default (5%) would have flagged it."""
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    competitor_url_repo.set_alert_overrides(
        tenant_id, url_id, price_threshold_pct_override=Decimal("50.00"), alert_on_availability_change_override=None
    )
    t0 = datetime.now(timezone.utc) - timedelta(days=1)
    t1 = t0 + timedelta(hours=1)

    _research(tenant_id, url_id, requested_by, fake_extractor, price=100000, availability="IN_STOCK", when=t0)
    result = _research(tenant_id, url_id, requested_by, fake_extractor, price=80000, availability="IN_STOCK", when=t1)

    # 20% drop still emits an event (delta_paise != 0)...
    assert result.price_event_id is not None
    events = competitor_price_event_repo.list_events(tenant_id, url_id)
    # ...but does not breach the 50%-override threshold.
    assert events[0]["threshold_breached"] is False


def test_availability_alert_override_suppresses_threshold_breach(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    competitor_url_repo.set_alert_overrides(
        tenant_id, url_id, price_threshold_pct_override=None, alert_on_availability_change_override=False
    )
    t0 = datetime.now(timezone.utc) - timedelta(days=1)
    t1 = t0 + timedelta(hours=1)

    _research(tenant_id, url_id, requested_by, fake_extractor, price=100000, availability="IN_STOCK", when=t0)
    _research(tenant_id, url_id, requested_by, fake_extractor, price=100000, availability="OUT_OF_STOCK", when=t1)

    events = competitor_price_event_repo.list_events(tenant_id, url_id)
    assert events[0]["availability_change"] == "IN_TO_OUT"
    assert events[0]["threshold_breached"] is False


def test_set_tags_and_archive_url(two_tenants):
    tenant_id, _ = two_tenants
    url_id, added_by = _make_url(tenant_id)

    competitor_url_repo.set_tags(tenant_id, url_id, ["DIRECT_RIVAL", "ASPIRATIONAL"])
    urls = competitor_url_repo.get_by_ids(tenant_id, [url_id])
    assert set(urls[0]["tags"]) == {"DIRECT_RIVAL", "ASPIRATIONAL"}

    competitor_url_repo.archive_url(tenant_id, url_id)
    assert competitor_url_repo.get_by_ids(tenant_id, [url_id]) == []  # ACTIVE-only filter now excludes it


def test_handoff_payload_reflects_latest_snapshot_and_staleness(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_id, requested_by = _make_url(tenant_id)
    old = datetime.now(timezone.utc) - timedelta(days=10)

    _research(tenant_id, url_id, requested_by, fake_extractor, price=50000, availability="IN_STOCK", when=old)

    payload = build_ci_handoff_snapshot(tenant_id, url_id, now=datetime.now(timezone.utc))

    assert not isinstance(payload, Unavailable)
    assert payload.listed_price_paise == 50000
    assert payload.is_stale is True
    assert is_stale(old, now=datetime.now(timezone.utc)) is True


def test_handoff_payload_unavailable_when_no_research_yet(two_tenants):
    tenant_id, _ = two_tenants
    url_id, _ = _make_url(tenant_id)

    payload = build_ci_handoff_snapshot(tenant_id, url_id)

    assert isinstance(payload, Unavailable)


def test_digest_aggregates_price_events_across_competitors(two_tenants, fake_extractor):
    tenant_id, _ = two_tenants
    url_a, requested_by = _make_url(tenant_id, "https://amazon.in/dp/digest-a")
    url_b, _ = _make_url(tenant_id, "https://amazon.in/dp/digest-b")
    t0 = datetime.now(timezone.utc) - timedelta(days=3)
    t1 = t0 + timedelta(hours=1)

    _research(tenant_id, url_a, requested_by, fake_extractor, price=100000, availability="IN_STOCK", when=t0)
    _research(tenant_id, url_a, requested_by, fake_extractor, price=80000, availability="IN_STOCK", when=t1)
    _research(tenant_id, url_b, requested_by, fake_extractor, price=200000, availability="IN_STOCK", when=t0)
    _research(tenant_id, url_b, requested_by, fake_extractor, price=220000, availability="IN_STOCK", when=t1)

    summary = build_digest(tenant_id, since=t0 - timedelta(hours=1), until=datetime.now(timezone.utc))

    assert summary.competitors_with_activity == 2
    by_url = {e.competitor_url_id: e for e in summary.entries}
    assert by_url[url_a].price_decrease_count == 1
    assert by_url[url_b].price_increase_count == 1


def test_digest_empty_when_no_events_in_window(two_tenants):
    tenant_id, _ = two_tenants
    summary = build_digest(
        tenant_id, since=datetime.now(timezone.utc) - timedelta(days=7), until=datetime.now(timezone.utc)
    )
    assert summary.competitors_with_activity == 0
    assert summary.entries == ()


def test_digest_subscription_upsert_and_get(two_tenants):
    tenant_id, _ = two_tenants
    member_id = uuid.uuid4()

    assert ci_digest_subscription_repo.get_subscription(tenant_id, member_id) is None

    ci_digest_subscription_repo.upsert_subscription(tenant_id, member_id, frequency="WEEKLY")
    sub = ci_digest_subscription_repo.get_subscription(tenant_id, member_id)
    assert sub["frequency"] == "WEEKLY"
    assert sub["enabled"] is True

    ci_digest_subscription_repo.upsert_subscription(tenant_id, member_id, frequency="NONE", enabled=False)
    sub = ci_digest_subscription_repo.get_subscription(tenant_id, member_id)
    assert sub["frequency"] == "NONE"
    assert sub["enabled"] is False
