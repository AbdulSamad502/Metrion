"""gst_lookup_result repository — deterministic-engine.md §8.4 / §8.4.1.

Three functions, mirroring this package's other repositories' thin-mapping discipline (no
calculation, no interpretation of the result here):

- `save()` — append-only insert (§8.4.1's L6 mechanism: "old row retained for audit history,
  not deleted — consistent with never mutating a prior `gst_lookup_result` in place"). There
  is no `update()`/`delete()` function in this module at all — not merely an unused
  capability, an absent one, matching the migration's own `GRANT SELECT, INSERT` (no `UPDATE`/
  `DELETE` for `metrion_app`).
- `find_cached()` — the TTL-gated cache-hit/cache-miss check §8.4.1 requires before a fresh
  fetch runs: "before reusing a cached `gst_lookup_result` row for a query, G2 computes
  `now - retrieved_at`; if it exceeds 14 days, the row is not reused." Returns `None` on a
  cache miss (no row at all, or the most recent row is stale) — the caller (`lookup.py`'s
  future composition-root wiring, G3) is responsible for running `gst_applicability_lookup`
  fresh in that case, this function never triggers a fetch itself.
- `count_for_tenant()` — G3's addition: real, live-queried usage of this tenant's
  `gst_lookup_result` rows, for `backend.entitlement.resolve_gst_lookup_entitlement` (OP9's
  shared-service cap) to report from day one — mirrors `competitor_url_repo.count_active`'s
  own "real usage, not a stub number" precedent (see that function's own docstring in
  `backend/src/backend/entitlement.py`). Counts every row ever inserted (append-only, L6), not
  just cache-fresh ones — a future volume cap is about how many lookups were RUN, not how many
  are currently reusable from cache.
- `get_by_id()` — this checkpoint's (G4, deterministic-engine.md §7.2.1/§8.4 L2) addition: a
  plain tenant-scoped read of one row by id, for `backend.services.cfo_actions.
  accept_gst_lookup_result` to read back the REAL stored `likely_rate_pct`/`likely_hsn`/
  `likely_category` before creating a `gst_rate_override` manual_adjustment — never trusting a
  client-supplied value for those fields. Mirrors `find_cached`'s query style exactly (plain
  SELECT, no interpretation of the row here); RLS makes a cross-tenant id and a genuinely
  nonexistent id indistinguishable -> both return `None`, by design, same as every other
  repository in this package.

All three go through `tenant_scope()`, the same as every other repository in this package —
`gst_lookup_result` carries real per-tenant rows (unlike the platform-owned reference tables
`config_repo.py` reads), so there is no tenant-agnostic path here at all.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any
from uuid import UUID

from sqlalchemy import text

from calc_engine.gst_lookup.types import GstLookupResult
from calc_engine.repositories.tenant_context import tenant_scope

_DEFAULT_TTL_DAYS = 14  # §8.4.1's chosen TTL.

_INSERT_SQL = text(
    """
    INSERT INTO gst_lookup_result
        (id, tenant_id, sku, query_text, query_hsn, likely_rate_pct, likely_hsn,
         likely_category, ambiguity_note, alternatives, source_url, source_title,
         retrieved_at, status, verified_by, verified_at)
    VALUES
        (:id, :tenant_id, :sku, :query_text, :query_hsn, :likely_rate_pct, :likely_hsn,
         :likely_category, :ambiguity_note, CAST(:alternatives AS jsonb), :source_url,
         :source_title, :retrieved_at, :status, :verified_by, :verified_at)
    """
)


def _alternatives_to_json(alternatives: tuple[dict[str, Any], ...]) -> str:
    """`rate_pct` inside each alternative dict may be a `Fraction` — not directly
    JSON-serialisable — stored as its exact string form (`str(Fraction(...))`, e.g. "18" or
    "37/2"), never coerced to a float (no float anywhere in a money/rate-adjacent path)."""

    def _safe(value: Any) -> Any:
        return str(value) if isinstance(value, Fraction) else value

    return json.dumps([{k: _safe(v) for k, v in alt.items()} for alt in alternatives])


def save(tenant_id: UUID, result: GstLookupResult) -> UUID:
    """Append-only insert of a `GstLookupResult` already constructed by
    `gst_lookup.lookup.gst_applicability_lookup`. Never mutates a prior row — a fresh lookup
    for the same query always inserts a new row with a new `id` (§8.4.1's L6 mechanism)."""
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            _INSERT_SQL,
            {
                "id": str(result.id),
                "tenant_id": str(tenant_id),
                "sku": result.sku,
                "query_text": result.query_text,
                "query_hsn": result.query_hsn,
                "likely_rate_pct": (
                    str(result.likely_rate_pct) if result.likely_rate_pct is not None else None
                ),
                "likely_hsn": result.likely_hsn,
                "likely_category": result.likely_category,
                "ambiguity_note": result.ambiguity_note,
                "alternatives": _alternatives_to_json(result.alternatives),
                "source_url": result.source_url,
                "source_title": result.source_title,
                "retrieved_at": result.retrieved_at,
                "status": result.status,
                "verified_by": result.verified_by,
                "verified_at": result.verified_at,
            },
        )
    return result.id


_FIND_LATEST_SQL = text(
    """
    SELECT id, tenant_id, sku, query_text, query_hsn, likely_rate_pct, likely_hsn,
           likely_category, ambiguity_note, alternatives, source_url, source_title,
           retrieved_at, status, verified_by, verified_at
    FROM gst_lookup_result
    WHERE query_text = :query_text
      AND (CAST(:query_hsn AS text) IS NULL AND query_hsn IS NULL OR query_hsn = :query_hsn)
    ORDER BY retrieved_at DESC
    LIMIT 1
    """
)


def find_cached(
    tenant_id: UUID,
    *,
    query_text: str,
    query_hsn: str | None = None,
    now: datetime,
    ttl_days: int = _DEFAULT_TTL_DAYS,
) -> dict[str, object] | None:
    """The most recent `gst_lookup_result` row for this exact `(query_text, query_hsn)` pair,
    or `None` on a cache miss — either no row exists at all, or the most recent one is older
    than `ttl_days` (§8.4.1: "if it exceeds 14 days, the row is not reused"). Per L6, this
    function is only ever a *lookup*; it never applies the cached row's `likely_rate_pct` to a
    calculation, and it never re-fetches on the caller's behalf — a cache miss is the caller's
    signal to run `gst_applicability_lookup` fresh."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _FIND_LATEST_SQL, {"query_text": query_text, "query_hsn": query_hsn}
        ).first()

    if row is None:
        return None

    row_dict = dict(row._mapping)
    retrieved_at: datetime = row_dict["retrieved_at"]
    if now - retrieved_at > timedelta(days=ttl_days):
        return None  # stale — TTL exceeded, not reused (§8.4.1).
    return row_dict


_COUNT_SQL = text("SELECT count(*) FROM gst_lookup_result")


def count_for_tenant(tenant_id: UUID) -> int:
    """Real, live-queried count of every `gst_lookup_result` row this tenant has ever had
    inserted (append-only, L6) — see module docstring for why this exists and what it feeds."""
    with tenant_scope(tenant_id) as conn:
        return int(conn.execute(_COUNT_SQL).scalar() or 0)


_GET_BY_ID_SQL = text(
    """
    SELECT id, tenant_id, sku, query_text, query_hsn, likely_rate_pct, likely_hsn,
           likely_category, ambiguity_note, alternatives, source_url, source_title,
           retrieved_at, status, verified_by, verified_at
    FROM gst_lookup_result
    WHERE id = :id
    """
)


def get_by_id(tenant_id: UUID, result_id: UUID) -> dict[str, Any] | None:
    """Tenant-scoped read of exactly one `gst_lookup_result` row by id (G4 addition — see
    module docstring). Returns the raw row dict, uninterpreted, exactly as `find_cached` does —
    `None` when no row with this id exists for this tenant (including when the id belongs to
    another tenant: RLS filters it out before this function ever sees it, so a cross-tenant id
    and a genuinely nonexistent one are indistinguishable here, by design)."""
    with tenant_scope(tenant_id) as conn:
        row = conn.execute(_GET_BY_ID_SQL, {"id": str(result_id)}).first()
    if row is None:
        return None
    return dict(row._mapping)
