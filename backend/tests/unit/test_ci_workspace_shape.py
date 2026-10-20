"""CI spec §6.29 — what the read-only dashboard is told. Pure shaping; no database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.services.ci_workspace import price_status, shape_candidate, shape_competitor, shape_workspace
from competitor_intelligence.monitor.report import Freshness

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
URL = {"id": uuid4(), "label": "Titan Octane", "marketplace": "AMAZON"}
SNAP_ID = uuid4()


def _snap(age: timedelta, **kw):
    base = {"id": SNAP_ID, "captured_at": NOW - age, "listed_price_paise": 269900, "availability": "IN_STOCK", "rating": "4.2", "rating_count": 5400}
    base.update(kw)
    return base


def _shape(snapshot, *, pending=False, event=None, candidate=None, relevance=None):
    return shape_competitor(URL, candidate=candidate, relevance=relevance, snapshot=snapshot, pending_snapshot_exists=pending, event=event, open_questions=0, now=NOW)


def test_a_fresh_confirmed_snapshot_is_verified_and_states_its_price() -> None:
    c = _shape(_snap(timedelta(hours=3)))
    assert c["priceStatus"] == "VERIFIED" and c["freshness"] == "FRESH" and c["listedPricePaise"] == 269900


def test_a_snapshot_past_the_seven_day_ceiling_states_no_price_at_all() -> None:
    c = _shape(_snap(timedelta(days=9)))
    assert c["freshness"] == "UNAVAILABLE" and c["priceStatus"] == "UNAVAILABLE"
    assert c["listedPricePaise"] is None and c["availability"] is None and c["ratingValue"] is None  # never a stale number


def test_an_unconfirmed_price_is_unverified_and_not_shown() -> None:
    c = _shape(None, pending=True)
    assert c["priceStatus"] == "UNVERIFIED" and c["listedPricePaise"] is None


def test_no_evidence_is_unavailable() -> None:
    c = _shape(None)
    assert c["priceStatus"] == "UNAVAILABLE" and c["evidenceDate"] is None and c["freshness"] == "UNAVAILABLE"


def test_the_delta_is_shown_only_for_the_current_snapshot() -> None:
    ev = {"to_snapshot_id": SNAP_ID, "delta_pct": "-9.2", "direction": "DECREASE"}
    assert _shape(_snap(timedelta(hours=3)), event=ev)["deltaPct"] == "-9.2"
    other = {"to_snapshot_id": uuid4(), "delta_pct": "-9.2", "direction": "DECREASE"}
    assert _shape(_snap(timedelta(hours=3)), event=other)["deltaPct"] is None


def test_relationship_defaults_to_unknown_and_relevance_is_never_invented() -> None:
    c = _shape(_snap(timedelta(hours=1)))
    assert c["relationshipClass"] == "UNKNOWN" and c["relevanceBand"] is None and c["relevanceScore"] is None
    c2 = _shape(_snap(timedelta(hours=1)), candidate={"identity_match": "NOT_A_MATCH", "relationship_class": "DIRECT_COMPETITOR"},
                relevance={"band": "MEDIUM", "total_score": 7, "is_provisional": True})
    assert (c2["relationshipClass"], c2["relevanceBand"], c2["relevanceScore"], c2["relevanceProvisional"]) == ("DIRECT_COMPETITOR", "MEDIUM", 7, True)


def test_price_status_rules() -> None:
    assert price_status(has_confirmed_snapshot=True, freshness=Freshness.STALE, latest_pending=False) == "VERIFIED"
    assert price_status(has_confirmed_snapshot=True, freshness=Freshness.UNAVAILABLE, latest_pending=True) == "UNVERIFIED"
    assert price_status(has_confirmed_snapshot=False, freshness=Freshness.UNAVAILABLE, latest_pending=False) == "UNAVAILABLE"


def test_candidates_carry_the_leads_title_and_link_but_never_the_snippet() -> None:
    """Owner decision 2026-10-18: a search lead is shown by what the search called it and its public link, so the seller can judge it. The snippet (search-engine text) is still never sent."""
    cand = {"id": uuid4(), "marketplace": "AMAZON", "tier": "RECOMMENDED", "identity_match": "NOT_A_MATCH", "relationship_class": "DIRECT_COMPETITOR",
            "seller_decision": "NONE", "evidence_status": "AWAITING_EVIDENCE", "candidate_url": "https://www.amazon.in/dp/B09ABC1234", "title": "Titan Octane Watch", "snippet": "search text"}
    shaped = shape_candidate(cand, None)
    assert "snippet" not in shaped and "candidateUrl" not in shaped
    assert shaped["title"] == "Titan Octane Watch" and shaped["url"] == "https://www.amazon.in/dp/B09ABC1234"
    assert shape_candidate({**cand, "title": None}, None)["title"] is None  # no title from the search: none is invented
    assert shaped["evidenceStatus"] == "AWAITING_EVIDENCE"


def test_the_workspace_counts_and_is_empty_for_a_new_seller() -> None:
    empty = shape_workspace(products=[], selected_product_id=None, competitors=[], candidates=[], reviews=[], changes=[], pending=[], events=[], discovery=None, now=NOW)
    assert empty["kpis"] == {"trackedCount": 0, "verifiedCount": 0, "needsEvidenceCount": 0, "importantChangeCount": 0, "reviewInsightCount": 0, "pendingQuestionCount": 0}
    assert empty["competitors"] == [] and empty["lastDiscovery"] is None and empty["selectedProductId"] is None

    fresh, stale = _shape(_snap(timedelta(hours=2))), _shape(_snap(timedelta(days=3)))
    ws = shape_workspace(products=[("SKU-1", "Emerald Chrono")], selected_product_id="SKU-1", competitors=[fresh, stale], candidates=[], reviews=[], changes=[{}], pending=[{}], events=[], discovery=None, now=NOW)
    assert ws["kpis"]["trackedCount"] == 2 and ws["kpis"]["verifiedCount"] == 2 and ws["kpis"]["needsEvidenceCount"] == 1
    assert ws["kpis"]["importantChangeCount"] == 1 and ws["kpis"]["pendingQuestionCount"] == 1
    assert ws["products"] == [{"productId": "SKU-1", "title": "Emerald Chrono"}]
