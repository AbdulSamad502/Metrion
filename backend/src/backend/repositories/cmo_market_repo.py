"""CMO 3.0 M10: the seller's saved market-trend reports, read-only. Tenant-scoped (RLS). No model, no web search; the reports were made and billed by the existing market-trends flow."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.tenant_context import tenant_scope

_REPORTS = text(
    "SELECT id, generation_id, generated_at, sections FROM cmo_trend_report WHERE tenant_id = :t ORDER BY generated_at DESC, id DESC LIMIT :n"
)


def recent_reports(tenant_id: UUID, limit: int) -> list[dict[str, Any]]:
    """The newest saved reports (sections as stored: each researched section holds its state and findings with their cited sources). Newest first."""
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_REPORTS, {"t": tenant_id, "n": max(1, min(int(limit), 20))}).all()
    return [{"id": r.id, "generationId": r.generation_id, "generatedAt": r.generated_at.isoformat(), "sections": r.sections if isinstance(r.sections, dict) else {}} for r in rows]
