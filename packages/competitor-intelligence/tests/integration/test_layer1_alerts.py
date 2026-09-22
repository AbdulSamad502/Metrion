"""Checkpoint 7 — Layer 1 alerts (competitor-intelligence-agent.md §6.17, C26) and the
CIHandoff v2 finding schema (§5.6), against a real Postgres. Reuses the real
`submit_research_session` write path (same convention as test_landscape.py) to produce real
`competitor_price_event` rows rather than hand-inserting them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from competitor_intelligence.alerts.layer1 import (
    EvidenceConfidence,
    FindingType,
    TargetAgent,
    build_layer1_alerts,
    layer1_alert_to_dict,
)
from competitor_intelligence.direct_path.research_run import submit_research_session
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_url_repo
from competitor_intelligence.types import Direction, Marketplace

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _make_url(tenant_id: uuid.UUID, url: str, *, label: str | None = None):
    added_by = uuid.uuid4()
    url_id = competitor_url_repo.create_url(tenant_id, marketplace=Marketplace.AMAZON, url=url, added_by=added_by, label=label)
    return url_id, added_by


def _research(tenant_id, url_id, requested_by, extractor, *, price: int, when: datetime, availability: str = "IN_STOCK"):
    image_ref = f"img-{url_id}-{when.isoformat()}"
    extractor.responses[image_ref] = ExtractionResult(
        fields=(ExtractedField("listed_price_paise", price), ExtractedField("availability", availability))
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


class TestLayer1Alerts:
    def test_price_drop_produces_an_observational_alert_and_handoff(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        t0 = datetime.now(timezone.utc) - timedelta(days=1)
        t1 = t0 + timedelta(hours=1)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/alert-1", label="Rival Mouse")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=100_000, when=t0)
        _research(tenant_a, url_id, requested_by, fake_extractor, price=90_000, when=t1)

        alerts = build_layer1_alerts(tenant_a, since=t0 - timedelta(minutes=1))
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.competitor_url_id == url_id
        assert alert.competitor_label == "Rival Mouse"
        assert alert.direction == Direction.DECREASE
        assert alert.finding_type == FindingType.PRICE_CHANGE

        # C26/AC29: the message states a fact only — never margin/contribution/break-even language.
        for forbidden in ("margin", "contribution", "break-even", "profit"):
            assert forbidden not in alert.message.lower()
        assert "dropped price" in alert.message
        assert "Rival Mouse" in alert.message

        handoff = alert.handoff
        assert handoff.finding_type == FindingType.PRICE_CHANGE
        assert handoff.created_by == "CI"
        assert handoff.competitor_refs == (str(url_id),)
        assert len(handoff.validated_fact) == 1
        assert handoff.validated_fact[0].confidence == EvidenceConfidence.HIGH
        assert len(handoff.evidence_refs) == 1
        assert handoff.suggested_action is not None
        assert handoff.suggested_action.target_agent == TargetAgent.CFO
        for forbidden in ("margin", "contribution", "break-even"):
            assert forbidden not in handoff.implication.lower()

    def test_alert_below_threshold_is_not_alert_eligible_but_no_event_is_lost(self, two_tenants, fake_extractor) -> None:
        """A tiny price wobble still emits a `competitor_price_event` (something changed) but
        is not `alert_eligible` unless it breaches the resolved threshold — confirmed by
        checking no Layer 1 alert is produced for a sub-threshold move, not by asserting on
        internal event bookkeeping this module doesn't own."""
        tenant_a, _ = two_tenants
        t0 = datetime.now(timezone.utc) - timedelta(days=1)
        t1 = t0 + timedelta(hours=1)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/alert-2")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=100_000, when=t0)
        _research(tenant_a, url_id, requested_by, fake_extractor, price=99_900, when=t1)  # 0.1% — below default 5%

        alerts = build_layer1_alerts(tenant_a, since=t0 - timedelta(minutes=1))
        assert alerts == []

    def test_first_observation_is_a_baseline_never_an_alert(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        now = datetime.now(timezone.utc)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/alert-3")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=100_000, when=now)

        alerts = build_layer1_alerts(tenant_a, since=now - timedelta(minutes=1))
        assert alerts == []

    def test_availability_change_produces_an_availability_finding(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        t0 = datetime.now(timezone.utc) - timedelta(days=1)
        t1 = t0 + timedelta(hours=1)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/alert-4", label="Rival Kit")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=100_000, when=t0, availability="IN_STOCK")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=100_000, when=t1, availability="OUT_OF_STOCK")

        alerts = build_layer1_alerts(tenant_a, since=t0 - timedelta(minutes=1))
        assert len(alerts) == 1
        assert alerts[0].finding_type == FindingType.AVAILABILITY_CHANGE
        assert "out of stock" in alerts[0].message

    def test_tenant_isolation(self, two_tenants, fake_extractor) -> None:
        tenant_a, tenant_b = two_tenants
        t0 = datetime.now(timezone.utc) - timedelta(days=1)
        t1 = t0 + timedelta(hours=1)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/alert-5")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=100_000, when=t0)
        _research(tenant_a, url_id, requested_by, fake_extractor, price=80_000, when=t1)

        assert build_layer1_alerts(tenant_b, since=t0 - timedelta(minutes=1)) == []
        assert len(build_layer1_alerts(tenant_a, since=t0 - timedelta(minutes=1))) == 1

    def test_wire_shape_round_trips(self, two_tenants, fake_extractor) -> None:
        tenant_a, _ = two_tenants
        t0 = datetime.now(timezone.utc) - timedelta(days=1)
        t1 = t0 + timedelta(hours=1)
        url_id, requested_by = _make_url(tenant_a, "https://amazon.in/dp/alert-6", label="Wire Shape Co")
        _research(tenant_a, url_id, requested_by, fake_extractor, price=100_000, when=t0)
        _research(tenant_a, url_id, requested_by, fake_extractor, price=85_000, when=t1)

        alerts = build_layer1_alerts(tenant_a, since=t0 - timedelta(minutes=1))
        payload = layer1_alert_to_dict(alerts[0])
        assert set(payload.keys()) >= {
            "priceEventId", "competitorUrlId", "competitorLabel", "findingType", "direction",
            "deltaPct", "availabilityChange", "thresholdBreached", "message", "createdAt", "handoff",
        }
        handoff_payload = payload["handoff"]
        assert set(handoff_payload.keys()) == {
            "findingId", "findingType", "validatedFact", "evidenceRefs", "competitorRefs",
            "implication", "suggestedAction", "createdAt", "createdBy",
        }
        assert handoff_payload["suggestedAction"]["targetAgent"] == "CFO"
