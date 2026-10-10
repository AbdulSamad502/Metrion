"""The ONE seam through which CEO code reads the owning specialists' persisted data that has no CFO-style repository import (spec §6.13 hard rule 5).

CI, PI and CMO each expose a small tenant-scoped read function in their own package; this module re-exports exactly those, and nothing else, so the
architecture test can keep `backend/ceo` free of direct specialist imports. Read-only: no capture, no fetch, no model call, no write."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from calc_engine.formulas.cost_components import weighted_average_cost
from calc_engine.repositories import config_repo, manual_adjustment_repo
from calc_engine.types import Unavailable
from competitor_intelligence.handoff import CiHandoffSnapshot, build_ci_handoff_snapshot
from competitor_intelligence.repositories import competitor_listing_insight_repo, competitor_url_repo
from competitor_intelligence.types import Unavailable as CiUnavailable
from product_intelligence.repositories import pi_research_run_repo, product_candidate_repo
from slim_cmo.repositories import generation_repo as cmo_generation_repo

from cfo.repositories import agent_data_request_repo

from backend.services import cfo_actions

__all__ = [
    "CiHandoffSnapshot", "CiUnavailable", "competitor_handoff", "list_active_competitors", "latest_pi_run", "recent_cmo_generations",
    "StoredCogs", "stored_cogs", "SalesHistory", "sales_history", "stored_quotes", "stored_budget", "fee_reference_options",
]


def list_active_competitors(tenant_id: UUID, *, limit: int) -> list[dict[str, Any]]:
    return competitor_url_repo.list_active(tenant_id, limit=limit)


def competitor_handoff(tenant_id: UUID, competitor_url_id: UUID, *, now: Any) -> CiHandoffSnapshot | CiUnavailable:
    return build_ci_handoff_snapshot(tenant_id, competitor_url_id, now=now)


def latest_pi_run(tenant_id: UUID, *, finished_only: bool = False) -> dict[str, Any] | None:
    return pi_research_run_repo.latest_run_for_tenant(tenant_id, finished_only=finished_only)


def recent_cmo_generations(tenant_id: UUID, *, limit: int) -> list[dict[str, Any]]:
    return cmo_generation_repo.list_recent_for_tenant(tenant_id, limit=limit)


# ---- stored seller inputs and assembled history for the two decision playbooks (spec 6.33). Reads only; the engine selects and computes. ----
@dataclass(frozen=True, slots=True)
class StoredCogs:
    """The seller's stored per-unit cost for a SKU as of a date, chosen by the engine's own `weighted_average_cost` (latest effective entry, no arithmetic).
    `amount_paise` is None when none is stored, with the engine's reason: a missing cost is never zero."""

    amount_paise: int | None
    effective_from: date | None
    reason: str | None
    adjustment_ids: tuple[str, ...]


def stored_cogs(tenant_id: UUID, sku: str, as_of: date) -> StoredCogs:
    history = cfo_actions.resolve_cost_history_for_skus(tenant_id, [sku]).get(sku, [])
    ids = tuple(str(r["id"]) for r in manual_adjustment_repo.active_adjustments_for_target(tenant_id, target_type="SKU", target_ref=sku, field="cogs_per_unit"))
    chosen = weighted_average_cost(sku, as_of, history)
    if isinstance(chosen, Unavailable):
        return StoredCogs(None, None, chosen.reason, ids)
    effective = max((e.effective_from for e in history if e.effective_from <= as_of and e.amount_paise == chosen), default=None)
    return StoredCogs(chosen.value, effective, None, ids)


@dataclass(frozen=True, slots=True)
class SalesHistory:
    """One SKU's sales lines for a period in the engine's full canonical line shape (return / RTO / cancellation status included), as plain dicts the CFO
    batch-size route accepts. Lines that could not be honestly assembled are counted and their reasons kept: never dropped silently."""

    lines: tuple[dict[str, Any], ...]
    blocked_count: int
    blocked_reasons: tuple[str, ...]
    active_adjustment_ids: tuple[str, ...]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _line_dict(line: Any) -> dict[str, Any]:
    return {
        "sales_line_id": str(line.sales_line_id), "marketplace": line.marketplace, "document_type": line.document_type, "quantity": line.quantity,
        "invoice_date": _iso(line.invoice_date), "dispatch_date": _iso(line.dispatch_date), "order_date": _iso(line.order_date),
        "gross_item_amount_paise": line.gross_item_amount.value,
        "components": [{"id": str(c.id), "component_kind": c.component_kind, "component_code": c.component_code, "source_side": c.source_side, "amount_paise": c.amount.value}
                       for c in line.components],
        "confidence": line.confidence.value, "cancellation_state": line.cancellation_state, "return_status": line.return_status, "returned_qty": line.returned_qty,
        "refunded_amount_paise": line.refunded_amount.value if line.refunded_amount is not None else None, "rto_status": line.rto_status, "rto_qty": line.rto_qty,
        "rto_outcome": line.rto_outcome, "quarantine_rule_ids": list(line.quarantine_rule_ids),
    }


def sales_history(tenant_id: UUID, sku: str, *, period_start: date, period_end: date) -> SalesHistory:
    out = cfo_actions.assemble_canonical_lines_for_period(tenant_id, period_start=period_start, period_end=period_end)
    mine = [ln for ln in out.lines if out.sku_by_line.get(str(ln.sales_line_id)) == sku]
    blocked = [b for b in out.blocked if out.sku_by_line.get(str(b.sales_line_id)) == sku]
    return SalesHistory(
        lines=tuple(_line_dict(ln) for ln in mine), blocked_count=len(blocked), blocked_reasons=tuple(dict.fromkeys(b.reason for b in blocked)),
        active_adjustment_ids=tuple(str(i) for i in out.active_adjustment_ids),
    )


def open_data_request(tenant_id: UUID, request_id: UUID) -> dict[str, Any] | None:
    """One OPEN `agent_data_request` of this tenant (RLS-scoped), or None."""
    return next((r for r in agent_data_request_repo.list_for_tenant(tenant_id) if str(r["id"]) == str(request_id) and r["status"] == "OPEN"), None)


def answer_data_request(tenant_id: UUID, request_id: UUID, adjustment_id: UUID) -> None:
    agent_data_request_repo.mark_answered(tenant_id, request_id, answered_with_kind="MANUAL_ADJUSTMENT", answered_with_id=adjustment_id)


def pi_idea_keywords(tenant_id: UUID, name: str, *, limit: int = 6) -> list[str]:
    """The keyword themes Product Intelligence stored for the idea of that name in the latest finished run (names matched case-insensitively), else []. Public-web
    themes, not verified."""
    run = pi_research_run_repo.latest_run_for_tenant(tenant_id, finished_only=True)
    if run is None:
        return []
    for c in product_candidate_repo.list_candidates_for_run(tenant_id, UUID(str(run["id"]))):
        if str(c.get("candidate_title", "")).casefold() == name.strip().casefold():
            return [str(k) for k in ((c.get("keyword_themes") or {}).get("top_keywords") or [])][:limit]
    return []


def ci_listing_keywords(tenant_id: UUID, *, now: Any, limit: int = 6) -> tuple[str, list[str]] | None:
    """(competitor label, keyword themes) from the most recent listing insight of the first tracked competitor that has one, else None. Derived from a captured
    listing; not verified."""
    for u in competitor_url_repo.list_active(tenant_id, limit=10):
        snap = build_ci_handoff_snapshot(tenant_id, UUID(str(u["id"])), now=now)
        if isinstance(snap, CiUnavailable):
            continue
        insight = competitor_listing_insight_repo.get_by_snapshot(tenant_id, snap.snapshot_id)
        words = list(((insight or {}).get("keyword_themes") or {}).keys())[:limit]
        if words:
            return str(u.get("label") or "a competitor"), [str(w) for w in words]
    return None


def stored_cost(tenant_id: UUID, sku: str) -> list[dict[str, Any]]:
    """Every ACTIVE `cogs_per_unit` at (SKU, sku), newest first."""
    return manual_adjustment_repo.active_adjustments_for_target(tenant_id, target_type="SKU", target_ref=sku, field="cogs_per_unit")


def stored_quotes(tenant_id: UUID, sku: str) -> list[dict[str, Any]]:
    """Every ACTIVE `supplier.quote` at (SKU, sku), newest first, as stored (the engine parses them; this only reads)."""
    return manual_adjustment_repo.active_adjustments_for_target(tenant_id, target_type="SKU", target_ref=sku, field="supplier.quote")


def stored_budget(tenant_id: UUID) -> list[dict[str, Any]]:
    """Every ACTIVE `batch.budget` at (ACCOUNT, tenant id), newest first."""
    return manual_adjustment_repo.active_adjustments_for_target(tenant_id, target_type="ACCOUNT", target_ref=str(tenant_id), field="batch.budget")


def fee_reference_options(tenant_id: UUID, *, as_of: date) -> list[dict[str, str]]:
    """The (marketplace, category, fee type) triples a margin can actually be priced for on `as_of` (persisted fee references only): a form offers these and
    nothing else, so a typed category can never silently fail to match."""
    return config_repo.fee_reference_options(tenant_id, as_of_date=as_of)
