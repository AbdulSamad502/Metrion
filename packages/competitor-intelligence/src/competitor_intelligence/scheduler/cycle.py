"""One housekeeping cycle for one tenant — competitor-intelligence-agent.md §6.25, §6.26, D16.

Everything here reads and writes CI's OWN tables. It makes no outbound request of any kind: no competitor, no marketplace,
no search provider (D16, AC47) — so it is a re-evaluation of stored evidence, never a watch on a competitor.

1. Seller questions that were never answered within their expiry become `EXPIRED` (§6.23.2). The field stays `UNKNOWN` and
   the unconfirmed snapshot stays out of every consequential path (it already was: a `PENDING` price is excluded at read).
2. Alerts held for quiet hours whose window has ended are released — after re-validating that their evidence is still fresh (§6.26.2).
3. A competitor whose newest screenshot is older than the tenant's reminder interval gets a `FRESHNESS` finding citing that screenshot,
   once per screenshot (§6.25): the dashboard and the CEO then ask for a fresh one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from competitor_intelligence.alerts.raise_alert import deliver_due_held_alerts
from competitor_intelligence.findings import build
from competitor_intelligence.intake.events import CiEvent
from competitor_intelligence.repositories import ci_event_repo, ci_info_request_repo, ci_tenant_config_repo, competitor_url_repo


def run_tenant_cycle(tenant_id: UUID, *, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    counts = {"expired": 0, "delivered": 0, "withheld": 0, "reminders": 0}

    counts["expired"] = ci_info_request_repo.expire_overdue(tenant_id, now=now)
    if counts["expired"]:
        ci_event_repo.record(tenant_id, CiEvent.FIELD_CONFIRMATION_EXPIRED, detail={"count": counts["expired"]}, occurred_at=now)

    held = deliver_due_held_alerts(tenant_id, now=now)
    counts["delivered"], counts["withheld"] = held["delivered"], held["withheld"]

    reminder_days = int(ci_tenant_config_repo.get_config(tenant_id).get("stalenessReminderDays") or ci_tenant_config_repo.DEFAULT_STALENESS_REMINDER_DAYS)
    for sku in competitor_url_repo.list_linked_skus(tenant_id):
        for url in competitor_url_repo.list_active_by_linked_sku(tenant_id, sku):
            if build.record_freshness_finding(tenant_id, UUID(str(url["id"])), now=now, min_age_days=reminder_days) is not None:
                counts["reminders"] += 1
    return counts
