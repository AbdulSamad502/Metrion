"""Claim-lifecycle data access (docs/specs/cfo-phase3-scope.md 3d). Append-only events; the current state is derived."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from calc_engine.leak_claims import ClaimRuleError, claim_draft_text, effective_state, validate_transition
from calc_engine.repositories import read_model_version_repo
from calc_engine.repositories.tenant_context import tenant_scope


@dataclass(frozen=True, slots=True)
class ClaimView:
    leak_finding_id: UUID
    marketplace: str
    category: str
    state: str
    history: tuple[tuple[str, str, datetime, str | None], ...]  # (from, to, at, note)


def _finding(conn: Connection, tenant_id: UUID, finding_id: UUID) -> dict[str, Any]:
    row = conn.execute(text("SELECT id, marketplace, leak_category, status, reconciliation_exception_id FROM leak_finding WHERE tenant_id = :t AND id = :f"),
                       {"t": str(tenant_id), "f": str(finding_id)}).one_or_none()
    if row is None:
        raise ClaimRuleError("that discrepancy does not exist")
    return dict(row._mapping)


def _latest(conn: Connection, tenant_id: UUID, finding_id: UUID) -> str | None:
    r = conn.execute(text("SELECT to_state FROM leak_claim_event WHERE tenant_id = :t AND leak_finding_id = :f ORDER BY created_at DESC, id DESC LIMIT 1"),
                     {"t": str(tenant_id), "f": str(finding_id)}).one_or_none()
    return None if r is None else str(r[0])


def current_view(tenant_id: UUID, finding_id: UUID) -> ClaimView:
    with tenant_scope(tenant_id) as conn:
        f = _finding(conn, tenant_id, finding_id)
        hist = conn.execute(text("SELECT from_state, to_state, created_at, note FROM leak_claim_event WHERE tenant_id = :t AND leak_finding_id = :f ORDER BY created_at, id"),
                            {"t": str(tenant_id), "f": str(finding_id)}).all()
        return ClaimView(finding_id, f["marketplace"], f["leak_category"], effective_state(f["status"], _latest(conn, tenant_id, finding_id)),
                         tuple((a, b, c, d) for a, b, c, d in hist))


def transition(tenant_id: UUID, finding_id: UUID, to_state: str, actor: UUID, note: str | None = None) -> ClaimView:
    """The seller reports a step. Forward-only (see `leak_claims`); every step is a new row. Bumps the read-model version so cached answers refresh."""
    with tenant_scope(tenant_id) as conn:
        f = _finding(conn, tenant_id, finding_id)
        cur = effective_state(f["status"], _latest(conn, tenant_id, finding_id))
        validate_transition(f["marketplace"], cur, to_state)
        conn.execute(text("INSERT INTO leak_claim_event (id, tenant_id, leak_finding_id, from_state, to_state, actor, note) VALUES (:id, :t, :f, :a, :b, :u, :n)"),
                     {"id": str(uuid4()), "t": str(tenant_id), "f": str(finding_id), "a": cur, "b": to_state, "u": str(actor), "n": (note or "").strip()[:500] or None})
        read_model_version_repo.bump_on(conn, tenant_id)
    return current_view(tenant_id, finding_id)


def order_refs(tenant_id: UUID, finding_id: UUID) -> list[str]:
    """Order / line references behind a finding, from the reconciliation exception's own rows (sales side, settlement side, ambiguous candidates)."""
    with tenant_scope(tenant_id) as conn:
        f = _finding(conn, tenant_id, finding_id)
        rows = conn.execute(text(
            "SELECT s.order_ref, s.line_ref, t.order_ref, t.line_ref, e.candidate_sales_line_ids FROM reconciliation_exception e "
            "LEFT JOIN sales_line s ON s.id = e.sales_line_id AND s.tenant_id = e.tenant_id LEFT JOIN settlement_line t ON t.id = e.settlement_line_id AND t.tenant_id = e.tenant_id "
            "WHERE e.tenant_id = :t AND e.id = :x"), {"t": str(tenant_id), "x": str(f["reconciliation_exception_id"])}).all()
        refs: set[str] = set()
        for so, sl, to, tl, cands in rows:
            refs.update(r for r in (so, sl, to, tl) if r)
            if cands:
                ids = [str(c) for c in (cands if isinstance(cands, list) else [])]
                if ids:
                    for o, l in conn.execute(text("SELECT order_ref, line_ref FROM sales_line WHERE tenant_id = :t AND id::text = ANY(:ids)"), {"t": str(tenant_id), "ids": ids}):
                        refs.update(r for r in (o, l) if r)
        return sorted(refs)


def draft(tenant_id: UUID, finding_id: UUID, actor: UUID) -> tuple[str, ClaimView]:
    """Builds the copyable text (identifiers only). Moves ACKNOWLEDGED -> CLAIM_DRAFTED on the first draft; later drafts just return the text."""
    view = current_view(tenant_id, finding_id)
    text_ = claim_draft_text(view.marketplace, view.category, order_refs(tenant_id, finding_id), str(finding_id))
    if view.state == "ACKNOWLEDGED":
        view = transition(tenant_id, finding_id, "CLAIM_DRAFTED", actor)
    elif view.state == "NEW":
        raise ClaimRuleError("acknowledge the discrepancy first; then a claim text can be drafted")
    elif view.state in ("SELLER_REPORTED_RESOLVED", "DISMISSED"):
        raise ClaimRuleError(f"this discrepancy is already {view.state.replace('_', ' ').lower()}")
    return text_, view
