"""The research brief the CEO saves for a seller who has just described their niche in chat (spec §6.35).

Product Intelligence runs from a saved, READY niche brief (category, budget, marketplaces). A seller who answered the CEO's questions and said "yes, run it" has
supplied exactly those inputs, so the CEO saves them as the seller's own brief; nothing is added or defaulted, and the brief is the same record the Product Intelligence
page creates. A retry of the same confirmed answer reuses the brief it already made (matched by the answering message's id) instead of saving a second one.
Every read and write is tenant-scoped through the PI repositories.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from backend.services import pi_actions


def create_ready_brief(tenant_id: UUID, *, created_by: UUID, inputs: Mapping[str, Any], ref: str) -> UUID:
    """Raises ValueError when the brief cannot be made READY (a missing category, budget or marketplace)."""
    for row in pi_actions.list_niche_briefs(tenant_id):
        if (row.get("constraints") or {}).get("ceo_ref") == ref and row.get("status") in ("DRAFT", "READY"):
            pi_actions.mark_niche_brief_ready(tenant_id, UUID(str(row["id"])), readied_at=datetime.now(timezone.utc))
            return UUID(str(row["id"]))
    brief = pi_actions.create_niche_brief_draft(
        tenant_id, created_by=created_by, category_text=str(inputs["category_text"]), budget_paise=int(inputs["budget_paise"]),
        target_price_min_paise=inputs.get("target_price_min_paise"), target_price_max_paise=inputs.get("target_price_max_paise"),
        marketplaces=list(inputs["marketplaces"]), constraints={"ceo_ref": ref, "source": "CEO chat"},
    )
    pi_actions.mark_niche_brief_ready(tenant_id, brief, readied_at=datetime.now(timezone.utc))
    return brief
