"""Approve, reject, add and remove competitors — competitor-intelligence-agent.md §6.24 (C39).

Called only by fixed CEO actions; there is no dashboard write path. Every operation writes an audit
event (C47) and every repository call is tenant-scoped.

* **Add** takes a marketplace URL the seller stated: the C4/D7 host allowlist applies, the saved-URL
  cap is checked **before** the write, and a URL already tracked is returned as-is (never duplicated).
  A previously removed URL is **restored**, history intact.
* **Remove** is soft: the competitor is archived (excluded from comparison, monitoring and alerts —
  every ACTIVE-only query already does this) with who/when/why recorded; evidence, snapshots and events
  are retained under §6.8. Nothing is deleted.
* **Approve / reject** delegate to the existing discovery functions (`accept_candidate`,
  `reject_candidate`), which own the candidate-to-tracked-competitor transition and its run-state rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from competitor_intelligence.capture.allowlist import marketplace_for_host
from competitor_intelligence.discovery.discovery_run import accept_candidate, reject_candidate
from competitor_intelligence.intake.events import CiEvent
from competitor_intelligence.repositories import ci_event_repo, competitor_url_repo
from competitor_intelligence.repositories.competitor_url_repo import WatchlistFull


class ManageStatus(str, Enum):
    OK = "OK"
    ALREADY_TRACKED = "ALREADY_TRACKED"
    RESTORED = "RESTORED"
    NOT_ALLOWLISTED = "NOT_ALLOWLISTED"
    CAP_REACHED = "CAP_REACHED"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class ManageResult:
    status: ManageStatus
    competitor_url_id: UUID | None = None
    detail: str | None = None
    limit: int | None = None
    active_names: tuple[str, ...] = ()


def _full(exc: WatchlistFull) -> ManageResult:
    from competitor_intelligence.watchlist.labels import label_of  # noqa: PLC0415

    return ManageResult(ManageStatus.CAP_REACHED, detail=f"{len(exc.active)} of {exc.limit} competitor slots are used", limit=exc.limit, active_names=tuple(label_of(r) for r in exc.active))


def add_competitor(
    tenant_id: UUID,
    *,
    url: str,
    product_id: str | None,
    label: str | None,
    added_by: UUID,
    max_active: int | None,
    agent_run_id: UUID | None = None,
    investigation_id: UUID | None = None,
) -> ManageResult:
    marketplace = marketplace_for_host(url)
    if marketplace is None:
        return ManageResult(ManageStatus.NOT_ALLOWLISTED, detail="only amazon.in, flipkart.com and meesho.com links can be tracked")

    existing = competitor_url_repo.find_by_url(tenant_id, url)
    if existing is not None and existing["status"] == "ACTIVE":
        if label and label.strip() and competitor_url_repo.set_label_if_blank(tenant_id, existing["id"], label.strip()):
            return ManageResult(ManageStatus.ALREADY_TRACKED, competitor_url_id=existing["id"], detail=f"named:{label.strip()}")
        return ManageResult(ManageStatus.ALREADY_TRACKED, competitor_url_id=existing["id"])

    if max_active is not None and competitor_url_repo.count_active(tenant_id) >= max_active:
        return ManageResult(ManageStatus.CAP_REACHED, detail=f"{max_active} competitors are already tracked, which is the limit set for your account", limit=max_active)

    if existing is not None:  # archived: restore, history intact
        try:
            competitor_url_repo.restore_url(tenant_id, existing["id"], linked_sku=product_id)
        except WatchlistFull as exc:
            return _full(exc)
        ci_event_repo.record(tenant_id, CiEvent.COMPETITOR_ADDED, actor=added_by, agent_run_id=agent_run_id,
                             investigation_id=investigation_id, object_type="competitor_url", object_id=existing["id"],
                             detail={"restored": True})
        return ManageResult(ManageStatus.RESTORED, competitor_url_id=existing["id"])

    try:
        url_id = competitor_url_repo.create_url(
            tenant_id, marketplace=marketplace, url=url, added_by=added_by, label=label, linked_sku=product_id
        )
    except WatchlistFull as exc:
        return _full(exc)
    ci_event_repo.record(tenant_id, CiEvent.COMPETITOR_ADDED, actor=added_by, agent_run_id=agent_run_id,
                         investigation_id=investigation_id, object_type="competitor_url", object_id=url_id,
                         detail={"marketplace": marketplace.value})
    return ManageResult(ManageStatus.OK, competitor_url_id=url_id)


def remove_competitor(
    tenant_id: UUID,
    competitor_url_id: UUID,
    *,
    removed_by: UUID,
    reason: str | None = None,
    agent_run_id: UUID | None = None,
    investigation_id: UUID | None = None,
) -> ManageResult:
    row = competitor_url_repo.get_any_by_id(tenant_id, competitor_url_id)
    if row is None:
        return ManageResult(ManageStatus.NOT_FOUND)
    if row["status"] == "ARCHIVED":
        return ManageResult(ManageStatus.OK, competitor_url_id=competitor_url_id)  # idempotent
    competitor_url_repo.soft_remove(tenant_id, competitor_url_id, removed_by=removed_by, reason=reason)
    ci_event_repo.record(tenant_id, CiEvent.COMPETITOR_REMOVED, actor=removed_by, agent_run_id=agent_run_id,
                         investigation_id=investigation_id, object_type="competitor_url", object_id=competitor_url_id)
    return ManageResult(ManageStatus.OK, competitor_url_id=competitor_url_id)


def approve_candidate(
    tenant_id: UUID, candidate_id: UUID, *, decided_by: UUID, agent_run_id: UUID | None = None, investigation_id: UUID | None = None
) -> ManageResult:
    from competitor_intelligence.discovery.discovery_run import CandidateNotAllowlisted, CandidateNotFound

    try:
        result = accept_candidate(tenant_id, candidate_id, decided_by=decided_by)
    except CandidateNotFound:
        return ManageResult(ManageStatus.NOT_FOUND)
    except CandidateNotAllowlisted as exc:
        return ManageResult(ManageStatus.NOT_ALLOWLISTED, detail=str(exc))
    except WatchlistFull as exc:
        return _full(exc)
    ci_event_repo.record(tenant_id, CiEvent.COMPETITOR_APPROVED, actor=decided_by, agent_run_id=agent_run_id,
                         investigation_id=investigation_id, object_type="ci_candidate", object_id=candidate_id)
    _name_from_search_title(tenant_id, result.competitor_url_id)
    return ManageResult(ManageStatus.OK, competitor_url_id=result.competitor_url_id)


def _name_from_search_title(tenant_id: UUID, competitor_url_id: UUID) -> None:
    """A competitor approved from a search lead is named by what the search called it (stored, never invented), so the seller can refer to it by that name. A name the seller
    already gave is never replaced; if the search returned no title the competitor stays unnamed and shows its derived name."""
    try:
        from competitor_intelligence.repositories import ci_search_result_repo  # noqa: PLC0415

        row = competitor_url_repo.get_any_by_id(tenant_id, competitor_url_id)
        if row is None or not row.get("url"):
            return
        found = ci_search_result_repo.titles_by_url(tenant_id, [row["url"]]).get(row["url"])
        title = " ".join(str((found or {}).get("title") or "").split())
        if title:
            from competitor_intelligence.discovery.lead_quality import lead_label  # noqa: PLC0415

            competitor_url_repo.set_label_if_blank(tenant_id, competitor_url_id, lead_label(title))
    except Exception:  # noqa: BLE001 - naming is a convenience: the approval itself already stands
        pass


def reject_candidate_decision(
    tenant_id: UUID, candidate_id: UUID, *, decided_by: UUID, agent_run_id: UUID | None = None, investigation_id: UUID | None = None
) -> ManageResult:
    from competitor_intelligence.discovery.discovery_run import CandidateNotFound

    try:
        reject_candidate(tenant_id, candidate_id, decided_by=decided_by)
    except CandidateNotFound:
        return ManageResult(ManageStatus.NOT_FOUND)
    ci_event_repo.record(tenant_id, CiEvent.COMPETITOR_REJECTED, actor=decided_by, agent_run_id=agent_run_id,
                         investigation_id=investigation_id, object_type="ci_candidate", object_id=candidate_id)
    return ManageResult(ManageStatus.OK)
