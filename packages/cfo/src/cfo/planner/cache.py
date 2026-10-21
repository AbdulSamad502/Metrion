"""Cache keying for validated plan results (cfo-query-planner.md §6.4, D2).

A key binds the plan to the tenant, the tenant's monotone `data_version`, the catalog version and the
formula versions. Any change to data, catalog or formulas yields a different key, so a stale result can
never be served and no explicit purge is needed (old keys simply expire by TTL). The tenant is part of
the key *and* the prefix, so a cross-tenant collision is impossible. Values are evidence packets only —
never raw rows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from uuid import UUID

from cfo.planner.catalog import CATALOG_VERSION
from cfo.planner.plan import QueryPlan, plan_hash


def tenant_prefix(tenant_id: UUID) -> str:
    return f"cfo:ev:{tenant_id}:"


def cache_key(
    plan: QueryPlan,
    *,
    tenant_id: UUID,
    data_version: int,
    formula_versions: Mapping[str, str],
    catalog_version: str = CATALOG_VERSION,
) -> str:
    material = json.dumps(
        {
            "plan": plan_hash(plan),
            "tenant": str(tenant_id),
            "data_version": data_version,
            "catalog": catalog_version,
            "formulas": sorted(formula_versions.items()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return tenant_prefix(tenant_id) + hashlib.sha256(material.encode()).hexdigest()
