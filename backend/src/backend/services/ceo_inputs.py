"""Inputs the seller confirmed in chat for the new-product decision, saved as the CFO's own stored inputs (spec §6.36).

The seller answered the CEO's questions and said "yes" on a confirm card that listed exactly what would be saved, so the CEO writes the supplier quote and the batch
budget through the SAME write path the CFO page uses (`cfo_actions.enter_expense`, with the same `financials.adjust` permission and CFO entitlement). Nothing is
defaulted. Existing stored values are never touched: a quote or budget that is already active is left alone (the engine would otherwise have to ask which to use),
and a retry of the same confirmed answer finds the row it already wrote (matched by `reason`) instead of saving a second one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from backend.agents.ceo_hub import CFO_ENTER_EXPENSE
from backend.auth.permissions import FINANCIALS_ADJUST, has_permission
from backend.entitlement import resolve_cfo_entitlement
from backend.services import ceo_reads
from backend.services.cfo_actions import enter_expense


class CannotSave(Exception):
    """Plain words for the seller; nothing was saved."""


def _mine(rows: list[dict[str, Any]], ref: str) -> bool:
    return any(r.get("reason") == ref for r in rows)


def save_new_product_inputs(
    tenant_id: UUID, *, created_by: UUID, role: Any, permissions: Any, sku: str, save: Mapping[str, Any], ref: str,
) -> list[str]:
    """Returns one plain line per thing saved. Raises `CannotSave` (nothing written) when the member may not write or the CFO is not available to them."""
    if role is None or not has_permission(role=role, permissions=permissions, key=FINANCIALS_ADJUST):
        raise CannotSave("you do not have permission to save financial inputs, so I saved nothing (ask your account owner to add them)")
    if not resolve_cfo_entitlement(tenant_id, direct_action_code=CFO_ENTER_EXPENSE).passed:
        raise CannotSave("saving financial inputs is not part of your current plan, so I saved nothing")
    done: list[str] = []
    quote = save.get("quote")
    if quote:
        rows = ceo_reads.stored_quotes(tenant_id, sku)
        if not rows:
            enter_expense(tenant_id, target_type="SKU", target_ref=sku, field="supplier.quote", value=dict(quote), created_by=created_by, reason=ref)
            done.append(f"Saved the supplier quote from {quote['supplier_name']} for {sku}.")
        elif _mine(rows, ref):
            done.append(f"The supplier quote from {quote['supplier_name']} was already saved.")
    budget = save.get("budget_paise")
    if budget is not None:
        rows = ceo_reads.stored_budget(tenant_id)
        if not rows:
            enter_expense(tenant_id, target_type="ACCOUNT", target_ref=str(tenant_id), field="batch.budget", value={"amount_paise": int(budget)}, created_by=created_by, reason=ref)
            done.append("Saved your batch budget.")
        elif _mine(rows, ref):
            done.append("Your batch budget was already saved.")
    return done
