"""Tenant-scoped READ queries behind the read-only CMO showcase (docs/specs/ceo-cmo-delegation.md 6.8-6.10) and the one telemetry write.

Every function runs inside `tenant_scope` (RLS, FORCE) AND filters `tenant_id` explicitly in SQL (defence in depth). Nothing here generates, meters, calls a
model or a network service, or computes anything beyond counts: character / byte counts are the ones stored with the artefact, or (for bullets and descriptions,
which store only text) a deterministic count under the artefact's own stored counting rule. Stored text is returned verbatim; nothing is invented, so a missing
publication date is `None`, never a guessed date.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from slim_cmo.textnorm import count_by_rule, count_chars, utf8_bytes

from backend.tenant_context import tenant_scope

_LABEL = (
    "COALESCE((SELECT sf.fact_value FROM seller_fact sf WHERE sf.tenant_id = g.tenant_id AND sf.sku = g.sku "
    "AND sf.attribute_name = 'product_name' ORDER BY sf.provided_at DESC LIMIT 1), g.sku)"
)
_NIL = "CAST(:{p} AS {t}) IS NULL OR "


def like_pattern(q: str | None) -> str | None:
    if q is None or not q.strip():
        return None
    return "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _origin(investigation_id: UUID | None) -> dict[str, Any]:
    return {"investigationId": str(investigation_id) if investigation_id else None, "turnId": None,
            "kind": "CEO_CHAT" if investigation_id else "PRE_CHAT_WORKFLOW"}


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


def _strs(v: object) -> list[str]:
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else []


def _count(s: str, rule: str | None) -> int:
    return count_by_rule(s, rule) if rule in ("UTF16_CODE_UNITS", "CODE_POINTS") else count_chars(s)


# ---- products -------------------------------------------------------------------------------------------------------------

_PRODUCTS = text(
    f"""
    WITH skus AS (
      SELECT g.sku, max(g.created_at) AS last_at FROM cmo_generation g
      WHERE g.tenant_id = :t AND g.status = 'COMPLETE' AND g.sku IS NOT NULL AND g.output_type <> 'TREND_REPORT'
      GROUP BY g.sku ORDER BY max(g.created_at) DESC, g.sku LIMIT :limit
    )
    SELECT s.sku, s.last_at, g.marketplace, count(*) AS n,
           (SELECT {_LABEL.replace("g.sku", "s.sku").replace("g.tenant_id", ":t")}) AS label
    FROM skus s JOIN cmo_generation g ON g.tenant_id = :t AND g.sku = s.sku AND g.status = 'COMPLETE' AND g.marketplace IS NOT NULL
    GROUP BY s.sku, s.last_at, g.marketplace ORDER BY s.last_at DESC, s.sku
    """
)


def products(tenant_id: UUID, *, q: str | None, limit: int) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_PRODUCTS, {"t": tenant_id, "limit": limit}).all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        p = out.setdefault(r.sku, {"sku": r.sku, "label": r.label or r.sku, "lastGeneratedAt": _iso(r.last_at), "counts": {}})
        p["counts"][r.marketplace] = int(r.n)
    items = list(out.values())
    pat = (q or "").strip().lower()
    return [p for p in items if not pat or pat in p["sku"].lower() or pat in p["label"].lower()]


# ---- trends ---------------------------------------------------------------------------------------------------------------

_TRENDS = text(
    """
    SELECT g.id, g.created_at, g.status, r.sections, r.interpretation,
           COALESCE((SELECT array_agg(n.term ORDER BY n.term) FROM cmo_niche_term n
                     WHERE n.tenant_id = g.tenant_id AND n.id = ANY(r.niche_term_ids)), ARRAY[]::text[]) AS terms
    FROM cmo_generation g JOIN cmo_trend_report r ON r.tenant_id = g.tenant_id AND r.generation_id = g.id
    WHERE g.tenant_id = :t AND g.output_type = 'TREND_REPORT' AND g.status = 'COMPLETE'
    ORDER BY g.created_at DESC, g.id OFFSET :offset LIMIT :limit
    """
)


def _finding(f: Mapping[str, Any]) -> dict[str, Any]:
    sources = [s for s in (f.get("sources") or []) if isinstance(s, dict)]
    first = sources[0] if sources else {}
    theme, summary = str(f.get("theme") or "").strip(), str(f.get("summary") or "").strip()
    return {
        "text": f"{theme}. {summary}" if theme and summary else (theme or summary),
        "sourceName": first.get("title") or "Source name not stated",
        "sourceUrl": first.get("url"),
        "publishedAt": first.get("published_at"),  # None when the source states none: the UI says "publication date not stated"
        "retrievedAt": first.get("retrieved_at"),
        "corroboration": f.get("corroboration"),
        "sources": [{"name": s.get("title"), "url": s.get("url"), "publishedAt": s.get("published_at"), "retrievedAt": s.get("retrieved_at")} for s in sources],
    }


def trends(tenant_id: UUID, *, offset: int, limit: int) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_TRENDS, {"t": tenant_id, "offset": offset, "limit": limit}).all()
    out = []
    for r in rows:
        sections = r.sections if isinstance(r.sections, dict) else {}
        interp = r.interpretation if isinstance(r.interpretation, dict) else {}
        out.append({
            "generationId": str(r.id), "createdAt": _iso(r.created_at), "status": r.status, "nicheTerms": list(r.terms or []),
            "sections": [
                {"name": name, "state": str(sec.get("state")), "findings": [_finding(f) for f in (sec.get("findings") or []) if isinstance(f, dict)]}
                for name, sec in sections.items() if isinstance(sec, dict)
            ],
            "interpretationLabel": interp.get("label") if interp.get("items") else None,
            "evidenceRef": f"/api/v1/cmo/market-trends/{r.id}",
        })
    return out


# ---- titles ---------------------------------------------------------------------------------------------------------------

_USE = "e.event_kind IN ('COPIED','MARKED_USED') AND (CAST(:lb AS int) IS NULL OR e.occurred_at >= now() - make_interval(days => CAST(:lb AS int)))"


def _titles_sql(frequent: bool) -> Any:
    order = "(coalesce(u.copied,0) + coalesce(u.marked,0)) DESC, u.last_use DESC, b.generated_at DESC, b.rank" if frequent else "b.generated_at DESC, b.rank"
    where = ("WHERE b.rn = 1 AND (coalesce(u.copied,0) + coalesce(u.marked,0)) > 0 AND (coalesce(u.copied,0) + coalesce(u.marked,0)) >= :minc" if frequent else "")
    return text(
        f"""
        WITH base AS (
          SELECT o.id AS option_id, g.id AS generation_id, o.rank, o.title_text, o.char_count, fc.title_max_chars, fc.source_url, fc.verified_at,
                 g.sku, {_LABEL} AS label, g.marketplace, g.created_at AS generated_at, ar.investigation_id,
                 a.id AS approval_id, a.approved_at, a.edited_by_seller, lower(btrim(o.title_text)) AS k,
                 row_number() OVER (PARTITION BY g.sku, lower(btrim(o.title_text)) ORDER BY g.created_at DESC, o.rank) AS rn
          FROM cmo_title_option o
          JOIN cmo_generation g ON g.tenant_id = o.tenant_id AND g.id = o.generation_id
          LEFT JOIN format_constraint fc ON fc.id = g.format_constraint_ref
          LEFT JOIN agent_run ar ON ar.tenant_id = g.tenant_id AND ar.id = g.agent_run_id
          LEFT JOIN LATERAL (SELECT a2.id, a2.approved_at, a2.edited_by_seller FROM cmo_title_approval a2
                             WHERE a2.tenant_id = g.tenant_id AND a2.option_id = o.id ORDER BY a2.approved_at DESC LIMIT 1) a ON true
          WHERE o.tenant_id = :t AND g.status = 'COMPLETE' AND g.marketplace = :mp
            AND (CAST(:sku AS text) IS NULL OR g.sku = :sku)
            AND (CAST(:q AS text) IS NULL OR o.title_text ILIKE :q ESCAPE '\\')
            AND (NOT :approved_only OR a.id IS NOT NULL)
            AND (CAST(:from AS timestamptz) IS NULL OR g.created_at >= CAST(:from AS timestamptz))
            AND (CAST(:to AS timestamptz) IS NULL OR g.created_at <= CAST(:to AS timestamptz))
        ), u AS (
          SELECT g2.sku, lower(btrim(o2.title_text)) AS k,
                 count(*) FILTER (WHERE e.event_kind = 'GENERATED') AS generated,
                 count(*) FILTER (WHERE e.event_kind = 'VIEWED') AS viewed,
                 count(*) FILTER (WHERE e.event_kind = 'COPIED' AND {_USE.split(" AND ", 1)[1]}) AS copied,
                 count(*) FILTER (WHERE e.event_kind = 'MARKED_USED' AND {_USE.split(" AND ", 1)[1]}) AS marked,
                 min(e.occurred_at) FILTER (WHERE {_USE}) AS since, max(e.occurred_at) FILTER (WHERE {_USE}) AS last_use
          FROM cmo_result_usage_event e
          JOIN cmo_title_option o2 ON o2.tenant_id = e.tenant_id AND o2.id = e.option_id
          JOIN cmo_generation g2 ON g2.tenant_id = o2.tenant_id AND g2.id = o2.generation_id
          WHERE e.tenant_id = :t AND g2.marketplace = :mp GROUP BY g2.sku, lower(btrim(o2.title_text))
        )
        SELECT b.*, u.generated, u.viewed, u.copied, u.marked, u.since
        FROM base b LEFT JOIN u ON u.sku IS NOT DISTINCT FROM b.sku AND u.k = b.k
        {where}
        ORDER BY {order} OFFSET :offset LIMIT :limit
        """
    )


_TITLES = {False: _titles_sql(False), True: _titles_sql(True)}
_USE_AVAILABLE = text(
    "SELECT min(occurred_at) AS since FROM cmo_result_usage_event WHERE tenant_id = :t AND event_kind IN ('COPIED','MARKED_USED')"
)


def use_events_since(tenant_id: UUID) -> datetime | None:
    """Timestamp of the first recorded COPIED / MARKED_USED event of the tenant, or None when there is none (-> "Frequently used unavailable")."""
    with tenant_scope(tenant_id) as conn:
        return conn.execute(_USE_AVAILABLE, {"t": tenant_id}).scalar()


def titles(
    tenant_id: UUID, *, marketplace: str, sku: str | None, q: str | None, frequent: bool, approved_only: bool,
    date_from: datetime | None, date_to: datetime | None, lookback_days: int | None, min_count: int | None, offset: int, limit: int,
) -> list[dict[str, Any]]:
    params = {"t": tenant_id, "mp": marketplace, "sku": sku, "q": like_pattern(q), "approved_only": approved_only, "from": date_from, "to": date_to,
              "lb": lookback_days, "minc": min_count or 1, "offset": offset, "limit": limit}
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_TITLES[frequent], params).all()
    out = []
    for r in rows:
        has_usage = any(v for v in (r.generated, r.viewed, r.copied, r.marked))
        out.append({
            "generationId": str(r.generation_id), "optionId": str(r.option_id), "rank": r.rank, "titleText": r.title_text, "charCount": r.char_count,
            "maxChars": r.title_max_chars,
            "constraint": {"sourceUrl": r.source_url, "verifiedAt": _iso(r.verified_at)} if r.source_url else None,
            "approved": {"approvalId": str(r.approval_id), "approvedAt": _iso(r.approved_at), "editedBySeller": bool(r.edited_by_seller)} if r.approval_id else None,
            "sku": r.sku or "", "productLabel": r.label or r.sku or "", "marketplace": r.marketplace, "generatedAt": _iso(r.generated_at),
            "origin": _origin(r.investigation_id),
            "usage": {"generated": int(r.generated or 0), "viewed": int(r.viewed or 0), "copied": int(r.copied or 0), "markedUsed": int(r.marked or 0),
                      "since": _iso(r.since)} if has_usage else None,
        })
    return out


# ---- copy packs -----------------------------------------------------------------------------------------------------------

_PACKS = text(
    f"""
    SELECT g.id, g.marketplace, g.sku, {_LABEL} AS label, g.created_at, g.output_structured AS s, g.grounding_basis,
           fc.bullet_max_chars, fc.description_max_chars, fc.backend_terms_max_bytes, fc.count_rule AS fc_rule,
           ar.investigation_id, a.id AS approval_id, a.approved_text,
           bt.output_structured AS bt_s
    FROM cmo_generation g
    LEFT JOIN format_constraint fc ON fc.id = g.format_constraint_ref
    LEFT JOIN agent_run ar ON ar.tenant_id = g.tenant_id AND ar.id = g.agent_run_id
    LEFT JOIN cmo_title_approval a ON a.tenant_id = g.tenant_id AND a.id = g.grounding_approval_id
    LEFT JOIN LATERAL (SELECT b.output_structured FROM cmo_generation b
                       WHERE b.tenant_id = g.tenant_id AND b.output_type = 'BACKEND_TERMS' AND b.status = 'COMPLETE'
                         AND g.grounding_approval_id IS NOT NULL AND b.grounding_approval_id = g.grounding_approval_id
                       ORDER BY b.created_at DESC LIMIT 1) bt ON true
    WHERE g.tenant_id = :t AND g.output_type = 'LISTING_COPY' AND g.status = 'COMPLETE' AND g.marketplace = :mp
      AND (CAST(:sku AS text) IS NULL OR g.sku = :sku)
      AND (CAST(:q AS text) IS NULL OR CAST(g.output_structured AS text) ILIKE :q ESCAPE '\\')
    ORDER BY g.created_at DESC, g.id OFFSET :offset LIMIT :limit
    """
)


def copy_packs(tenant_id: UUID, *, marketplace: str, sku: str | None, q: str | None, offset: int, limit: int) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_PACKS, {"t": tenant_id, "mp": marketplace, "sku": sku, "q": like_pattern(q), "offset": offset, "limit": limit}).all()
    out = []
    for r in rows:
        s = r.s if isinstance(r.s, dict) else {}
        rule = s.get("count_rule") or r.fc_rule
        desc = str(s.get("description") or "")
        bt = r.bt_s if isinstance(r.bt_s, dict) else None
        joined = str(bt.get("joined") or "") if bt else ""
        provenance = s.get("provenance") if isinstance(s.get("provenance"), dict) else {}
        out.append({
            "generationId": str(r.id), "marketplace": r.marketplace, "sku": r.sku or "", "productLabel": r.label or r.sku or "",
            "groundedOn": {"approvalId": str(r.approval_id) if r.approval_id else None,
                           "titleText": r.approved_text or str(provenance.get("grounding_title") or ""), "basis": r.grounding_basis or "UNKNOWN"},
            "bullets": [{"text": b, "chars": _count(b, rule), "max": r.bullet_max_chars} for b in _strs(s.get("bullets"))],
            "description": {"text": desc, "chars": _count(desc, rule), "max": r.description_max_chars},
            "backendTerms": ({"text": joined, "bytes": bt.get("byte_count") if isinstance(bt.get("byte_count"), int) else utf8_bytes(joined),
                              "maxBytes": bt.get("max_bytes") if bt.get("max_bytes") is not None else r.backend_terms_max_bytes} if bt and joined else None),
            "generatedAt": _iso(r.created_at), "origin": _origin(r.investigation_id), "labels": [r.grounding_basis] if r.grounding_basis else [],
        })
    return out


# ---- hashtags -------------------------------------------------------------------------------------------------------------

_HASHTAGS = text(
    f"""
    SELECT g.id, g.sku, {_LABEL} AS label, g.created_at, g.output_structured AS s, ar.investigation_id
    FROM cmo_generation g LEFT JOIN agent_run ar ON ar.tenant_id = g.tenant_id AND ar.id = g.agent_run_id
    WHERE g.tenant_id = :t AND g.output_type = 'HASHTAGS' AND g.status = 'COMPLETE'
      AND (CAST(:sku AS text) IS NULL OR g.sku = :sku)
      AND (CAST(:q AS text) IS NULL OR CAST(g.output_structured->'hashtags' AS text) ILIKE :q ESCAPE '\\')
    ORDER BY g.created_at DESC, g.id OFFSET :offset LIMIT :limit
    """
)


def hashtags(tenant_id: UUID, *, sku: str | None, q: str | None, offset: int, limit: int) -> list[dict[str, Any]]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(_HASHTAGS, {"t": tenant_id, "sku": sku, "q": like_pattern(q), "offset": offset, "limit": limit}).all()
    return [
        {"generationId": str(r.id), "sku": r.sku or "", "productLabel": r.label or r.sku or "",
         "hashtags": _strs((r.s or {}).get("hashtags") if isinstance(r.s, dict) else None), "generatedAt": _iso(r.created_at), "origin": _origin(r.investigation_id)}
        for r in rows
    ]


# ---- compliance (counts of what deterministic validation already stored; nothing else) -------------------------------------

_COMPLIANCE_TITLES = text(
    """
    SELECT count(*) FILTER (WHERE (o.constraint_check->>'passed') = 'true') AS passed, count(*) AS total
    FROM cmo_title_option o JOIN cmo_generation g ON g.tenant_id = o.tenant_id AND g.id = o.generation_id
    WHERE o.tenant_id = :t AND g.status = 'COMPLETE'
      AND (CAST(:sku AS text) IS NULL OR g.sku = :sku) AND (CAST(:mp AS text) IS NULL OR g.marketplace = :mp)
    """
)
_COMPLIANCE_SHORT = text(
    """
    SELECT count(*) FILTER (WHERE (g.output_structured->>'short') = 'true') AS short, count(*) AS sets
    FROM cmo_generation g WHERE g.tenant_id = :t AND g.output_type = 'TITLE_SET' AND g.status = 'COMPLETE'
      AND (CAST(:sku AS text) IS NULL OR g.sku = :sku) AND (CAST(:mp AS text) IS NULL OR g.marketplace = :mp)
    """
)
_COMPLIANCE_RISK = text(
    """
    SELECT f->>'policy_risk' AS risk, count(*) AS n
    FROM cmo_trend_report r JOIN cmo_generation g ON g.tenant_id = r.tenant_id AND g.id = r.generation_id,
         LATERAL jsonb_path_query(r.sections, '$.*.findings[*]') f
    WHERE r.tenant_id = :t AND g.status = 'COMPLETE' AND f->>'policy_risk' IS NOT NULL GROUP BY 1
    """
)


def compliance(tenant_id: UUID, *, sku: str | None, marketplace: str | None) -> list[dict[str, Any]]:
    p = {"t": tenant_id, "sku": sku, "mp": marketplace}
    counts: list[dict[str, Any]] = []
    with tenant_scope(tenant_id) as conn:
        t = conn.execute(_COMPLIANCE_TITLES, p).one()
        sh = conn.execute(_COMPLIANCE_SHORT, p).one()
        risks = conn.execute(_COMPLIANCE_RISK, {"t": tenant_id}).all() if sku is None and marketplace is None else []
    if t.total:
        counts.append({"label": "Title options that passed the stored length check", "count": int(t.passed), "basis": "cmo_title_option.constraint_check"})
        counts.append({"label": "Title options stored", "count": int(t.total), "basis": "cmo_title_option"})
    if sh.sets:
        counts.append({"label": "Title sets returned short of the requested number", "count": int(sh.short), "basis": "cmo_generation.output_structured.short"})
    for r in sorted(risks, key=lambda x: x.risk):
        counts.append({"label": f"Reported tactics with policy risk {r.risk}", "count": int(r.n), "basis": "cmo_trend_report findings policy_risk (stored)"})
    return counts


# ---- usage events (the one write) -----------------------------------------------------------------------------------------


class NotFound(Exception):
    pass


_GEN_EXISTS = text("SELECT 1 FROM cmo_generation WHERE tenant_id = :t AND id = :g AND status = 'COMPLETE' AND output_type <> 'TREND_REPORT'")
_OPT_EXISTS = text("SELECT 1 FROM cmo_title_option WHERE tenant_id = :t AND id = :o AND generation_id = :g")
_INSERT_EVENT = text(
    """
    INSERT INTO cmo_result_usage_event (tenant_id, generation_id, option_id, result_part, event_kind, actor_user_id, surface)
    SELECT :t, :g, :o, :part, :kind, :u, :surface
    WHERE NOT EXISTS (
      SELECT 1 FROM cmo_result_usage_event x
      WHERE x.tenant_id = :t AND x.actor_user_id = :u AND x.generation_id = :g AND x.option_id IS NOT DISTINCT FROM :o
        AND x.result_part IS NOT DISTINCT FROM :part AND x.event_kind = :kind
        AND x.occurred_at > now() - make_interval(secs => :window)
    )
    """
)


def record_usage(
    tenant_id: UUID, user_id: UUID, *, generation_id: UUID, option_id: UUID | None, result_part: str | None, kind: str, surface: str, dedup_seconds: int | None
) -> bool:
    """Append one event; True when written, False when collapsed into an identical recent one. A foreign / unknown / non-copyable id raises NotFound (the route's 404)."""
    if kind not in ("VIEWED", "COPIED", "MARKED_USED"):  # defence in depth: GENERATED is written by the database triggers only
        raise ValueError("only VIEWED, COPIED and MARKED_USED may be recorded by a client")
    with tenant_scope(tenant_id) as conn:
        if conn.execute(_GEN_EXISTS, {"t": tenant_id, "g": generation_id}).first() is None:
            raise NotFound()
        if option_id is not None and conn.execute(_OPT_EXISTS, {"t": tenant_id, "o": option_id, "g": generation_id}).first() is None:
            raise NotFound()
        res = conn.execute(_INSERT_EVENT, {"t": tenant_id, "g": generation_id, "o": option_id, "part": result_part, "kind": kind, "u": user_id,
                                           "surface": surface, "window": float(dedup_seconds or 1)})
        return res.rowcount == 1
