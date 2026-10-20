"""CEO-brokered competitor-listing inputs for Slim CMO (docs/specs/slim-cmo-agent.md section 6.7).

Two small, read-only steps, both tenant-scoped, neither a CI run (no CI unit is consumed):

* `broker` - the CEO's side. Picks which of the seller's saved competitor listing insights may inform a writing task and returns their ids, or no ids plus a one-line reason
  (the seller has no `agent.ci`, the CI entitlement check fails, nothing usable was saved, or what was saved is stale). The ids are frozen into the plan card, so the seller
  sees that competitor themes are used.
* `load_inputs` - CMO's side. Re-checks that every id is the seller's own (an unknown or foreign id looks identical: not found), re-checks `agent.ci` and the entitlement, and
  builds the `CiInputs` the writer receives. Any failure to use them is NOT an error: the task simply runs independently.

Only derived words ever reach a prompt. The competitors' saved title / description / bullets are read here for the originality comparison alone and travel no further.
Competitor prices are never read.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from competitor_intelligence.repositories import competitor_listing_insight_repo
from slim_cmo.ci_inputs import CiInputs, CiInsight
from slim_cmo.service.errors import NotFound

from backend.auth.permissions import AGENT_CI, has_permission
from backend.entitlement import resolve_ci_entitlement

MAX_INSIGHTS = 5  # one per tracked competitor, at most (the watchlist cap)
DEFAULT_MAX_AGE_DAYS = 30  # older listing captures are not offered as current market context; operator-tunable below
NO_CI_NOTE = "Competitor listing themes were not used"


def _max_age_days() -> int:
    raw = os.environ.get("CMO_CI_INSIGHT_MAX_AGE_DAYS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_MAX_AGE_DAYS


def _allowed(tenant_id: UUID, role: str, permissions: Mapping[str, object]) -> str | None:
    """None when allowed, else the plain reason it is not."""
    if not has_permission(role=role, permissions=dict(permissions), key=AGENT_CI):
        return "your plan or role does not include Competitor Intelligence"
    if not resolve_ci_entitlement(tenant_id).passed:
        return "Competitor Intelligence is not available on your plan right now"
    return None


def _fresh(row: Mapping[str, Any], now: datetime) -> bool:
    derived = row.get("derived_at")
    if str(row.get("insight_state")) != "COMPLETE" or not row.get("keyword_themes"):
        return False
    if isinstance(derived, datetime):
        stamp = derived if derived.tzinfo else derived.replace(tzinfo=timezone.utc)
        return now - stamp <= timedelta(days=_max_age_days())
    return False


def broker(tenant_id: UUID, role: str, permissions: Mapping[str, object], *, now: datetime) -> tuple[list[str], str | None]:
    """(insight ids to use, the note to tell the seller when none are used). Never raises: a read problem is an independent task with a note."""
    try:
        why = _allowed(tenant_id, role, permissions)
        if why is not None:
            return [], f"{NO_CI_NOTE}: {why}."
        rows = competitor_listing_insight_repo.list_recent_with_text(tenant_id, limit=MAX_INSIGHTS)
        if not rows:
            return [], f"{NO_CI_NOTE}: none of your tracked competitors has a saved listing capture yet (add a competitor listing screenshot in Competitor Intelligence to use them)."
        usable = [r for r in rows if _fresh(r, now)]
        if not usable:
            return [], f"{NO_CI_NOTE}: the saved competitor listing captures are older than {_max_age_days()} days or incomplete."
        return [str(r["id"]) for r in usable], None
    except Exception:  # noqa: BLE001 - a CI read problem never blocks a writing task
        return [], f"{NO_CI_NOTE}: they could not be read just now."


def _list(v: Any) -> list[str]:
    if isinstance(v, Mapping):
        return [str(k) for k in v]
    if isinstance(v, Sequence) and not isinstance(v, (str, bytes)):
        return [str(x) for x in v]
    return []


def _brand_guess(title: str | None) -> list[str]:
    """The first word of a competitor's title is usually its brand: it is kept out of the themes and out of the seller's text (unless the seller's own facts use that word)."""
    words = (title or "").split()
    first = words[0].strip(",.:;-|()[]").casefold() if words else ""
    return [first] if first.isalpha() and len(first) >= 3 else []


def load_inputs(ctx: Any, ids: Sequence[UUID]) -> CiInputs | None:
    """The writer's inputs for brokered insight `ids`, or None (independent). Raises `NotFound` when an id is not the seller's own (spec 6.7: 404)."""
    unique = list(dict.fromkeys(ids))[:MAX_INSIGHTS]
    if not unique:
        return None
    rows = competitor_listing_insight_repo.get_by_ids(ctx.tenant_id, unique)
    if len(rows) != len(unique):
        raise NotFound("competitor listing insight not found")
    if _allowed(ctx.tenant_id, ctx.role, ctx.permissions) is not None:
        return None
    now = datetime.now(timezone.utc)
    rows = [r for r in rows if _fresh(r, now)]
    if not rows:
        return None
    insights = tuple(
        CiInsight(
            id=str(r["id"]), keyword_themes=tuple(_list(r.get("keyword_themes"))), feature_categories=tuple(_list(r.get("feature_categories"))),
            benefit_terms=tuple(_list(r.get("benefit_term_patterns"))), differentiation_opportunities=tuple(_list(r.get("differentiation_opportunities"))),
        ) for r in rows
    )
    references: list[str] = []
    brands: list[str] = []
    for r in rows:
        for part in (r.get("title"), r.get("description")):
            if isinstance(part, str) and part.strip():
                references.append(part)
        references.extend(b for b in _list(r.get("bullets")) if b.strip())
        brands.extend(_brand_guess(r.get("title")))
    return CiInputs(insights=insights, references=tuple(references), exclude_terms=tuple(dict.fromkeys(brands)))
