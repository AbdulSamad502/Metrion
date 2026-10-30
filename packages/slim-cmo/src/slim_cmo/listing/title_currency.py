"""Was this saved listing written from the title the seller has approved NOW? (docs/CMO-3.0/CMO_ACCEPTANCE_TESTS.md N-15d; spec 6.18.7). Pure: no I/O, no model.

A listing pack is grounded on one title (the seller's approval of it, or a title they typed). When the seller later APPROVES a different title for the same product and marketplace, the pack was
built from a previous title. This is information, not a defect: the pack stays valid, is not edited, relabelled, regenerated or invalidated, and an unapproved title change (a new set of options
nobody chose, a typed idea) changes nothing. Missing or unconfirmed title information is UNKNOWN, never OUTDATED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from slim_cmo.listing.text import norm

CURRENT, OUTDATED, UNKNOWN = "CURRENT", "OUTDATED", "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ApprovalRef:
    id: str
    text: str
    approved_at: datetime


NEXT_STEP = "Nothing was changed or regenerated. Ask me to write the complete listing again and I will plan it for your approval first."


def assess(*, built_from: str | None, built_approval: ApprovalRef | None, current: ApprovalRef | None, marketplace: str, product: str | None) -> dict[str, Any]:
    """{"state", "reason", "marketplace", "product", "builtFrom", "currentApproved", "explanation", "nextStep"}. OUTDATED only when the seller approved a DIFFERENT title after the one
    this pack was built from; the words differ and the later approval is newer."""
    where = f"{product or 'this product'} on {marketplace.title()}"
    base: dict[str, Any] = {"state": UNKNOWN, "reason": None, "marketplace": marketplace, "product": product, "builtFrom": built_from or None, "currentApproved": None, "explanation": "", "nextStep": None}

    def done(state: str, reason: str, explanation: str, **extra: Any) -> dict[str, Any]:
        return {**base, "state": state, "reason": reason, "explanation": explanation, **extra}

    if not built_from or not norm(built_from):
        return done(UNKNOWN, "NO_PACK_TITLE", "I cannot find the title this listing was written from, so I cannot tell whether it is current.")
    if current is None or not norm(current.text):
        return done(UNKNOWN, "NO_APPROVED_TITLE", f"You have not approved a title for {where}, so there is nothing to compare this listing with.")
    if norm(built_from) == norm(current.text):
        return done(CURRENT, "SAME_TITLE", f"This listing was written from the title you currently have approved for {where}.")
    if built_approval is None:
        return done(UNKNOWN, "TYPED_TITLE", f"This listing was written from a title you typed rather than one you approved, so I cannot say it is out of date. Your approved title for {where} is different.")
    if built_approval.id == current.id:
        return done(CURRENT, "SAME_APPROVAL", f"This listing was written from the title you currently have approved for {where}.")
    if current.approved_at > built_approval.approved_at:
        return done(
            OUTDATED, "NEWER_APPROVAL",
            f"This listing for {where} was built from a previous title. Since then you approved a different title. The listing is still saved exactly as it was; it has not been edited or relabelled.",
            currentApproved=current.text, nextStep=NEXT_STEP,
        )
    return done(UNKNOWN, "APPROVAL_NOT_NEWER", f"The title you currently have approved for {where} is not newer than the one this listing was written from, so I do not call it out of date.")
