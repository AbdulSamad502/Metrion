"""The read-only data behind the CI dashboard (competitor-intelligence-agent.md §6.29).

One function, `build_workspace`, gathers what CEO–CI investigations already produced — tracked
competitors with their freshness and verified prices, market position inputs, verified changes,
review insights, discovery candidates, pending seller questions and the event history — and hands it
to the pure `shape_workspace`, which turns rows into the response. The dashboard renders exactly this
and collects nothing (C32).

Rules enforced here, in code:
* A price is shown as **verified** only if it comes from a confirmed snapshot within the D6 ceiling
  (`latest_usable_snapshot` already excludes pending and declined prices, C37). Anything else is
  `UNVERIFIED` with the reason, or `UNAVAILABLE` — never a number presented as current.
* Nothing arithmetic about money happens here: the market band is fetched from the engine by the
  existing `/market-overview` route; this module only passes stored values through.
* No competitor or marketplace image, no review text, no snippet — insights and findings only.
* Tavily-reported values are not read here at all (C35).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from calc_engine.api.competitor_effective_price import compute_competitor_effective_price
from calc_engine.formulas.effective_price import ObservedOffer
from calc_engine.repositories import metric_result_repo
from competitor_intelligence.monitor.report import Freshness, freshness_of
from competitor_intelligence.watchlist.labels import label_of
from competitor_intelligence.repositories import (
    ci_candidate_relevance_repo,
    ci_candidate_repo,
    ci_discovery_run_repo,
    ci_event_repo,
    ci_finding_repo,
    ci_info_request_repo,
    competitor_price_event_repo,
    competitor_review_insight_repo,
    competitor_snapshot_field_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.seller_product.derive import list_products

MAX_EVENTS = 40
MAX_CANDIDATES = 12


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def price_status(*, has_confirmed_snapshot: bool, freshness: Freshness, latest_pending: bool) -> str:
    """`VERIFIED` | `UNVERIFIED` | `UNAVAILABLE` (§6.29.2)."""
    if has_confirmed_snapshot and freshness is not Freshness.UNAVAILABLE:
        return "VERIFIED"
    if latest_pending:
        return "UNVERIFIED"
    return "UNAVAILABLE"


def shape_competitor(
    url: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any] | None,
    relevance: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any] | None,
    pending_snapshot_exists: bool,
    event: Mapping[str, Any] | None,
    open_questions: int,
    now: datetime,
) -> dict[str, Any]:
    evidence_date = snapshot["captured_at"] if snapshot else None
    freshness = freshness_of(evidence_date, now=now)
    status = price_status(has_confirmed_snapshot=snapshot is not None, freshness=freshness, latest_pending=pending_snapshot_exists)
    current = snapshot is not None and freshness is not Freshness.UNAVAILABLE
    return {
        "id": str(url["id"]),
        "label": label_of(url),
        "marketplace": url["marketplace"],
        "identityMatch": candidate["identity_match"] if candidate else None,
        "relationshipClass": (candidate.get("relationship_class") if candidate else None) or "UNKNOWN",
        "relevanceBand": relevance["band"] if relevance else None,
        "relevanceScore": relevance["total_score"] if relevance else None,
        "relevanceProvisional": bool(relevance["is_provisional"]) if relevance else None,
        "evidenceDate": _iso(evidence_date),
        "freshness": freshness.value,
        "priceStatus": status,
        # A price is stated only while it is current and confirmed (D6, C37); otherwise the field is absent, never a stale number.
        "listedPricePaise": snapshot["listed_price_paise"] if current else None,
        "availability": snapshot["availability"] if current else None,
        "ratingValue": str(snapshot["rating"]) if current and snapshot.get("rating") is not None else None,
        "ratingCount": snapshot.get("rating_count") if current else None,
        "deltaPct": str(event["delta_pct"]) if event and current and event["to_snapshot_id"] == snapshot["id"] else None,
        "deltaDirection": event["direction"] if event and current and event["to_snapshot_id"] == snapshot["id"] else None,
        "openQuestions": open_questions,
    }


_EFFECTIVE_PRICE_CONFIG_VERSION = "CI_EFFECTIVE_PRICE.v1"


def effective_price_view(rows: Sequence[Any], *, delivery_paise: int | None, offers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The Brain 1 effective-price rows for one competitor, as the dashboard shows them: each figure with its `engineResultRef`, an unavailable one with its reason. This only
    reshapes what the engine returned; nothing is computed here."""
    by = {r.metric_code: r for r in rows}
    eff, total = by.get("EFFECTIVE_PRICE"), by.get("BUYER_TOTAL")

    def cell(r: Any) -> dict[str, Any] | None:
        if r is None:
            return None
        return {"valuePaise": r.value_paise, "engineResultRef": str(r.id), "isAvailable": r.is_available, "unavailableReason": r.unavailable_reason}

    return {
        "effective": cell(eff),
        "buyerTotal": cell(total),
        "deliveryChargePaise": delivery_paise,
        "offers": [{"kind": o.get("kind"), "amountPaise": o.get("amount_paise"), "conditional": bool(o.get("condition_text"))} for o in offers],
        "excludedOffers": [{"kind": e.get("kind"), "reason": e.get("reason")} for e in (eff.exclusions if eff is not None else ())],
    }


def compute_effective_view(tenant_id: UUID, *, product_id: str, competitor_id: str, snapshot: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Brain 1 (deterministic-engine.md 5.15.2) over what the seller confirmed about one competitor's listing: price, visible discount, delivery charge and offers.
    CI performs no effective-price arithmetic of its own for this comparison (C44). A delivery charge or offer the seller never confirmed is simply not an input."""
    fields = {r["field_name"]: r["value"] for r in competitor_snapshot_field_repo.get_fields(tenant_id, snapshot["id"])}
    offers = [o for o in (fields.get("offers") or []) if isinstance(o, dict)]
    delivery = fields.get("delivery_charge_paise")
    rows = compute_competitor_effective_price(
        competitor_ref=competitor_id, source_ref=str(snapshot["id"]), listed_paise=snapshot["listed_price_paise"], visible_discount_paise=snapshot["visible_discount_paise"],
        delivery_charge_paise=delivery if isinstance(delivery, int) else None,
        offers=[ObservedOffer(str(o.get("kind") or "OTHER"), o.get("amount_paise") if isinstance(o.get("amount_paise"), int) else None, o.get("condition_text")) for o in offers],
        computed_at=now,
    )
    for row in rows:
        metric_result_repo.save(tenant_id, row, grain="SKU", target_ref=product_id, period=None, config_version=_EFFECTIVE_PRICE_CONFIG_VERSION)
    return effective_price_view(rows, delivery_paise=delivery if isinstance(delivery, int) else None, offers=offers)


def shape_candidate(candidate: Mapping[str, Any], relevance: Mapping[str, Any] | None) -> dict[str, Any]:
    from backend.services import ci_conv_data  # noqa: PLC0415

    return {
        "id": str(candidate["id"]),
        "title": candidate.get("title"),
        "url": candidate.get("candidate_url"),
        "identityNote": ci_conv_data.identity_note(dict(candidate)),
        "marketplace": candidate["marketplace"],
        "tier": candidate["tier"],
        "identityMatch": candidate["identity_match"],
        "relationshipClass": candidate.get("relationship_class") or "UNKNOWN",
        "relevanceBand": relevance["band"] if relevance else None,
        "relevanceScore": relevance["total_score"] if relevance else None,
        "relevanceProvisional": bool(relevance["is_provisional"]) if relevance else None,
        "sellerDecision": candidate["seller_decision"],
        "evidenceStatus": candidate["evidence_status"],
    }


def shape_finding(row: Mapping[str, Any]) -> dict[str, Any]:
    """One persisted finding, display-safe: its stable id (what Ask CEO passes), what it is about, how fresh and how well confirmed it is, and its sample size.
    The payload holds derived facts only (never review text or snippets)."""
    return {
        "id": str(row["id"]),
        "type": row["finding_type"],
        "competitorId": str(row["competitor_url_id"]) if row["competitor_url_id"] else None,
        "freshness": row["freshness"],
        "confidence": row["confidence"],
        "sellerConfirmation": row["seller_confirmation"],
        "sampleSize": row["sample_size"],
        "evidenceCount": len(row["evidence_refs"]),
        "createdAt": _iso(row["created_at"]),
        "payload": row["payload"],
    }


def attach_finding_ids(items: list[dict[str, Any]], findings: Sequence[dict[str, Any]], types: tuple[str, ...], key: str = "competitorId") -> None:
    """Gives each row the id of the newest finding of the right type about the same competitor, so its Ask CEO button can pass it (C46). A row with no finding gets `None`."""
    newest: dict[str, str] = {}
    for f in findings:  # newest first
        if f["type"] in types and f["competitorId"] and f["competitorId"] not in newest:
            newest[f["competitorId"]] = f["id"]
    for item in items:
        item["findingId"] = newest.get(str(item.get(key)))


def shape_workspace(
    *,
    products: Sequence[tuple[str, str | None]],
    selected_product_id: str | None,
    competitors: Sequence[dict[str, Any]],
    candidates: Sequence[dict[str, Any]],
    reviews: Sequence[dict[str, Any]],
    changes: Sequence[dict[str, Any]],
    pending: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    discovery: dict[str, Any] | None,
    now: datetime,
    findings: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    verified = [c for c in competitors if c["priceStatus"] == "VERIFIED"]
    needs_evidence = [c for c in competitors if c["freshness"] != Freshness.FRESH.value]
    return {
        "asOf": now.isoformat(),
        "products": [{"productId": pid, "title": title} for pid, title in products],
        "selectedProductId": selected_product_id,
        "kpis": {
            "trackedCount": len(competitors),
            "verifiedCount": len(verified),
            "needsEvidenceCount": len(needs_evidence),
            "importantChangeCount": len(changes),
            "reviewInsightCount": len(reviews),
            "pendingQuestionCount": len(pending),
        },
        "competitors": list(competitors),
        "candidates": list(candidates),
        "reviewInsights": list(reviews),
        "changes": list(changes),
        "pendingConfirmations": list(pending),
        "events": list(events),
        "findings": list(findings),
        "lastDiscovery": discovery,
    }


def _with_watchlist(tenant_id: UUID, ws: dict[str, Any]) -> dict[str, Any]:
    """How many of the seller's competitor slots are used (the same limit chat and every add path enforce)."""
    from competitor_intelligence.repositories import competitor_url_repo  # noqa: PLC0415

    st = competitor_url_repo.watchlist_status(tenant_id)
    ws["watchlist"] = {"limit": st["limit"], "used": len(st["active"]), "free": st["free"]}
    return ws


def build_workspace(tenant_id: UUID, product_id: str | None, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    products = list_products(tenant_id)
    linked = competitor_url_repo.list_linked_skus(tenant_id)
    known_ids = {pid for pid, _ in products} | set(linked)
    titled = [(pid, title) for pid, title in products if pid in known_ids] + [(pid, None) for pid in linked if pid not in {p for p, _ in products}]
    selected = product_id if product_id in known_ids else (linked[0] if linked else (products[0][0] if products else None))

    competitors: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    if selected is not None:
        for url in competitor_url_repo.list_active_by_linked_sku(tenant_id, selected):
            candidate = ci_candidate_repo.get_by_competitor_url_id(tenant_id, url["id"])
            relevance = ci_candidate_relevance_repo.get_latest_relevance(tenant_id, candidate["id"]) if candidate else None
            snapshot = competitor_snapshot_repo.latest_usable_snapshot(tenant_id, url["id"])
            all_snapshots = competitor_snapshot_repo.list_snapshots(tenant_id, url["id"], limit=1)
            pending_exists = bool(all_snapshots) and all_snapshots[0].get("price_confirmation") in ("PENDING", "DECLINED")
            events = competitor_price_event_repo.list_events(tenant_id, url["id"], limit=1)
            event = events[0] if events else None
            open_questions = len(ci_info_request_repo.list_open(tenant_id, competitor_url_id=url["id"]))
            shaped = shape_competitor(
                url, candidate=candidate, relevance=relevance, snapshot=snapshot, pending_snapshot_exists=pending_exists,
                event=event, open_questions=open_questions, now=now,
            )
            shaped["effectivePrice"] = (
                compute_effective_view(tenant_id, product_id=selected, competitor_id=shaped["id"], snapshot=snapshot, now=now)
                if snapshot is not None and shaped["priceStatus"] == "VERIFIED" else None
            )
            competitors.append(shaped)
            if event is not None and snapshot is not None and event["to_snapshot_id"] == snapshot["id"] and shaped["priceStatus"] == "VERIFIED":
                changes.append(
                    {
                        "competitorId": shaped["id"], "label": label_of(url), "marketplace": url["marketplace"],
                        "kind": "AVAILABILITY" if event.get("availability_change") and not event.get("threshold_breached") else "PRICE",
                        "deltaPaise": event["delta_paise"], "deltaPct": str(event["delta_pct"]), "direction": event["direction"],
                        "availabilityChange": event.get("availability_change"), "occurredAt": _iso(event["created_at"]),
                        "evidenceDate": shaped["evidenceDate"],
                    }
                )
            insight = competitor_review_insight_repo.latest_for_url(tenant_id, url["url"])  # whether or not it was tied to a listing snapshot
            if insight is not None:
                reviews.append(
                    {
                        "competitorId": shaped["id"], "label": label_of(url),
                        "complaintThemes": insight["complaint_themes"], "positiveThemes": insight["positive_themes"],
                        "reviewsConsidered": insight["reviews_considered"], "confidence": insight["confidence"],
                        "insightState": insight["insight_state"], "evidenceDate": _iso(insight["derived_at"]),
                    }
                )

    candidates: list[dict[str, Any]] = []
    discovery: dict[str, Any] | None = None
    if selected is not None:
        run = ci_discovery_run_repo.latest_for_product(tenant_id, selected)
        if run is not None:
            discovery = {
                "status": run["status"], "partialReason": run.get("partial_reason"), "failedReason": run.get("failed_reason"),
                "provider": run.get("provider_name"), "finishedAt": _iso(run.get("finished_at")), "rawCandidateCount": run.get("raw_candidate_count"),
            }
            from backend.services import ci_conv_data  # noqa: PLC0415

            rows = ci_conv_data.with_titles(tenant_id, ci_candidate_repo.list_candidates_for_run(tenant_id, run["id"]))
            from backend.services import ci_categories  # noqa: PLC0415

            cat = ci_categories.category_name(run.get("seller_product_ref"))
            if cat:
                rows = [{**c, "category": cat} for c in rows]
            order = {"RECOMMENDED": 0, "ANALYZED": 1, "RAW": 2}
            rows.sort(key=lambda c: (order.get(c["tier"], 3), -(c.get("relevance_score") or 0), c["created_at"]))
            for c in rows[:MAX_CANDIDATES]:
                if c["seller_decision"] == "REJECTED" or c.get("competitor_url_id") is not None:
                    continue  # rejected ones are gone; approved ones now appear under Competitors
                candidates.append(shape_candidate(c, ci_candidate_relevance_repo.get_latest_relevance(tenant_id, c["id"])))

    pending = [
        {"id": str(r["id"]), "field": r["field_name"], "reason": r["reason"], "competitorId": str(r["competitor_url_id"]) if r["competitor_url_id"] else None,
         "createdAt": _iso(r["created_at"]), "expiresAt": _iso(r["expires_at"])}
        for r in ci_info_request_repo.list_open(tenant_id)
    ]
    events = [
        {"id": str(e["id"]), "type": e["event_type"], "occurredAt": _iso(e["occurred_at"]), "objectType": e["object_type"],
         "objectId": str(e["object_id"]) if e["object_id"] else None, "detail": e["detail"]}
        for e in ci_event_repo.list_recent(tenant_id, limit=MAX_EVENTS)
    ]
    findings = [shape_finding(r) for r in ci_finding_repo.list_for_product(tenant_id, selected)] if selected is not None else []
    attach_finding_ids(changes, findings, ("PRICE_CHANGE", "AVAILABILITY_CHANGE"))
    attach_finding_ids(reviews, findings, ("REVIEW_THEME",))
    attach_finding_ids(competitors, findings, ("PRICE_CHANGE", "AVAILABILITY_CHANGE", "FRESHNESS"), key="id")
    return _with_watchlist(tenant_id, shape_workspace(
        products=titled, selected_product_id=selected, competitors=competitors, candidates=candidates, reviews=reviews,
        changes=changes, pending=pending, events=events, discovery=discovery, now=now, findings=findings,
    ))
