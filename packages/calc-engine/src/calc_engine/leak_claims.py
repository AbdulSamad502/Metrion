"""Claim lifecycle rules and the claim draft text (docs/specs/cfo-phase3-scope.md LD2, LD3). Pure: no I/O, no clock, no money, no model.

The SELLER reports claim progress (Metrion never files). States move forward only; DISMISSED is allowed from any non-terminal state. The draft is
copyable text containing identifiers only — never an amount, a total, a figure or any generated prose beyond fixed wording.
"""

from __future__ import annotations

from collections.abc import Sequence

STATES = ("NEW", "ACKNOWLEDGED", "CLAIM_DRAFTED", "SELLER_REPORTED_RAISED", "SELLER_REPORTED_RESOLVED", "DISMISSED")
TERMINAL = frozenset({"SELLER_REPORTED_RESOLVED", "DISMISSED"})
_FORWARD = {
    "NEW": ("ACKNOWLEDGED",),
    "ACKNOWLEDGED": ("CLAIM_DRAFTED",),
    "CLAIM_DRAFTED": ("SELLER_REPORTED_RAISED",),
    "SELLER_REPORTED_RAISED": ("SELLER_REPORTED_RESOLVED",),
}
# A finding recorded before the lifecycle existed carries one of the older statuses; they map onto the lifecycle conservatively.
_LEGACY = {"NEW": "NEW", "ACKNOWLEDGED": "ACKNOWLEDGED", "ACTIONED": "ACKNOWLEDGED", "DISMISSED": "DISMISSED"}
MAX_ORDER_IDS_IN_DRAFT = 50

AMAZON_WITHHELD = "Amazon findings are withheld until the order-to-settlement match key has been verified against a real export, so no claim steps are available yet."


class ClaimRuleError(ValueError):
    """A transition or request the claim rules refuse; the message is safe to show the seller."""


def effective_state(finding_status: str, latest_event_state: str | None) -> str:
    return latest_event_state if latest_event_state is not None else _LEGACY.get(finding_status, "NEW")


def validate_transition(marketplace: str, current: str, to: str) -> None:
    if to not in STATES or to == "NEW":
        raise ClaimRuleError(f"unknown claim state {to!r}")
    if marketplace.upper() == "AMAZON":
        raise ClaimRuleError(AMAZON_WITHHELD)
    if current in TERMINAL:
        raise ClaimRuleError(f"this discrepancy is already {current.replace('_', ' ').lower()}; it cannot move again")
    if to == "DISMISSED":
        return
    if to not in _FORWARD.get(current, ()):
        nxt = ", ".join(s.replace("_", " ").lower() for s in _FORWARD.get(current, ())) or "nothing"
        raise ClaimRuleError(f"a claim cannot go from {current.replace('_', ' ').lower()} to {to.replace('_', ' ').lower()}; the next step is: {nxt}")


def claim_draft_text(marketplace: str, category: str, order_ids: Sequence[str], finding_ref: str) -> str:
    """Copyable text with identifiers only. At most `MAX_ORDER_IDS_IN_DRAFT` ids are listed; the rest are counted, never silently dropped."""
    if marketplace.upper() == "AMAZON":
        raise ClaimRuleError(AMAZON_WITHHELD)
    ids = sorted({o for o in order_ids if o})
    if not ids:
        raise ClaimRuleError("no order or line reference could be found for this discrepancy, so there is nothing to put in a claim")
    shown, more = ids[:MAX_ORDER_IDS_IN_DRAFT], len(ids) - MAX_ORDER_IDS_IN_DRAFT
    lines = [
        f"Marketplace: {marketplace.title()}",
        f"Discrepancy identified: {category.replace('_', ' ').lower()}",
        "Orders / lines concerned:",
        *[f"- {o}" for o in shown],
    ]
    if more > 0:
        lines.append(f"- and {more} more (the full list is in Metrion under reference {finding_ref})")
    lines += [f"Reference in Metrion: {finding_ref}",
              "Please review these settlements against the orders listed above. This is a discrepancy Metrion identified from uploaded reports; it has not been filed by Metrion."]
    return "\n".join(lines)
