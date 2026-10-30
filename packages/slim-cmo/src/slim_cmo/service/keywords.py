"""Keyword intelligence service (CMO 3.0 M2): load the seller's confirmed facts, run the pure analysis, save the result once. Zero units, no model, no network.

Idempotent per (tenant, request_key): the same key returns the saved analysis unchanged. A different key is a new analysis (facts may have changed), and each one is kept.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text

from slim_cmo import billing
from slim_cmo.ci_inputs import CiInputs
from slim_cmo.claims import Attribute
from slim_cmo.generation.facts import build_fact_context
from slim_cmo.keywords.intelligence import METHOD, CiTheme, KeywordInputs, analyse
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.errors import InvalidConfirmation
from slim_cmo.service.models import Actor, GenerationStore
from slim_cmo.types import Marketplace

_FIND = text("SELECT id, sku, marketplace, status, result, created_at FROM cmo_keyword_analysis WHERE tenant_id = :t AND request_key = :k")
_INSERT = text(
    """
    INSERT INTO cmo_keyword_analysis (tenant_id, sku, marketplace, method, status, result, request_key, created_by)
    VALUES (:t, :sku, :mp, :method, :status, CAST(:result AS jsonb), :k, :u) RETURNING id, created_at
    """
)
_LATEST = text(
    "SELECT id, sku, marketplace, status, result, created_at FROM cmo_keyword_analysis WHERE tenant_id = :t AND sku = :sku ORDER BY created_at DESC, id LIMIT :limit"
)
_NICHE = text("SELECT term FROM cmo_niche_term WHERE tenant_id = :t AND status = 'CONFIRMED' ORDER BY term")


@dataclass(frozen=True, slots=True)
class KeywordRequest:
    request_key: str
    sku: str
    marketplace: Marketplace | None = None
    ci: CiInputs | None = None  # brokered by the CEO; derived theme words only


def _row(r: Any) -> dict[str, Any]:
    res = dict(r.result) if isinstance(r.result, dict) else json.loads(r.result)
    return {"analysisId": str(r.id), "sku": r.sku, "marketplace": r.marketplace, "createdAt": r.created_at.isoformat(), **res}


def ci_themes(ci: CiInputs | None) -> tuple[tuple[CiTheme, ...], int]:
    """Every derived single-word theme with the ids of the competitor listings that carried it (a count, never an estimate)."""
    if ci is None:
        return (), 0
    blocked = {t.casefold() for t in ci.exclude_terms}
    ids: dict[str, list[str]] = {}
    for ins in ci.insights:
        for t in (*ins.keyword_themes, *ins.benefit_terms):
            w = t.strip().casefold()
            if w and w.isalpha() and w not in blocked and ins.id not in ids.setdefault(w, []):
                ids[w].append(ins.id)
    return tuple(CiTheme(w, tuple(v)) for w, v in sorted(ids.items())), len(ci.insights)


class KeywordIntelligenceService:
    def __init__(self, store: GenerationStore) -> None:
        self._store = store

    def run(self, actor: Actor, req: KeywordRequest) -> dict[str, Any]:
        key = billing.normalise_request_key(req.request_key)
        sku = (req.sku or "").strip()
        if not sku:
            raise InvalidConfirmation("a sku is required so the analysis uses the right product's facts")
        with tenant_scope(actor.tenant_id) as conn:
            found = conn.execute(_FIND, {"t": actor.tenant_id, "k": key}).first()
        if found is not None:
            return {**_row(found), "reused": True}
        facts = list(self._store.load_facts(actor.tenant_id, sku))
        ctx = build_fact_context(facts)
        attrs: list[Attribute] = [*ctx.eligible, *(a for a, _ in ctx.ineligible)]
        by = {a.name.casefold(): a.value for a in ctx.eligible if a.value}
        themes, n = ci_themes(req.ci)
        with tenant_scope(actor.tenant_id) as conn:
            niche = tuple(str(r.term) for r in conn.execute(_NICHE, {"t": actor.tenant_id}))
        result = analyse(KeywordInputs(
            product_name=by.get("product_name"), brand=by.get("brand"), attributes=tuple(a for a in attrs if a.name.casefold() != "product_name"),
            fact_ids=tuple(ctx.fact_ids), ci_themes=themes, ci_insight_count=n, niche_terms=niche, marketplace=req.marketplace,
        ))
        with tenant_scope(actor.tenant_id) as conn:
            saved = conn.execute(_INSERT, {"t": actor.tenant_id, "sku": sku, "mp": req.marketplace.value if req.marketplace else None, "method": METHOD, "status": result["status"],
                                           "result": json.dumps(result), "k": key, "u": actor.user_id}).one()
        return {"analysisId": str(saved.id), "sku": sku, "marketplace": req.marketplace.value if req.marketplace else None, "createdAt": saved.created_at.isoformat(), **result, "reused": False}

    def latest(self, tenant_id: UUID, sku: str, limit: int = 5) -> Sequence[dict[str, Any]]:
        with tenant_scope(tenant_id) as conn:
            return [_row(r) for r in conn.execute(_LATEST, {"t": tenant_id, "sku": sku, "limit": limit})]
