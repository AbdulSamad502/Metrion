"""Inputs the seller confirmed in chat for the new-product decision, saved as the CFO's own stored inputs (spec §6.36).

The seller answered the CEO's questions and said "yes" on a confirm card that listed exactly what would be saved, so the CEO writes the supplier quote and the batch
budget through the SAME write path the CFO page uses (`cfo_actions.enter_expense`, with the same `financials.adjust` permission and CFO entitlement). Nothing is
defaulted. Existing stored values are never touched: a quote or budget that is already active is left alone (the engine would otherwise have to ask which to use),
and a retry of the same confirmed answer finds the row it already wrote (matched by `reason`) instead of saving a second one.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import UUID

from backend.agents.ceo_hub import CFO_ENTER_EXPENSE
from backend.auth.permissions import FINANCIALS_ADJUST, has_permission
from backend.entitlement import resolve_cfo_entitlement
from backend.services import ceo_reads
from backend.services.cfo_actions import enter_expense


class CannotSave(Exception):
    """Plain words for the seller; nothing was saved."""


def _answered(tenant_id: UUID, save: Mapping[str, Any], adjustment_id: UUID) -> None:
    """The data request this answers (when the save came from one) is closed with what answered it."""
    rid = save.get("request_id")
    if rid:
        try:
            ceo_reads.answer_data_request(tenant_id, UUID(str(rid)), adjustment_id)
        except Exception:  # noqa: BLE001 - the value is saved; a failed bookkeeping update must not undo or hide that
            pass


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
    cost = save.get("cost_paise")
    if cost is not None:
        rows = ceo_reads.stored_cost(tenant_id, sku)
        if not rows:
            adj = enter_expense(tenant_id, target_type="SKU", target_ref=sku, field="cogs_per_unit",
                                value={"amount_paise": int(cost), "effective_from": date.today().isoformat()}, created_by=created_by, reason=ref)
            done.append(f"Saved your cost per unit for {sku}.")
            _answered(tenant_id, save, adj)
        elif _mine(rows, ref):
            done.append("Your cost per unit was already saved.")
    quote = save.get("quote")
    if quote:
        rows = ceo_reads.stored_quotes(tenant_id, sku)
        if not rows:
            adj = enter_expense(tenant_id, target_type="SKU", target_ref=sku, field="supplier.quote", value=dict(quote), created_by=created_by, reason=ref)
            _answered(tenant_id, save, adj)
            done.append(f"Saved the supplier quote from {quote['supplier_name']} for {sku}.")
        elif _mine(rows, ref):
            done.append(f"The supplier quote from {quote['supplier_name']} was already saved.")
    budget = save.get("budget_paise")
    if budget is not None:
        rows = ceo_reads.stored_budget(tenant_id)
        if not rows:
            adj = enter_expense(tenant_id, target_type="ACCOUNT", target_ref=str(tenant_id), field="batch.budget", value={"amount_paise": int(budget)}, created_by=created_by, reason=ref)
            _answered(tenant_id, save, adj)
            done.append("Saved your batch budget.")
        elif _mine(rows, ref):
            done.append("Your batch budget was already saved.")
    return done
