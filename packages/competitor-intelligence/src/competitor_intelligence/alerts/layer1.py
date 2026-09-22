"""Layer 1 competitor alerts (competitor-intelligence-agent.md §6.17, C26) and the generalized
`Evidence`/`CIHandoff` finding schema (§5.6) that backs them.

**Layer 1 vs. Layer 2 — read this before touching this file.** Per §6.17:

| Layer | Owner | Example |
|---|---|---|
| Layer 1 — CI alert (observational only) | CI | "Competitor X dropped price 8% (Rs.999 -> Rs.919)." |
| Layer 2 — cross-agent business alert | CEO orchestrator | CI alert + CFO margin/contribution impact, composed by CEO |

CI produces Layer 1 **only**. `Layer1Alert.message` is the entire narration this module is
allowed to emit — a plain restatement of a fact CI already computed (the price/availability
delta itself is `delta/compute.py`'s own permitted arithmetic over CI's own observed facts,
not a financial calculation). It states nothing about margin, contribution, break-even, fee
or cost (C26, AC29) — there is no code path here that could produce such a figure.

The `CIHandoff` this module builds alongside each alert is CI's entire contribution to a
future Layer 2 (C26 rule 2: "CI's contribution to Layer 2 is exactly the CIHandoff payload it
already emits — nothing else in CI changes to enable it"). Layer 2 itself (a CEO composing
this payload with a CFO figure) is deferred per §1a item 8 — no CFO agent exists yet. Nothing
in this module needs to change when one does.

`CIHandoff` is a distinct object from `handoff.py`'s `CiHandoffSnapshot` — see that module's
docstring ("Relationship to the existing handoff.py shape", competitor-intelligence-agent.md
§5.6): `CiHandoffSnapshot` is a *fact* view (latest known facts for one competitor);
`CIHandoff` here is a *finding* view (an implication plus a suggested next question for
another agent). Both are real, both stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from competitor_intelligence.repositories import (
    competitor_price_event_repo,
    competitor_snapshot_repo,
    competitor_url_repo,
)
from competitor_intelligence.types import AvailabilityChange, Direction


class EvidenceSourceType(str, Enum):
    SELLER_SCREENSHOT = "SELLER_SCREENSHOT"
    LICENSED_PROVIDER = "LICENSED_PROVIDER"
    REVIEW_SNIPPET = "REVIEW_SNIPPET"


class EvidenceConfidence(str, Enum):
    """§6.16.1's HIGH/MEDIUM/LOW extraction-trust scale — a different scale from
    `competitor_intelligence.types.Confidence` (who produced a value). Never derived from
    that enum by a lookup table (§5.6)."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingType(str, Enum):
    PRICE_CHANGE = "PRICE_CHANGE"
    LISTING_GAP = "LISTING_GAP"
    REVIEW_THEME = "REVIEW_THEME"
    AVAILABILITY_CHANGE = "AVAILABILITY_CHANGE"
    DIFFERENTIATION_OPPORTUNITY = "DIFFERENTIATION_OPPORTUNITY"
    MARKET_POSITION = "MARKET_POSITION"


class TargetAgent(str, Enum):
    CFO = "CFO"
    CMO = "CMO"


@dataclass(frozen=True, slots=True)
class Evidence:
    """§5.6's generalized evidence record — a screenshot-backed extraction, not a review
    snippet specifically (the earlier, narrower typing this replaces)."""

    evidence_id: str
    source_type: EvidenceSourceType
    source_reference: str
    captured_at: datetime
    field: str
    extracted_value: str
    confidence: EvidenceConfidence


@dataclass(frozen=True, slots=True)
class ValidatedFact:
    fact: str
    confidence: EvidenceConfidence
    captured_at: datetime
    is_stale: bool


@dataclass(frozen=True, slots=True)
class SuggestedAction:
    target_agent: TargetAgent
    suggested_question: str


@dataclass(frozen=True, slots=True)
class CIHandoff:
    """§5.6's finding-view schema. `evidence_refs` is what actually crosses the wire per the
    spec's own shape (a list of ids); the full `evidence` tuple is kept alongside for anything
    in-process that wants the extraction detail without a second lookup."""

    finding_id: str
    finding_type: FindingType
    validated_fact: tuple[ValidatedFact, ...]
    evidence: tuple[Evidence, ...]
    competitor_refs: tuple[str, ...]
    implication: str
    suggested_action: SuggestedAction | None
    created_at: datetime
    created_by: str = "CI"

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(e.evidence_id for e in self.evidence)


@dataclass(frozen=True, slots=True)
class Layer1Alert:
    """The seller/CEO-Hub-visible object — `message` is observational only (C26/AC29): no
    margin, contribution, break-even, fee or cost figure or implication anywhere in it."""

    price_event_id: UUID
    competitor_url_id: UUID
    competitor_label: str
    finding_type: FindingType
    direction: Direction | None
    delta_pct: str | None
    availability_change: AvailabilityChange | None
    threshold_breached: bool
    message: str
    created_at: datetime
    handoff: CIHandoff


def _label_for(url_row: dict[str, Any]) -> str:
    return url_row.get("label") or f"{str(url_row['marketplace']).title()} listing"


def _format_message(
    *,
    label: str,
    direction: Direction | None,
    delta_pct: Any,
    availability_change: AvailabilityChange | None,
    from_price_paise: int | None,
    to_price_paise: int | None,
) -> str:
    parts: list[str] = []
    if direction is not None and delta_pct is not None:
        verb = "raised" if direction == Direction.INCREASE else "dropped"
        price_bit = ""
        if from_price_paise is not None and to_price_paise is not None:
            price_bit = f" (Rs.{from_price_paise / 100:,.2f} -> Rs.{to_price_paise / 100:,.2f})"
        parts.append(f"{label} {verb} price {abs(delta_pct)}%{price_bit}")
    if availability_change is not None:
        phrase = "went out of stock" if availability_change == AvailabilityChange.IN_TO_OUT else "came back in stock"
        parts.append(f"{label} {phrase}")
    return "; ".join(parts) if parts else f"{label} changed"


def build_layer1_alerts(
    tenant_id: UUID, *, since: datetime, now: datetime | None = None
) -> list[Layer1Alert]:
    """Every alert-eligible price event since `since`, narrated as a Layer 1 alert plus its
    backing `CIHandoff` finding. `competitor_price_event.alert_eligible` already encodes
    §6.3 rule 4 (neither snapshot stale, neither pending manual entry) at write time — this
    function trusts that stored column rather than re-deriving the gate."""
    now = now or datetime.now(timezone.utc)
    events = competitor_price_event_repo.list_recent_for_tenant(tenant_id, since=since)
    if not events:
        return []

    url_ids = {UUID(str(e["competitor_url_id"])) for e in events}
    urls_by_id = {UUID(str(u["id"])): u for u in competitor_url_repo.get_by_ids(tenant_id, list(url_ids))}

    alerts: list[Layer1Alert] = []
    for event in events:
        # §6.3 rule 3/4 are two independent gates: `threshold_breached` is whether the move is
        # significant enough to be worth surfacing at all; `alert_eligible` is whether the data
        # backing it is trustworthy enough to surface (neither snapshot stale/pending). A Layer
        # 1 alert requires both — a sub-threshold wobble is real (it's still in
        # `competitor_price_event`, and the digest's own aggregation counts it) but is not, on
        # its own, alert-worthy.
        if not event["alert_eligible"] or not event["threshold_breached"]:
            continue
        url_id = UUID(str(event["competitor_url_id"]))
        url_row = urls_by_id.get(url_id)
        if url_row is None:
            # Archived or a cross-tenant race since the event was written — never fabricate a
            # label for a URL we can no longer see.
            continue
        label = _label_for(url_row)

        from_snapshot = competitor_snapshot_repo.get_by_id(tenant_id, UUID(str(event["from_snapshot_id"])))
        to_snapshot = competitor_snapshot_repo.get_by_id(tenant_id, UUID(str(event["to_snapshot_id"])))
        from_price = from_snapshot["listed_price_paise"] if from_snapshot else None
        to_price = to_snapshot["listed_price_paise"] if to_snapshot else None

        # `competitor_price_event.direction` is set unconditionally by delta/compute.py (it
        # defaults to DECREASE when delta_paise is 0), so it can't be used to tell "a price
        # actually changed" apart from "only availability changed" — `delta_paise != 0` is the
        # real signal (matches `should_emit_price_event`'s own gate for creating this row).
        price_changed = event["delta_paise"] != 0
        direction = Direction(event["direction"]) if price_changed else None
        availability_change = (
            AvailabilityChange(event["availability_change"]) if event.get("availability_change") else None
        )
        message = _format_message(
            label=label,
            direction=direction,
            delta_pct=event["delta_pct"] if price_changed else None,
            availability_change=availability_change,
            from_price_paise=from_price,
            to_price_paise=to_price,
        )
        finding_type = FindingType.PRICE_CHANGE if price_changed else FindingType.AVAILABILITY_CHANGE

        validated_facts: list[ValidatedFact] = []
        evidence: list[Evidence] = []
        if to_snapshot is not None and to_price is not None:
            captured_at = to_snapshot["captured_at"]
            validated_facts.append(
                ValidatedFact(
                    fact=f"{label} listed price = Rs.{to_price / 100:.2f}",
                    confidence=EvidenceConfidence.HIGH,
                    captured_at=captured_at,
                    is_stale=False,  # alert_eligible already excludes stale snapshots
                )
            )
            evidence.append(
                Evidence(
                    evidence_id=f"{event['id']}:price",
                    source_type=EvidenceSourceType.SELLER_SCREENSHOT,
                    source_reference=str(to_snapshot["id"]),
                    captured_at=captured_at,
                    field="price",
                    extracted_value=str(to_price),
                    confidence=EvidenceConfidence.HIGH,
                )
            )

        handoff = CIHandoff(
            finding_id=str(event["id"]),
            finding_type=finding_type,
            validated_fact=tuple(validated_facts),
            evidence=tuple(evidence),
            competitor_refs=(str(url_id),),
            implication=(
                "A competitor price/availability change was observed. This is an observational "
                "fact only — CI states no downstream business impact (C26). Route to CFO for a "
                "financial-impact read."
            ),
            suggested_action=SuggestedAction(
                target_agent=TargetAgent.CFO,
                suggested_question=f"What would matching {label}'s new price do to contribution margin?",
            ),
            created_at=now,
        )

        alerts.append(
            Layer1Alert(
                price_event_id=UUID(str(event["id"])),
                competitor_url_id=url_id,
                competitor_label=label,
                finding_type=finding_type,
                direction=direction,
                delta_pct=str(event["delta_pct"]) if event.get("delta_pct") is not None else None,
                availability_change=availability_change,
                threshold_breached=bool(event["threshold_breached"]),
                message=message,
                created_at=event["created_at"],
                handoff=handoff,
            )
        )
    return alerts


def layer1_alert_to_dict(alert: Layer1Alert) -> dict[str, Any]:
    """The wire shape — kept with the dataclass it serializes, same convention as
    `handoff.py`'s `handoff_snapshot_to_dict`."""
    return {
        "priceEventId": str(alert.price_event_id),
        "competitorUrlId": str(alert.competitor_url_id),
        "competitorLabel": alert.competitor_label,
        "findingType": alert.finding_type.value,
        "direction": alert.direction.value if alert.direction else None,
        "deltaPct": alert.delta_pct,
        "availabilityChange": alert.availability_change.value if alert.availability_change else None,
        "thresholdBreached": alert.threshold_breached,
        "message": alert.message,
        "createdAt": alert.created_at.isoformat(),
        "handoff": {
            "findingId": alert.handoff.finding_id,
            "findingType": alert.handoff.finding_type.value,
            "validatedFact": [
                {
                    "fact": f.fact,
                    "confidence": f.confidence.value,
                    "capturedAt": f.captured_at.isoformat(),
                    "isStale": f.is_stale,
                }
                for f in alert.handoff.validated_fact
            ],
            "evidenceRefs": list(alert.handoff.evidence_refs),
            "competitorRefs": list(alert.handoff.competitor_refs),
            "implication": alert.handoff.implication,
            "suggestedAction": (
                {
                    "targetAgent": alert.handoff.suggested_action.target_agent.value,
                    "suggestedQuestion": alert.handoff.suggested_action.suggested_question,
                }
                if alert.handoff.suggested_action
                else None
            ),
            "createdAt": alert.handoff.created_at.isoformat(),
            "createdBy": alert.handoff.created_by,
        },
    }
