"""Deterministic "what changed" aggregation — §5 `ci_digest_subscription` /
`ci_tenant_config.digest_default_frequency`. Builds the digest's CONTENT from CI's own
already-persisted price events; it does not send anything (WhatsApp/email delivery stays
deferred per spec §1a) and it does not narrate — every field here is a count or a raw
observed fact, exactly like `handoff.py`. Narration (turning this into seller-facing prose)
is the CEO/CMO's job once they exist, per the hard rule that CI itself never composes text
beyond structured facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from competitor_intelligence.repositories import competitor_price_event_repo, competitor_url_repo


@dataclass(frozen=True, slots=True)
class DigestCompetitorEntry:
    competitor_url_id: UUID
    label: str | None
    price_increase_count: int
    price_decrease_count: int
    availability_change_count: int
    threshold_breached_count: int


@dataclass(frozen=True, slots=True)
class DigestSummary:
    since: datetime
    until: datetime
    competitors_with_activity: int
    entries: tuple[DigestCompetitorEntry, ...]


def build_digest(tenant_id: UUID, *, since: datetime, until: datetime) -> DigestSummary:
    events = competitor_price_event_repo.list_recent_for_tenant(tenant_id, since=since)
    events = [e for e in events if e["created_at"] <= until]

    by_url: dict[UUID, list[dict]] = {}
    for event in events:
        by_url.setdefault(event["competitor_url_id"], []).append(event)

    if not by_url:
        return DigestSummary(since=since, until=until, competitors_with_activity=0, entries=())

    urls = {row["id"]: row for row in competitor_url_repo.get_by_ids(tenant_id, list(by_url.keys()))}

    entries = []
    for url_id, url_events in by_url.items():
        entries.append(
            DigestCompetitorEntry(
                competitor_url_id=url_id,
                label=urls.get(url_id, {}).get("label"),
                price_increase_count=sum(1 for e in url_events if e["direction"] == "INCREASE"),
                price_decrease_count=sum(1 for e in url_events if e["direction"] == "DECREASE"),
                availability_change_count=sum(1 for e in url_events if e["availability_change"] is not None),
                threshold_breached_count=sum(1 for e in url_events if e["threshold_breached"]),
            )
        )

    return DigestSummary(since=since, until=until, competitors_with_activity=len(entries), entries=tuple(entries))
