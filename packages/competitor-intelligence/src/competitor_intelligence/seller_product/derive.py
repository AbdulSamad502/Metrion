"""Canonical-derived `SellerProduct` fields — competitor-intelligence-agent.md §5.5.1 Source
1 / §5.5.2. A read-only view over `packages/data-foundation`'s `sales_line` table: this
module never writes to `sales_line` and never invents a field `sales_line` cannot supply
(`category`, `price`, `attributes`, `keywords`, `fulfillment_type` all stay out of scope
here by design — see `seller_product_profile_repo.py` for those).

Cross-package import note: `data_foundation` is not declared as a formal dependency in this
package's `pyproject.toml`, mirroring the same documented reason `backend/pyproject.toml`
gives for not declaring `competitor-intelligence` — a relative `file:` specifier resolves
against the *installer's* cwd, not this file's directory, on a monorepo with no
workspace-aware build tool yet. Both packages are installed side by side in dev and CI
(`.github/workflows/ci.yml` installs data-foundation before competitor-intelligence), so the
import is real and exercised, just not pip-declared. See `backend/README.md`'s install order.

`sales_line` is read through `data_foundation`'s own `tenant_scope()` (its own engine, same
`DATABASE_URL_APP` role, same fail-closed contract, auth.md §7.3) — never through this
package's `tenant_scope()`, which only ever holds a connection scoped for CI's own tables.
"""

from __future__ import annotations

from uuid import UUID

from data_foundation.repositories.tenant_context import tenant_scope as data_foundation_tenant_scope
from sqlalchemy import text

from competitor_intelligence.seller_product.types import CanonicalDerived

# Most-recent `sales_line` row for the given sku/marketplace_item_id, per §5.5.2: "most-recent
# item_title/sku/marketplace_item_id per SKU." `order_date` is the best proxy for "when this
# sale happened"; the ingestion timestamps (`ingestion_run.started_at`/`finished_at`) break
# ties when `order_date` is null or repeated, so a row ingested later is preferred over an
# older ingestion of an equally-dated (or date-less) line — never an arbitrary DB row order.
_LATEST_SALES_LINE_SQL = text(
    """
    SELECT sl.sku, sl.marketplace_item_id, sl.item_title, sl.order_date,
           ir.finished_at, ir.started_at
    FROM sales_line sl
    JOIN ingestion_run ir ON ir.id = sl.ingestion_run_id
    WHERE sl.tenant_id = :tenant_id
      AND ((CAST(:sku AS text) IS NOT NULL AND sl.sku = CAST(:sku AS text))
           OR (CAST(:marketplace_item_id AS text) IS NOT NULL
               AND sl.marketplace_item_id = CAST(:marketplace_item_id AS text)))
    ORDER BY sl.order_date DESC NULLS LAST,
             ir.finished_at DESC NULLS LAST,
             ir.started_at DESC NULLS LAST
    LIMIT 1
    """
)


def derive_canonical(
    tenant_id: UUID, *, sku: str | None = None, marketplace_item_id: str | None = None
) -> CanonicalDerived | None:
    """Returns the `CanonicalDerived` half of a `SellerProduct` for this tenant's product, or
    `None` when no matching `sales_line` row exists — the caller (`merge.py`) treats `None`
    as "canonical source has nothing," never as a zero/empty `SellerProduct`.

    Exactly one of `sku`/`marketplace_item_id` must identify the product; both may be given
    (an OR match), but at least one is required — mirrors `sales_line.sku` /
    `sales_line.marketplace_item_id` both being the recognised natural identifiers (§5.5.2).
    """
    if not sku and not marketplace_item_id:
        raise ValueError("derive_canonical() requires sku or marketplace_item_id — got neither")

    with data_foundation_tenant_scope(tenant_id) as conn:
        row = conn.execute(
            _LATEST_SALES_LINE_SQL,
            {"tenant_id": str(tenant_id), "sku": sku, "marketplace_item_id": marketplace_item_id},
        ).mappings().first()

    if row is None:
        return None

    product_id = row["sku"] or row["marketplace_item_id"]
    if product_id is None:
        # A sales_line row matched by marketplace_item_id but itself carries neither
        # column populated is not expected in practice, but refuse to fabricate an id
        # rather than return a CanonicalDerived with product_id=None (C30).
        return None

    last_updated = row["finished_at"] or row["started_at"]
    return CanonicalDerived(product_id=product_id, title=row["item_title"], last_updated=last_updated)
