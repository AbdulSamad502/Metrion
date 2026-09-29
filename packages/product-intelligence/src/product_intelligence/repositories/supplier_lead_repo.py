"""supplier_lead — `product-intelligence-agent.md` §6.6. Discovery only, never ranked here
or anywhere in PI (C4) — CFO ranks, from seller-supplied quotes only.

**Checkpoint 1 scaffolding only** — every function below is a `NotImplementedError` stub.
Every function takes `tenant_id` first, per CI's convention.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def insert_lead(
    tenant_id: UUID,
    *,
    run_id: UUID,
    supplier_name: str,
    source: str,
    contact: dict[str, Any] | None,
    locality: str | None,
    distance_km: Decimal | None,
    category_match: str | None,
    source_url: str | None,
    fetched_at: datetime,
) -> UUID:
    """`source` is `GOOGLE_PLACES` | `TAVILY` | `INDIAMART_LOOKUP` — IndiaMART is not
    implemented in this build (plan's Context; deferred pending a commercial partnership),
    so no caller in Checkpoint 2 passes that value yet."""
    raise NotImplementedError("supplier_lead_repo.insert_lead: Checkpoint 2")


def list_leads_for_run(tenant_id: UUID, run_id: UUID) -> list[dict[str, Any]]:
    raise NotImplementedError("supplier_lead_repo.list_leads_for_run: Checkpoint 2")
