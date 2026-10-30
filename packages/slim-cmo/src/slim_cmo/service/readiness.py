"""Saving buyer-question sets and readiness assessments (CMO 3.0 M5). Zero units, no model, no network. Each result is stored once, exactly as shown, idempotent per (tenant, request_key).

Also the keyword analysis for a product (the M2 rules over the seller's confirmed facts) without needing a title set, so readiness and buyer questions can reuse it.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from slim_cmo import billing
from slim_cmo.ci_inputs import CiInputs
from slim_cmo.generation.facts import build_fact_context
from slim_cmo.keywords.intelligence import KeywordInputs
from slim_cmo.keywords.intelligence import analyse as analyse_keywords
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.keywords import _NICHE, ci_themes
from slim_cmo.service.models import Actor, GenerationStore
from slim_cmo.types import Marketplace

_TABLES = {"questions": "cmo_buyer_question_set", "readiness": "cmo_readiness_assessment"}


def save_result(actor: Actor, kind: str, sku: str, method: str, result: dict[str, Any], request_key: str, agent_run_id: UUID | None = None) -> tuple[str, bool]:
    """(row id, reused). The same request key returns the saved row unchanged; nothing is overwritten."""
    table = _TABLES[kind]
    key = billing.normalise_request_key(request_key)
    with tenant_scope(actor.tenant_id) as conn:
        found = conn.execute(text(f"SELECT id FROM {table} WHERE tenant_id = :t AND request_key = :k"), {"t": actor.tenant_id, "k": key}).first()
        if found is not None:
            return str(found.id), True
        row = conn.execute(text(f"INSERT INTO {table} (tenant_id, sku, method, result, request_key, created_by, agent_run_id) VALUES (:t, :sku, :m, CAST(:r AS jsonb), :k, :u, :run) RETURNING id"),
                           {"t": actor.tenant_id, "sku": sku, "m": method, "r": json.dumps(result), "k": key, "u": actor.user_id, "run": agent_run_id}).one()
    return str(row.id), False


def keyword_analysis(store: GenerationStore, tenant: UUID, sku: str, marketplace: Marketplace | None = None, ci: CiInputs | None = None) -> tuple[dict[str, Any], Any]:
    """(the M2 keyword analysis, the fact context) for one product's confirmed facts."""
    ctx = build_fact_context(list(store.load_facts(tenant, sku)))
    by = {a.name.casefold(): a.value for a in ctx.eligible if a.value}
    themes, n = ci_themes(ci)
    with tenant_scope(tenant) as conn:
        niche = tuple(str(r.term) for r in conn.execute(_NICHE, {"t": tenant}))
    kw = analyse_keywords(KeywordInputs(by.get("product_name"), by.get("brand"), tuple(a for a in [*ctx.eligible, *(a for a, _ in ctx.ineligible)] if a.name.casefold() != "product_name"),
                                        tuple(ctx.fact_ids), themes, n, niche, marketplace))
    return kw, ctx
