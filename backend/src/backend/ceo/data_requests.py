"""When a CFO leg says what it is missing, the CEO asks for exactly that - spec section 6.37.

A leg's result may carry the id of an OPEN `agent_data_request`. This module decides, by code, whether the CEO can collect that field in chat (a cost per unit, a
supplier quote, a batch budget), and only when nothing of it is stored yet. It builds the question for the guided input session and remembers the original request so the
same question can be re-run after the seller confirms. It reads and decides; the save is `services/ceo_inputs.py`, the arithmetic is the engine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from backend.ceo.contract import LegResult
from backend.services import ceo_reads

SESSION_FOR_FIELD: Mapping[str, str] = {"cogs_per_unit": "dr.cogs_per_unit", "supplier.quote": "dr.supplier_quote", "batch.budget": "dr.batch_budget"}


def request_ids(legs: Sequence[LegResult]) -> list[UUID]:
    out: list[UUID] = []
    for leg in legs:
        payload = leg.payload or {}
        raw = [payload.get("dataRequestId"), *(payload.get("dataRequestIds") or [])]
        for v in raw:
            try:
                if v:
                    out.append(UUID(str(v)))
            except ValueError:
                continue
    return list(dict.fromkeys(out))


def collectable(tenant_id: UUID, legs: Sequence[LegResult], sku: str | None) -> tuple[str, dict[str, Any]] | None:
    """(session key, the open request row) for the first request the CEO can collect now, else None. Nothing of the field may already be stored: asking for a second
    value would make the engine ask which to use."""
    for rid in request_ids(legs):
        row = ceo_reads.open_data_request(tenant_id, rid)
        session = SESSION_FOR_FIELD.get(str(row["requested_field"])) if row else None
        if row is None or session is None:
            continue
        if session == "dr.batch_budget":
            if not ceo_reads.stored_budget(tenant_id):
                return session, row
        elif sku:
            stored = ceo_reads.stored_cost(tenant_id, sku) if session == "dr.cogs_per_unit" else ceo_reads.stored_quotes(tenant_id, sku)
            if not stored:
                return session, row
    return None
