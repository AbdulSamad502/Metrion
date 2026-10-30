"""Title analysis service (CMO 3.0 M3): load a saved title set, the seller's confirmed facts and the marketplace rule, run the pure analyzer, save the result once. Zero units, no model,
no network. Idempotent per (tenant, request_key). The rule used is the VERIFIED, current one only (tests may accept test-fixture rows, exactly like generation); when none exists the rule
check is NOT_ASSESSED, never a pass.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text

from slim_cmo import billing
from slim_cmo.ci_inputs import CiInputs
from slim_cmo.config import GENERATION_REQUIRED_KEYS, ConfigMissing, load_generation_config
from slim_cmo.constraints import ConstraintUnavailable, resolve_constraint
from slim_cmo.generation.facts import build_fact_context
from slim_cmo.keywords.intelligence import KeywordInputs
from slim_cmo.keywords.intelligence import analyse as analyse_keywords
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.errors import NotFound
from slim_cmo.service.keywords import _NICHE, ci_themes
from slim_cmo.service.models import Actor, GenerationStore
from slim_cmo.titles_analysis.analyzer import METHOD, AnalysisInputs, RuleContext, TitleOption, analyse_titles
from slim_cmo.types import ConstraintRowKind, OutputType
from slim_cmo.validators import check_title

_FIND = text("SELECT id, generation_id, marketplace, result, created_at FROM cmo_title_analysis WHERE tenant_id = :t AND request_key = :k")
_INSERT = text(
    """
    INSERT INTO cmo_title_analysis (tenant_id, generation_id, marketplace, method, result, request_key, created_by)
    VALUES (:t, :g, :mp, :method, CAST(:result AS jsonb), :k, :u) RETURNING id, created_at
    """
)
_LATEST = text("SELECT id, generation_id, marketplace, result, created_at FROM cmo_title_analysis WHERE tenant_id = :t AND generation_id = :g ORDER BY created_at DESC, id LIMIT :limit")


def _row(r: Any) -> dict[str, Any]:
    res = dict(r.result) if isinstance(r.result, dict) else json.loads(r.result)
    return {"analysisId": str(r.id), "generationId": str(r.generation_id), "createdAt": r.created_at.isoformat(), **res}


class TitleAnalysisService:
    def __init__(self, store: GenerationStore, *, clock: Callable[[], Any], accepted_row_kinds: frozenset[ConstraintRowKind] = frozenset({ConstraintRowKind.VERIFIED})) -> None:
        self._store, self._clock, self._kinds = store, clock, accepted_row_kinds

    def _rule(self, tenant: UUID, ts: Any, allowed_context: str) -> RuleContext:
        values = self._store.load_config(tenant, GENERATION_REQUIRED_KEYS, self._clock().date())
        cfg = load_generation_config(values)
        if isinstance(cfg, ConfigMissing):
            return RuleContext(reason="the marketplace rule settings are not configured")
        rows = self._store.load_constraints(tenant, ts.marketplace, self._kinds)
        res = resolve_constraint(rows, marketplace=ts.marketplace, category=ts.category_hint, output_type=OutputType.TITLE_SET, now=self._clock(),
                                 max_age_days=cfg.format_constraint_max_age_days, accepted_row_kinds=self._kinds)
        if isinstance(res, ConstraintUnavailable):
            return RuleContext(reason=f"no verified, current rule exists for {ts.marketplace.value.title()} ({res.reason.value.lower().replace('_', ' ')})")
        row = res.row

        def check(t: str) -> tuple[bool, tuple[str, ...], int]:
            c = check_title(t, row, allowed_context=allowed_context)
            return c.valid, tuple(v.code.value for v in c.violations), c.char_count

        return RuleContext(check=check, limit=row.title_max_chars, source_url=row.source_url, verified_at=row.verified_at.date().isoformat(), kind=row.row_kind.value)

    def run(self, actor: Actor, generation_id: UUID, request_key: str, ci: CiInputs | None = None) -> dict[str, Any]:
        tenant = actor.tenant_id
        key = billing.normalise_request_key(request_key)
        with tenant_scope(tenant) as conn:
            found = conn.execute(_FIND, {"t": tenant, "k": key}).first()
        if found is not None:
            return {**_row(found), "reused": True}
        ts = self._store.load_title_set(tenant, generation_id)
        if ts is None:
            raise NotFound("title set not found")  # a foreign or unknown id looks identical
        facts = list(self._store.load_facts(tenant, ts.sku)) if ts.sku else []
        ctx = build_fact_context(facts)
        by = {a.name.casefold(): a.value for a in ctx.eligible if a.value}
        product_name, brand = by.get("product_name"), by.get("brand")
        themes, n = ci_themes(ci)
        with tenant_scope(tenant) as conn:
            niche = tuple(str(r.term) for r in conn.execute(_NICHE, {"t": tenant}))
        kw = analyse_keywords(KeywordInputs(product_name, brand, tuple(a for a in [*ctx.eligible, *(a for a, _ in ctx.ineligible)] if a.name.casefold() != "product_name"),
                                            tuple(ctx.fact_ids), themes, n, niche, ts.marketplace))
        result = analyse_titles(AnalysisInputs(
            options=[TitleOption(str(o.id), o.rank, o.title_text) for o in ts.options], facts=ctx, product_name=product_name, brand=brand, keyword_result=kw,
            rule=self._rule(tenant, ts, ctx.allowed_context), ci_theme_words=tuple(t.word for t in themes), marketplace=ts.marketplace,
        ))
        result["keywordMethod"] = kw.get("method")
        with tenant_scope(tenant) as conn:
            saved = conn.execute(_INSERT, {"t": tenant, "g": generation_id, "mp": ts.marketplace.value, "method": METHOD, "result": json.dumps(result), "k": key, "u": actor.user_id}).one()
        return {"analysisId": str(saved.id), "generationId": str(generation_id), "createdAt": saved.created_at.isoformat(), **result, "reused": False}

    def latest(self, tenant_id: UUID, generation_id: UUID, limit: int = 5) -> Sequence[dict[str, Any]]:
        with tenant_scope(tenant_id) as conn:
            return [_row(r) for r in conn.execute(_LATEST, {"t": tenant_id, "g": generation_id, "limit": limit})]
